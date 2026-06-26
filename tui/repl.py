"""
GrassFlow REPL — 基于 prompt_toolkit 的交互式 TUI
组合 layout / slash_commands / agent_integration / fallback 模块实现。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import traceback
from typing import Any, Dict, List, Optional

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout

from core.config import config_manager
from tui.agent_integration import AgentIntegration
from tui.fallback import run_fallback_mode
from tui.layout import (
    BANNER, DEFAULT_MODEL, DEFAULT_PROVIDER, MAX_OUTPUT_LINES,
    OutputEntry, REPLMode, REPLTheme, BUILTIN_THEMES,
    build_pt_style, build_layout_from_repl, build_keybindings_from_repl,
)
from tui.session import SessionInfo, session_manager
from tui.slash_commands import SlashCommandCompleter, command_registry

# 滚动到底部的哨兵值（prompt_toolkit 会 clamp 到实际最大值）
SCROLL_TO_BOTTOM = 10**6


class GrassFlowREPL:
    """GrassFlow 交互式 REPL（prompt_toolkit + 模块组合）"""

    # 延迟导入的命令处理函数缓存
    _CMD_HANDLERS: Optional[Dict[str, Any]] = None

    def __init__(self, theme: Optional[REPLTheme] = None, enable_session: bool = True, enable_streaming: bool = True):
        self._theme = theme or self._load_theme()
        self.session: Optional[SessionInfo] = None
        self.session_mgr = session_manager if enable_session else None
        self._enable_session = enable_session
        self._agent = AgentIntegration(
            config_manager=config_manager, session_manager=self.session_mgr, enable_streaming=enable_streaming,
        )
        self.output: List[OutputEntry] = []
        self.mode = REPLMode.NORMAL
        self._running = False
        self._should_exit = False
        self._output_window = None
        self._input_queue: queue.Queue = queue.Queue()
        self._completer = SlashCommandCompleter()
        self.app: Optional[Application] = None
        self.input_buffer = Buffer(
            multiline=True, completer=self._completer, complete_while_typing=True,
            accept_handler=None,  # 不使用 accept_handler，用自定义 Enter 绑定（hermes 模式）
        )
        self.kb = KeyBindings()
        self._undo_stack: List[OutputEntry] = []
        self._redo_stack: List[OutputEntry] = []
        self._token_count = 0
        self._token_limit = 128000
        self._last_latency_ms = 0
        self._api_call_count = 0
        self._setup_keybindings()

    # ==================== 主题 ====================

    def _load_theme(self) -> REPLTheme:
        try:
            theme_name = config_manager.get("display.theme", "default")
            return BUILTIN_THEMES.get(theme_name, BUILTIN_THEMES["default"])
        except Exception:
            return BUILTIN_THEMES["default"]

    def switch_theme(self, name: str) -> bool:
        if name in BUILTIN_THEMES:
            self._theme = BUILTIN_THEMES[name]
            if self.app:
                self.app.style = build_pt_style(self._theme)
            return True
        return False

    @property
    def theme_names(self) -> List[str]:
        return list(BUILTIN_THEMES.keys())

    # ==================== 属性访问器（向后兼容） ====================

    @property
    def _agent_running(self) -> bool:
        return self._agent.is_running

    @property
    def _agent_loop(self) -> Any:
        return self._agent._agent_loop

    @property
    def _ui_update_queue(self) -> queue.Queue:
        return self._agent._ui_update_queue

    @property
    def _enable_streaming(self) -> bool:
        return self._agent._enable_streaming

    # ==================== 输出管理 ====================

    def add_output(self, text: str, role: str = "system", metadata: Optional[Dict[str, Any]] = None) -> None:
        entry = OutputEntry(text=text, role=role, metadata=metadata)
        self.output.append(entry)
        if len(self.output) > MAX_OUTPUT_LINES:
            self.output = self.output[len(self.output) - MAX_OUTPUT_LINES:]
        # 自动滚动到底部
        if self._output_window:
            self._output_window.vertical_scroll = SCROLL_TO_BOTTOM
        # Bug 3 修复：触发重绘（refresh_interval=0 时必须显式 invalidate）
        if self.app:
            self.app.invalidate()

    def clear_output(self) -> None:
        self.output.clear()

    # ==================== 布局 / 快捷键（委托给 tui.layout） ====================

    def _build_layout(self) -> Layout:
        return build_layout_from_repl(self)

    def _setup_keybindings(self) -> None:
        self.kb = build_keybindings_from_repl(self)

    # ==================== 快捷键回调委托 ====================

    def _delegate_cmd(self, name: str) -> None:
        """通用委托：将快捷键回调分发给 slash_commands 模块中的处理函数"""
        if GrassFlowREPL._CMD_HANDLERS is None:
            from tui.slash_commands import (
                _handle_compact, _handle_new_session, _handle_list_sessions,
                _handle_undo, _handle_redo, _handle_list_models,
            )
            GrassFlowREPL._CMD_HANDLERS = {
                "compact": _handle_compact, "new_session": _handle_new_session,
                "list_sessions": _handle_list_sessions, "undo": _handle_undo,
                "redo": _handle_redo, "list_models": _handle_list_models,
            }
        GrassFlowREPL._CMD_HANDLERS[name](self)

    def _handle_compact(self) -> None:
        self._delegate_cmd("compact")

    def _handle_new_session(self) -> None:
        self._delegate_cmd("new_session")

    def _handle_list_sessions(self) -> None:
        self._delegate_cmd("list_sessions")

    def _handle_undo(self) -> None:
        self._delegate_cmd("undo")

    def _handle_redo(self) -> None:
        self._delegate_cmd("redo")

    def _handle_list_models(self) -> None:
        self._delegate_cmd("list_models")

    def _reset_stats(self) -> None:
        self._token_count = 0
        self._last_latency_ms = 0
        self._api_call_count = 0

    # ==================== 输入处理 ====================

    def _process_user_input(self, text: str) -> None:
        """处理用户输入（由 Enter 键绑定调用，不经过 accept_handler）

        参考 hermes 模式：直接处理输入，/exit 时设置标志并延迟调用 app.exit()。
        使用 create_background_task 延迟退出，避免在 keybinding handler 内
        同步调用 app.exit() 导致 "Return value already set" 崩溃。
        """
        if text.startswith("/"):
            if self._handle_slash_command(text):
                # /exit 命令：延迟退出，避免 keybinding handler 内同步调用 app.exit()
                self._should_exit = True
                if self.app and self.app.is_running:
                    async def _deferred_exit():
                        self.app.exit()
                    self.app.create_background_task(_deferred_exit())
            return
        if text.startswith("!"):
            shell_cmd = text[1:].strip()
            self.add_output(f"! {shell_cmd}", role="user")
            self._execute_shell(shell_cmd)
            return
        self._handle_agent_message(text)

    def _handle_slash_command(self, text: str) -> bool:
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        if cmd.startswith("/"):
            cmd = cmd[1:]
        cmd_def = command_registry.get(cmd)
        if cmd_def:
            command_registry.execute(cmd, args, self)
            return cmd_def.name == "exit"
        self.add_output(f"Unknown command: /{cmd}. Type /help for available commands.", role="error")
        return False

    def _handle_agent_message(self, text: str) -> None:
        self.add_output(text, role="user")
        if not self._agent.is_initialized:
            self.add_output(
                "No agent loop available. Set up an LLM provider to enable AI responses.\n"
                "Use /help for available commands.", role="system",
            )
            return
        if self.app and self.app.loop and self.app.loop.is_running():
            self.app.loop.create_task(self._run_agent_loop_async(text))
        else:
            self._agent.process_in_background(
                text=text, history=self._build_history(), system_prompt=self._get_system_prompt(),
            )

    # ==================== Agent Loop 事件处理 ====================

    def _apply_event(self, etype: str, edata: dict, inv: Any = None) -> bool:
        """将 Agent Loop 事件应用到 self.output。返回 True 表示应中断循环。"""
        if inv is None:
            inv = lambda: self.app.invalidate() if self.app else None
        if etype == "text_delta":
            token = edata.get("text", "")
            if self.output and self.output[-1].role == "assistant":
                self.output[-1].text += token
            else:
                self.add_output(token, role="assistant")
            # Bug 1 修复：流式 token 直接修改 output 后触发自动滚动
            if self._output_window:
                self._output_window.vertical_scroll = SCROLL_TO_BOTTOM
            inv()
        elif etype == "text_end":
            inv()
        elif etype == "thinking_delta":
            token = edata.get("text", "")
            if (self.output and self.output[-1].role == "system"
                    and self.output[-1].text.startswith("[thinking]")):
                self.output[-1].text += token
            else:
                self.add_output(f"[thinking] {token}", role="system")
            # Bug 1 修复：thinking token 直接修改 output 后触发自动滚动
            if self._output_window:
                self._output_window.vertical_scroll = SCROLL_TO_BOTTOM
            inv()
        elif etype == "tool_call_start":
            self.add_output(f"[tool] Calling {edata.get('name', '?')}...", role="tool")
            if edata.get("args"):
                self.add_output(f"  args: {json.dumps(edata['args'], ensure_ascii=False)[:300]}", role="tool")
            inv()
        elif etype == "tool_result":
            result = edata.get("result", edata.get("output", ""))
            is_err = edata.get("is_error", edata.get("success", True) is False)
            prefix = "[tool result] [ERROR] " if is_err else "[tool result] "
            self.add_output(f"{prefix}{str(result)[:500 if is_err else 800]}", role="error" if is_err else "tool")
            inv()
        elif etype == "error":
            self.add_output(f"[error] {edata.get('message', str(edata))}", role="error")
            inv()
        elif etype == "interrupted":
            self.add_output("Interrupted.", role="system")
            inv()
            return True
        elif etype == "usage":
            if isinstance(edata, dict):
                self._token_count = edata.get("total_tokens", self._token_count)
                self._api_call_count += 1
            inv()
        return False

    async def _run_agent_loop_async(self, text: str) -> None:
        """在 pt 事件循环中运行 Agent Loop（流式输出）"""
        try:
            async for event in self._agent.process_streaming(
                text=text, history=self._build_history(), system_prompt=self._get_system_prompt(),
            ):
                if self._apply_event(event.type, event.data):
                    break
        except Exception as e:
            self.add_output(f"Agent error: {e}\n{traceback.format_exc()}", role="error")
        finally:
            if self.app:
                self.app.invalidate()

    def _process_ui_updates(self) -> None:
        """消费 Agent Loop 后台线程的 UI 更新"""
        has_updates = False
        for action, kwargs in self._agent.drain_ui_updates():
            has_updates = True
            if action == "text_delta":
                token = kwargs.get("text", "")
                if self.output and self.output[-1].role == "assistant":
                    self.output[-1].text += token
                else:
                    self.add_output(token, role="assistant")
                # Bug 1 修复：流式 token 直接修改 output 后触发自动滚动
                if self._output_window:
                    self._output_window.vertical_scroll = SCROLL_TO_BOTTOM
            elif action == "thinking_delta":
                token = kwargs.get("text", "")
                if (self.output and self.output[-1].role == "system"
                        and self.output[-1].text.startswith("[thinking]")):
                    self.output[-1].text += token
                else:
                    self.add_output(f"[thinking] {token}", role="system")
                # Bug 1 修复：thinking token 直接修改 output 后触发自动滚动
                if self._output_window:
                    self._output_window.vertical_scroll = SCROLL_TO_BOTTOM
            elif action == "tool_call_start":
                self.add_output(f"[tool] Calling {kwargs.get('name', '?')}...", role="tool")
                if kwargs.get("args"):
                    self.add_output(f"  args: {json.dumps(kwargs['args'], ensure_ascii=False)[:300]}", role="tool")
            elif action == "tool_result":
                self.add_output(f"[tool result] {kwargs.get('output', '')}", role="tool")
            elif action == "error":
                self.add_output(f"[error] {kwargs.get('message', 'Unknown error')}", role="error")
            elif action == "interrupted":
                self.add_output("Interrupted.", role="system")
        # Bug 2 修复：循环结束后只 invalidate 一次，避免重入
        if has_updates and self.app:
            self.app.invalidate()

    # ==================== 辅助方法 ====================

    def _build_history(self) -> List[Dict[str, Any]]:
        messages = []
        for e in self.output:
            if e.role == "user":
                messages.append({"role": "user", "content": e.text})
            elif e.role == "assistant":
                messages.append({"role": "assistant", "content": e.text})
        return messages

    def _get_system_prompt(self) -> str:
        cwd = os.getcwd()
        return (
            f"You are GrassFlow AI assistant, running inside the GrassFlow REPL.\n\n"
            f"Current directory: {cwd}\n"
            f"You can help users with:\n"
            f"- Creating and managing workflows\n- Writing code and analyzing files\n"
            f"- Running commands and debugging\n\n"
            f"Be concise and helpful. Use tools when needed to complete tasks."
        )

    def _interrupt_agent(self) -> None:
        self._agent.interrupt()

    def _execute_shell(self, command: str) -> None:
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            self.add_output(output[:2000], role="tool")
        except subprocess.TimeoutExpired:
            self.add_output(f"Command timed out: {command}", role="error")
        except Exception as e:
            self.add_output(f"Shell error: {e}", role="error")

    # ==================== 生命周期 ====================

    def _init_session(self) -> None:
        if self._enable_session and self.session_mgr:
            try:
                self.session = self.session_mgr.create_session(
                    title="REPL Session", directory=os.getcwd(),
                    metadata={"model": DEFAULT_MODEL, "provider": DEFAULT_PROVIDER},
                )
                self.add_output(f"Session: {self.session.id[:12]}", role="system")
            except Exception as e:
                self.add_output(f"Session init failed: {e}", role="system")
                self.session = None

    def run(self) -> None:
        self._running, self._should_exit = True, False
        self._init_session()
        if self._agent.init_agent_loop():
            self.add_output("Agent loop initialized.", role="system")
        else:
            self.add_output("AgentLoop not available. Falling back to echo mode.", role="system")
        try:
            self.app = Application(
                layout=self._build_layout(),
                key_bindings=self.kb,
                style=build_pt_style(self._theme),
                full_screen=False,       # 非全屏模式，输出向上滚动（hermes 模式）
                mouse_support=True,      # 启用鼠标事件（滚轮滚动输出区域）
                refresh_interval=0.0,    # 禁用定时重绘，避免与终端 auto-scroll 冲突
                erase_when_done=True,    # 退出时清除底部 UI chrome，不留在 scrollback 中
            )
        except Exception as e:
            self._output_buffer = [(BANNER.strip(), "system")]
            self._run_fallback(f"prompt_toolkit 不可用 ({e})，使用降级模式。输入 /exit 退出。")
            return
        self.add_output(BANNER.strip(), role="system")
        self.add_output("  GrassFlow REPL\n  Type /help for commands, /exit to quit.\n", role="system")

        def _on_invalidate(_sender=None):
            self._process_ui_updates()

        self.app.on_invalidate += _on_invalidate
        try:
            self.app.run()
        except (EOFError, KeyboardInterrupt, BrokenPipeError):
            pass
        except Exception as e:
            self.add_output(f"REPL error: {e}", role="error")
        finally:
            self._running = False
        self._cleanup()

    def _run_fallback(self, notice: str = "") -> None:
        self._running, self._should_exit = True, False
        run_fallback_mode(
            agent_integration=self._agent._agent_loop, session_manager=self.session_mgr,
            theme=self._theme, notice=notice,
        )

    def _cleanup(self) -> None:
        print("\n  Goodbye!\n")

    def stop(self) -> None:
        self._should_exit = True
        if self.app:
            self.app.exit()


class AsyncGrassFlowREPL(GrassFlowREPL):
    """支持异步事件循环的 REPL 变体"""

    async def run_async(self) -> None:
        self._running, self._should_exit = True, False
        self._init_session()
        self.add_output(BANNER.strip(), role="system")
        self.add_output("  GrassFlow REPL (async)\n  Type /help for commands, /exit to quit.\n", role="system")
        if self._agent.init_agent_loop():
            self.add_output("Agent loop initialized.", role="system")
        self.app = Application(
            layout=self._build_layout(),
            key_bindings=self.kb,
            style=build_pt_style(self._theme),
            full_screen=False,       # 非全屏模式，输出向上滚动（hermes 模式）
            mouse_support=True,      # 启用鼠标事件（滚轮滚动输出区域）
            refresh_interval=0.0,    # 禁用定时重绘，避免与终端 auto-scroll 冲突
            erase_when_done=True,    # 退出时清除底部 UI chrome，不留在 scrollback 中
        )
        # Bug 4 修复：注册 on_invalidate 钩子，与 run() 保持一致
        def _on_invalidate(_sender=None):
            self._process_ui_updates()

        self.app.on_invalidate += _on_invalidate
        try:
            await self.app.run_async()
        except (EOFError, KeyboardInterrupt, BrokenPipeError):
            pass
        except Exception as e:
            self.add_output(f"REPL error: {e}", role="error")
        finally:
            self._running = False
        self._cleanup()


# ==================== 便捷函数 ====================

def _new_create_repl(
    theme: Optional[str] = None, enable_session: bool = True, enable_streaming: bool = True,
) -> GrassFlowREPL:
    repl_theme = BUILTIN_THEMES.get(theme) if theme and theme in BUILTIN_THEMES else None
    return GrassFlowREPL(theme=repl_theme, enable_session=enable_session, enable_streaming=enable_streaming)


def run_repl(theme: Optional[str] = None, enable_session: bool = True, enable_streaming: bool = True) -> None:
    _new_create_repl(theme=theme, enable_session=enable_session, enable_streaming=enable_streaming).run()


async def run_repl_async(
    theme: Optional[str] = None, enable_session: bool = True, enable_streaming: bool = True,
) -> None:
    repl_theme = BUILTIN_THEMES.get(theme) if theme and theme in BUILTIN_THEMES else None
    await AsyncGrassFlowREPL(
        theme=repl_theme, enable_session=enable_session, enable_streaming=enable_streaming,
    ).run_async()


# ==================== 向后兼容层 ====================
# re-export 保持旧的 import 路径可用：from tui.repl import Message, MessageRole, ...

from tui.compat import (  # noqa: E402, F401
    MessageRole, Message, CommandResult, CommandHandler,
    InputHandler, MessageRenderer, REPL, create_repl,
)

if __name__ == "__main__":
    run_repl()

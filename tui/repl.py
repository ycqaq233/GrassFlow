"""
GrassFlow REPL — 基于 prompt_toolkit 的交互式 TUI（hermes patch_stdout 模式）

架构变更：
- 输出不再通过 FormattedTextControl 渲染在 widget 树中
- 所有输出通过 cprint() 打印到终端 scrollback，由终端模拟器原生处理滚动
- mouse_support=False — 禁用 prompt_toolkit 的鼠标事件拦截
- patch_stdout() 包裹 app.run() — stdout 写入重定向到终端 scrollback
- 流式输出行缓冲机制（参考 hermes _emit_stream_text）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout

from tui.config_integration import config_manager, get_theme_name
from tui.agent_integration import AgentIntegration
from tui.fallback import run_fallback_mode
from tui.permission_handler import get_permission_handler
from tui.layout import (
    BANNER, DEFAULT_MODEL, DEFAULT_PROVIDER, MAX_OUTPUT_LINES,
    OutputEntry, REPLMode, REPLTheme, BUILTIN_THEMES,
    build_pt_style, build_layout_from_repl, build_keybindings_from_repl,
    format_output_line, cprint, ChatConsole, OutputHistory,
    set_event_loop,
)
from tui.session import SessionInfo, session_manager
from tui.slash_commands import SlashCommandCompleter, command_registry, register_skill_commands


class GrassFlowREPL:
    """GrassFlow 交互式 REPL（hermes patch_stdout 模式）"""

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
        # Single source of truth for LLM conversation history (separate from display-only self.output)
        self._conversation_history: List[Dict[str, Any]] = []
        self.mode = REPLMode.NORMAL
        self._running = False
        self._should_exit = False
        self._input_queue: queue.Queue = queue.Queue()
        self._completer = SlashCommandCompleter()
        self.app: Optional[Application] = None
        # Persistent command history (up/down arrow navigation)
        _history_dir = os.path.join(os.path.expanduser("~"), ".Grass")
        os.makedirs(_history_dir, exist_ok=True)
        _history_path = os.path.join(_history_dir, "repl_history")
        self.input_buffer = Buffer(
            multiline=True, completer=self._completer, complete_while_typing=True,
            accept_handler=None,
            history=FileHistory(_history_path),
        )
        self.kb = KeyBindings()
        self._undo_stack: List[OutputEntry] = []
        self._redo_stack: List[OutputEntry] = []
        self._output_lock = threading.Lock()
        self._token_count = 0
        self._token_limit = 128000
        self._last_latency_ms = 0
        self._api_call_count = 0
        self._api_start_time: float = 0.0
        self._retry_last: bool = False
        self._tool_verbose: bool = False  # False=compact tool display, True=full output
        self._permission_mode: str = "ask"  # default permission mode: ask/allow/deny
        self._session_approvals: set = set()  # session-level tool approvals (tool names)

        # Context compressor (lazy init)
        self._compressor = None

        # 流式输出状态（hermes 模式）
        self._stream_buf: str = ""
        self._stream_box_opened: bool = False
        self._stream_collected_text: str = ""  # accumulates current streaming segment
        self._stream_full_response: str = ""   # accumulates full response across tool calls

        # Thinking stream state（可折叠思考块）
        self._thinking_buf: str = ""           # accumulated thinking text
        self._thinking_token_count: int = 0    # token counter
        self._thinking_box_opened: bool = False  # whether header was printed
        self._thinking_start_time: float = 0.0   # thinking block start time

        # Thinking toggle state (Ctrl+T)
        self._thinking_expanded: bool = False  # current thinking block display state
        self._last_thinking_content: str = ""  # full thinking text from last block
        self._last_thinking_duration: float = 0.0  # elapsed seconds
        self._last_thinking_tokens: int = 0    # token count from last block

        self._setup_keybindings()
        self._setup_approval_callback()

    # ==================== 主题 ====================

    def _load_theme(self) -> REPLTheme:
        try:
            theme_name = get_theme_name()
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

    # ==================== 输出管理（hermes cprint 模式） ====================

    @staticmethod
    def _render_md(text: str) -> str:
        """Render markdown to ANSI string using Rich's Markdown renderer.

        Returns raw text if Rich is not available or rendering fails.
        """
        try:
            from tui.md_renderer import render_markdown_to_ansi
            return render_markdown_to_ansi(text)
        except Exception:
            return text

    def _cprint_output(self, text: str, role: str = "system") -> None:
        """打印格式化输出到终端 scrollback（hermes _cprint 模式）

        For assistant messages, renders markdown to colored terminal output.
        Raw text is stored in self.output (for conversation history);
        rendered ANSI is displayed in terminal.
        """
        entry = OutputEntry(text=text, role=role)
        with self._output_lock:
            self.output.append(entry)
            if len(self.output) > MAX_OUTPUT_LINES:
                self.output = self.output[len(self.output) - MAX_OUTPUT_LINES:]
        if role != "system":
            self._redo_stack.clear()
        # For assistant messages, render markdown; otherwise use plain format
        if role == "assistant":
            rendered = self._render_md(text)
            cprint(rendered)
        else:
            formatted = format_output_line(entry)
            cprint(formatted)
        if self.app:
            self.app.invalidate()

    def _cprint_raw(self, text: str) -> None:
        """打印原始 ANSI 文本（用于流式 token）"""
        cprint(text)

    def add_output(self, text: str, role: str = "system", metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加输出并打印到终端 scrollback"""
        self._cprint_output(text, role)

    def clear_output(self) -> None:
        with self._output_lock:
            self.output.clear()
            self._undo_stack.clear()
            self._redo_stack.clear()
        self._conversation_history.clear()
        if self._compressor:
            self._compressor.reset()

    # ==================== 流式输出（hermes 行缓冲模式） ====================

    def _emit_stream_text(self, text: str) -> None:
        """流式文本发射 — 累积模式（markdown 渲染在 _flush_stream 中完成）

        During streaming, text is accumulated in _stream_collected_text.
        Markdown rendering happens when _flush_stream() is called at the end
        of each response segment (text_end or tool_call_start).
        """
        if not text:
            return
        self._stream_collected_text += text

        # Track that we have visible text (for box opened state)
        if not self._stream_box_opened:
            text_stripped = text.lstrip("\n")
            if text_stripped:
                self._stream_box_opened = True

    def _flush_stream(self) -> None:
        """刷新流式缓冲区，渲染 markdown 并输出"""
        collected = self._stream_collected_text
        if not collected:
            if self._stream_box_opened:
                self._stream_box_opened = False
            return

        # Render markdown for the collected text segment
        rendered = self._render_md(collected)
        cprint("")  # blank line separator
        cprint(rendered)

        self._stream_buf = ""
        self._stream_box_opened = False

    def _reset_stream_state(self) -> None:
        """重置流式状态（不触碰 _stream_full_response）"""
        self._stream_buf = ""
        self._stream_box_opened = False
        self._stream_collected_text = ""
        # Reset thinking state
        self._thinking_buf = ""
        self._thinking_token_count = 0
        self._thinking_box_opened = False
        self._thinking_start_time = 0.0

    def _close_thinking_block(self) -> None:
        """关闭思考块：刷新剩余缓冲区，打印摘要行，保存状态供 Ctrl+T 切换"""
        if not self._thinking_box_opened and self._thinking_token_count == 0:
            return

        thinking_cfg = self.session.metadata.get("thinking", {}) if self.session else {}
        display_mode = thinking_cfg.get("display", "collapsed")

        # Calculate elapsed time
        elapsed_s = 0.0
        if self._thinking_start_time > 0:
            elapsed_s = time.monotonic() - self._thinking_start_time

        # Save state for Ctrl+T toggle
        self._last_thinking_duration = elapsed_s
        self._last_thinking_tokens = self._thinking_token_count
        self._thinking_expanded = (display_mode == "full")

        if display_mode == "full" and self._thinking_box_opened:
            # Flush remaining buffer
            if self._thinking_buf.strip():
                cprint(f"\033[2;3m  │ {self._thinking_buf}\033[0m")
                self._thinking_buf = ""
            duration_str = f" in {elapsed_s:.1f}s" if elapsed_s > 0 else ""
            cprint(f"\033[2;3m  └ Done thinking{duration_str} ({self._thinking_token_count} tokens)\033[0m")
            cprint("")
        elif self._thinking_token_count > 0:
            # Collapsed: single summary line with duration
            duration_str = f"{elapsed_s:.1f}s" if elapsed_s > 0 else "..."
            cprint(f"\033[2;3m  \U0001f4ad Thought for {duration_str} ({self._thinking_token_count} tokens)\033[0m")

    # ==================== 布局 / 快捷键（委托给 tui.layout） ====================

    def _build_layout(self) -> Layout:
        return build_layout_from_repl(self)

    def _setup_keybindings(self) -> None:
        self.kb = build_keybindings_from_repl(self)

    def _setup_approval_callback(self) -> None:
        """设置工具审批回调到全局 PermissionHandler。

        根据 self._permission_mode 决定审批行为：
          - "allow" / "approve": 自动批准所有工具
          - "ask": 显示内联审批提示（o/s/a/d 选项）
          - "deny": 自动拒绝所有工具

        审批提示格式（参考 hermes）:
          shell: ls -la /tmp

            [o]nce  |  [s]ession  |  [a]lways  |  [d]eny

            Choice [o/s/a/D]:

        实现说明：
          使用 app.run_in_terminal() 临时挂起 prompt_toolkit Application，
          然后用 input() 读取用户输入。这比 pt_prompt() 安全得多——
          pt_prompt() 会创建自己的 Application，与正在运行的 Application 冲突，
          导致审批提示无法正常工作（stdin 竞争、渲染冲突等）。
        """
        async def _approval_callback(
            tool_name: str, description: str, args_preview: str,
        ) -> str:
            mode = self._permission_mode

            if mode in ("allow", "approve"):
                return "once"

            if mode == "deny":
                return "deny"

            # mode == "ask": check session approvals first
            if tool_name in self._session_approvals:
                return "once"

            # Truncate args_preview for display
            display_args = args_preview
            if len(display_args) > 120:
                display_args = display_args[:117] + "..."

            # Build hermes-style approval prompt (plain text — terminal is in
            # cooked mode inside run_in_terminal, so ANSI is fine but we keep
            # it simple to avoid encoding issues on Windows consoles).
            prompt_lines = (
                f"\n  WARNING  {tool_name}: {display_args}\n"
                f"\n"
                f"  [o]nce  |  [s]ession  |  [a]lways  |  [d]eny\n"
                f"\n"
                f"  Choice [o/s/a/D]: "
            )

            answer = ""
            try:
                # Check if we're inside the prompt_toolkit event loop
                in_pt_loop = (
                    self.app is not None
                    and self.app.loop is not None
                    and self.app.loop.is_running()
                )
                if in_pt_loop:
                    # Use run_in_terminal to temporarily suspend the running
                    # Application. This properly restores the terminal so input()
                    # works.  pt_prompt() CANNOT be used here: it creates its own
                    # Application instance which conflicts with the already-running
                    # one, causing stdin contention and broken rendering.
                    def _read_approval() -> str:
                        try:
                            return input(prompt_lines)
                        except (EOFError, KeyboardInterrupt):
                            return ""

                    answer = await self.app.run_in_terminal(
                        _read_approval, render_cli_done=True,
                    )
                else:
                    answer = input(prompt_lines)
            except (EOFError, KeyboardInterrupt, Exception):
                answer = ""

            answer = answer.strip().lower()

            if answer == "o":
                return "once"
            elif answer == "s":
                self._session_approvals.add(tool_name)
                get_permission_handler().approve_session(tool_name)
                return "once"
            elif answer == "a":
                get_permission_handler().approve_permanent(tool_name)
                self._save_permanent_approval(tool_name)
                return "once"
            else:
                # "d" or any other input -> deny (default)
                return "deny"

        get_permission_handler().set_approval_callback(_approval_callback)

    @staticmethod
    def _save_permanent_approval(tool_name: str) -> None:
        """将永久批准的工具名写入 ~/.Grass/config.json 的 permissions 字段"""
        try:
            from tui.config_integration import load_config, save_config
            config = load_config()
            data = config.model_dump()
            permissions = data.get("permissions") or {}
            approved_tools = set(permissions.get("approved_tools") or [])
            approved_tools.add(tool_name)
            permissions["approved_tools"] = sorted(approved_tools)
            data["permissions"] = permissions
            # Reconstruct config and save
            from core.config import GrassFlowConfig
            updated = GrassFlowConfig(**data)
            save_config(updated, scope="global")
        except Exception as e:
            logger.debug("Failed to save permanent approval for '%s': %s", tool_name, e)

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
        self._api_start_time = 0.0
        if self._compressor:
            self._compressor.reset()

    # ==================== 上下文压缩 ====================

    def _init_compressor(self) -> None:
        """懒初始化上下文压缩器"""
        if self._compressor is not None:
            return
        try:
            from tui.context_compressor import ContextCompressor
            if not self._agent._agent_loop:
                return
            client = self._agent._agent_loop._client
            # 从 session metadata 读取压缩阈值，默认 80000
            threshold = 80000
            if self.session:
                threshold = self.session.metadata.get("compress_threshold", 80000)
            self._compressor = ContextCompressor(
                llm_client=client,
                context_limit=self._token_limit,
                compaction_threshold=threshold,
            )
            logger.debug("Context compressor initialized (threshold=%d)", threshold)
        except Exception as e:
            logger.debug("Failed to initialize context compressor: %s", e)
            self._compressor = None

    async def _check_and_compress(self) -> None:
        """检查对话历史是否需要压缩，如果需要则执行压缩。

        在调用 agent 之前调用此方法。
        压缩后更新 self._conversation_history。
        """
        self._init_compressor()
        if not self._compressor:
            return
        if len(self._conversation_history) < 4:
            return

        from tui.context_compressor import ChatMessage, SUMMARY_PREFIX, SUMMARY_END_MARKER
        messages = [ChatMessage(role=m["role"], content=m.get("content", "")) for m in self._conversation_history]
        if not self._compressor.should_compact(messages):
            return

        original_tokens = self._compressor.estimate_tokens(messages)
        result = await self._compressor.compact(messages)
        if result.tokens_saved <= 0:
            return

        # 重建消息列表
        rebuilt = []
        rebuilt.append(ChatMessage(
            role="system",
            content=f"{SUMMARY_PREFIX}\n\n{result.summary}\n\n{SUMMARY_END_MARKER}",
        ))
        rebuilt.extend(result.tail_messages)
        rebuilt = self._compressor._sanitize_tool_pairs(rebuilt)

        # 更新 _conversation_history
        self._conversation_history.clear()
        for msg in rebuilt:
            entry = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            self._conversation_history.append(entry)

        compacted_tokens = result.compacted_tokens
        cprint(f"\033[36m  Context compressed ({original_tokens} -> {compacted_tokens} tokens, "
               f"saved {result.tokens_saved} tokens)\033[0m")

    # ==================== 输入处理 ====================

    def _process_user_input(self, text: str) -> None:
        """处理用户输入（由 Enter 键绑定调用）

        参考 hermes 模式：直接处理输入，/exit 时设置标志并延迟调用 app.exit()。
        """
        if text.startswith("/"):
            parts = text.split()
            cmd_name = parts[0].lower().lstrip("/")
            cmd_def = command_registry.get(cmd_name)
            is_exit = cmd_def and cmd_def.name == "exit"

            self._handle_slash_command(text)

            if is_exit:
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
        # Consume _retry_last flag — replay the last user message
        if self._retry_last:
            self._retry_last = False
            last_user_text = None
            for entry in reversed(self.output):
                if entry.role == "user":
                    last_user_text = entry.text
                    break
            if last_user_text:
                text = last_user_text
                # Remove last assistant + user pair from conversation history to avoid duplication
                if len(self._conversation_history) >= 2:
                    if self._conversation_history[-1].get("role") == "assistant":
                        self._conversation_history.pop()
                    if self._conversation_history[-1].get("role") == "user":
                        self._conversation_history.pop()
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
            return True
        # Fallback: check if the command matches a skill name (handles late-discovered skills)
        try:
            from tui.skills_system import get_skills_manager
            from tui.slash_commands import _cmd_skill_load
            skills_mgr = get_skills_manager()
            skill = skills_mgr.get_skill(cmd)
            if skill is not None:
                _cmd_skill_load(self, [cmd])
                return True
        except Exception:
            pass
        self.add_output(f"Unknown command: /{cmd}. Type /help for available commands.", role="error")
        return False

    def _handle_agent_message(self, text: str) -> None:
        self._api_start_time = time.monotonic()
        self.add_output(text, role="user")
        # Append user message to conversation history (source of truth for LLM context)
        self._conversation_history.append({"role": "user", "content": text})
        # Persist user message to session DB
        if self.session and self.session_mgr:
            try:
                self.session_mgr.add_user_message(self.session.id, text)
            except Exception:
                pass

        # Check and compress context before agent processing
        if self.app and self.app.loop and self.app.loop.is_running():
            self.app.loop.create_task(self._pre_process_compression(text))
            return  # _pre_process_compression will call _dispatch_agent after compression

        self._dispatch_agent(text)

    async def _pre_process_compression(self, text: str) -> None:
        """Compress context if needed, then dispatch to agent."""
        try:
            await self._check_and_compress()
        except Exception as e:
            logger.debug("Context compression failed: %s", e)
        self._dispatch_agent(text)

    def _dispatch_agent(self, text: str) -> None:
        """Dispatch to agent processing (after compression check)."""
        if not self._agent.is_initialized:
            self.add_output(
                "No agent loop available. Set up an LLM provider to enable AI responses.\n"
                "Use /help for available commands.", role="system",
            )
            return

        # Extract thinking config from session metadata
        reasoning_effort = None
        if self.session:
            thinking = self.session.metadata.get("thinking", {})
            if thinking.get("enabled", False):
                reasoning_effort = thinking.get("effort", "medium")
                # Show thinking mode indicator when thinking is ON
                effort_label = reasoning_effort or "medium"
                cprint(f"\033[2;3m  \U0001f4ad Thinking: ON ({effort_label})\033[0m")

        if self.app and self.app.loop and self.app.loop.is_running():
            self.app.loop.create_task(self._run_agent_loop_async(text, reasoning_effort=reasoning_effort))
        else:
            self._agent.process_in_background(
                text=text, history=self._build_history(), system_prompt=self._get_system_prompt(),
                reasoning_effort=reasoning_effort,
            )

    # ==================== Agent Loop 事件处理 ====================

    def _apply_event_type(self, etype: str, data: dict) -> bool:
        """Apply a single event to output. Returns True if loop should break.

        Shared logic for both streaming (_apply_event) and queued (_process_ui_updates) paths.
        Uses hermes-style cprint for all output.
        """
        if etype == "text_delta":
            token = data.get("text", "")
            # 流式模式：通过 _emit_stream_text 行缓冲发射
            if self._enable_streaming:
                self._emit_stream_text(token)
            else:
                # 非流式：累积到 output 列表
                if self.output and self.output[-1].role == "assistant":
                    self.output[-1].text += token
                else:
                    self.add_output(token, role="assistant")
        elif etype == "text_end":
            self._close_thinking_block()
            self._flush_stream()
            # In streaming mode, the assistant text was only printed to terminal.
            # Store it in conversation history so _build_history() can see it next turn.
            if self._enable_streaming:
                # BUGFIX: accumulate current segment into full response
                full_response = self._stream_full_response + self._stream_collected_text
                if full_response.strip():
                    self._conversation_history.append({"role": "assistant", "content": full_response})
                    # BUGFIX: store-only path — append to self.output without re-printing via cprint
                    entry = OutputEntry(text=full_response, role="assistant")
                    with self._output_lock:
                        self.output.append(entry)
                        if len(self.output) > MAX_OUTPUT_LINES:
                            self.output = self.output[len(self.output) - MAX_OUTPUT_LINES:]
                    if self.app:
                        self.app.invalidate()
            elif not self._enable_streaming:
                # Non-streaming: text was already added to self.output via add_output in text_delta.
                # Extract it from the last output entry for conversation history.
                if self.output and self.output[-1].role == "assistant":
                    self._conversation_history.append({"role": "assistant", "content": self.output[-1].text})
            self._reset_stream_state()
            # Persist assistant response to session DB
            if self.session and self.session_mgr and self.output:
                last = self.output[-1]
                if last.role == "assistant" and last.text.strip():
                    try:
                        self.session_mgr.add_assistant_message(self.session.id, last.text)
                    except Exception:
                        pass
        elif etype == "thinking_delta":
            token = data.get("text", "")
            if token:
                if self._thinking_token_count == 0:
                    self._thinking_start_time = time.monotonic()
                    self._last_thinking_content = ""  # reset for new block
                self._thinking_token_count += 1
                # Accumulate full content for Ctrl+T toggle
                self._last_thinking_content += token

                # Check display mode
                thinking_cfg = self.session.metadata.get("thinking", {}) if self.session else {}
                display_mode = thinking_cfg.get("display", "collapsed")

                if display_mode == "full":
                    # Full mode: stream live with line buffering
                    self._thinking_buf += token
                    if not self._thinking_box_opened:
                        self._thinking_box_opened = True
                        cprint("")
                        cprint("\033[2;3m  ┌ Thinking...\033[0m")
                    while "\n" in self._thinking_buf:
                        line, self._thinking_buf = self._thinking_buf.split("\n", 1)
                        cprint(f"\033[2;3m    {line}\033[0m")
                # else: collapsed mode -- only count tokens, don't print content
        elif etype == "tool_call_start":
            self._flush_stream()
            # BUGFIX: accumulate current segment into full response before reset
            if self._stream_collected_text:
                self._stream_full_response += self._stream_collected_text
            self._reset_stream_state()
            name = data.get('name', 'tool')
            if self._tool_verbose:
                cprint(f"\n\033[1;36m  [tool] Calling {name}...\033[0m")
                if data.get("args"):
                    args_str = json.dumps(data['args'], ensure_ascii=False)[:300]
                    cprint(f"\033[2m    args: {args_str}\033[0m")
            else:
                # Compact: show summary line with args preview
                args_preview = ""
                if data.get("args"):
                    args_str = json.dumps(data['args'], ensure_ascii=False)
                    if len(args_str) > 80:
                        args_preview = args_str[:77] + "..."
                    else:
                        args_preview = args_str
                    args_preview = f"({args_preview})"
                else:
                    args_preview = "()"
                cprint(f"\n\033[1;36m  \U0001f527 {name}{args_preview}\033[0m")
        elif etype == "tool_result":
            self._flush_stream()
            # BUGFIX: accumulate current segment into full response before reset
            if self._stream_collected_text:
                self._stream_full_response += self._stream_collected_text
            self._reset_stream_state()
            result = data.get("result", data.get("output", ""))
            is_err = data.get("is_error", False) or data.get("success", True) is False
            if self._tool_verbose:
                color = "\033[1;31m" if is_err else "\033[2m"
                prefix = "[tool result] [ERROR] " if is_err else "[tool result] "
                cprint(f"{color}  {prefix}{str(result)[:500 if is_err else 800]}\033[0m")
            else:
                # Compact: single summary line truncated to ~200 chars
                result_str = str(result).replace("\n", " ").strip()
                max_len = 200
                if len(result_str) > max_len:
                    result_str = result_str[:max_len - 3] + "..."
                if is_err:
                    cprint(f"\033[1;31m  ❌ {data.get('name', 'tool')} → {result_str}\033[0m")
                else:
                    cprint(f"\033[32m  ✅ {data.get('name', 'tool')} → {result_str}\033[0m")
        elif etype == "error":
            self._close_thinking_block()
            self._flush_stream()
            self._reset_stream_state()
            cprint(f"\033[1;31m  [error] {data.get('message', str(data))}\033[0m")
        elif etype == "interrupted":
            self._close_thinking_block()
            self._flush_stream()
            self._reset_stream_state()
            cprint("\033[33m  Interrupted.\033[0m")
            return True
        elif etype == "usage":
            if isinstance(data, dict):
                self._token_count = data.get("total_tokens", self._token_count)
                self._api_call_count += 1
                if "latency_ms" in data:
                    self._last_latency_ms = data["latency_ms"]
                elif self._api_start_time > 0:
                    self._last_latency_ms = int((time.monotonic() - self._api_start_time) * 1000)
        return False

    def _apply_event(self, etype: str, edata: dict, inv: Any = None) -> bool:
        """将 Agent Loop 事件应用到输出。返回 True 表示应中断循环。"""
        if inv is None:
            inv = lambda: self.app.invalidate() if self.app else None
        result = self._apply_event_type(etype, edata)
        inv()
        return result

    async def _run_agent_loop_async(self, text: str, reasoning_effort: Optional[str] = None) -> None:
        """在 pt 事件循环中运行 Agent Loop（流式输出）"""
        try:
            self._stream_full_response = ""  # Reset full response for new turn
            self._reset_stream_state()
            async for event in self._agent.process_streaming(
                text=text, history=self._build_history(), system_prompt=self._get_system_prompt(),
                reasoning_effort=reasoning_effort,
            ):
                if self._apply_event(event.type, event.data):
                    break
        except Exception as e:
            self._close_thinking_block()
            self._flush_stream()
            self._reset_stream_state()
            self.add_output(f"Agent error: {e}\n{traceback.format_exc()}", role="error")
        finally:
            self._close_thinking_block()
            self._flush_stream()
            self._reset_stream_state()
            self._api_start_time = 0.0
            if self.app:
                self.app.invalidate()

    def _process_ui_updates(self) -> None:
        """消费 Agent Loop 后台线程的 UI 更新"""
        has_updates = False
        for action, kwargs in self._agent.drain_ui_updates():
            has_updates = True
            self._apply_event_type(action, kwargs)
        if has_updates and self.app:
            self.app.invalidate()
        if not self._agent.is_running:
            self._api_start_time = 0.0

    # ==================== 辅助方法 ====================

    def _build_history(self) -> List[Dict[str, Any]]:
        """Return conversation history for LLM context.

        Uses self._conversation_history as the single source of truth,
        which is populated in _handle_agent_message (user) and _apply_event_type text_end (assistant).
        self.output is display-only and must NOT be used for history building.
        """
        return list(self._conversation_history)

    def _get_system_prompt(self) -> str:
        cwd = os.getcwd()
        base = (
            f"You are GrassFlow AI assistant, running inside the GrassFlow REPL.\n\n"
            f"Current directory: {cwd}\n"
            f"You can help users with:\n"
            f"- Creating and managing workflows\n- Writing code and analyzing files\n"
            f"- Running commands and debugging\n\n"
        )
        # Inject skills prompt
        try:
            from tui.skills_system import get_skills_manager
            skills_mgr = get_skills_manager()
            skills_prompt = skills_mgr.build_skills_prompt()
            if skills_prompt:
                base += skills_prompt + "\n\n"
        except Exception:
            pass
        base += "Be concise and helpful. Use tools when needed to complete tasks."
        return base

    def _interrupt_agent(self) -> None:
        self._agent.interrupt()

    def _toggle_permission_mode(self) -> None:
        """切换权限模式 (ask <-> approve) 并显示提示"""
        if self._permission_mode == "ask":
            self._permission_mode = "approve"
            msg = "Permission mode: APPROVE — tools will execute automatically"
        else:
            self._permission_mode = "ask"
            msg = "Permission mode: ASK — tools require approval before execution"
        cprint(f"\033[1;36m  {msg}\033[0m")
        if self.app:
            self.app.invalidate()

    def _handle_think_toggle(self) -> None:
        """Ctrl+T: 切换当前思考块的显示（折叠 <-> 展开）"""
        if not self._last_thinking_content:
            cprint("\033[2;3m  No thinking content to toggle.\033[0m")
            return

        self._thinking_expanded = not self._thinking_expanded
        self._toggle_thinking_display()

    def _toggle_thinking_display(self) -> None:
        """重新打印思考块：根据 _thinking_expanded 状态显示折叠摘要或完整内容"""
        duration = self._last_thinking_duration
        tokens = self._last_thinking_tokens

        if self._thinking_expanded:
            # Show full thinking content
            cprint("")
            cprint("\033[2;3m  ┌ Thinking (expanded by Ctrl+T)\033[0m")
            for line in self._last_thinking_content.split("\n"):
                cprint(f"\033[2;3m    {line}\033[0m")
            duration_str = f" in {duration:.1f}s" if duration > 0 else ""
            cprint(f"\033[2;3m  └ Done thinking{duration_str} ({tokens} tokens)\033[0m")
            cprint("")
        else:
            # Show collapsed summary
            duration_str = f"{duration:.1f}s" if duration > 0 else "..."
            cprint(f"\033[2;3m  \U0001f4ad Thought for {duration_str} ({tokens} tokens)\033[0m")

    def _execute_shell(self, command: str) -> None:
        """在后台线程中执行 shell 命令，避免阻塞 UI 线程"""
        def _run():
            try:
                result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
                parts = []
                if result.stdout:
                    parts.append(result.stdout)
                if result.stderr:
                    parts.append(f"[stderr]\n{result.stderr}")
                if result.returncode != 0:
                    parts.append(f"[exit code: {result.returncode}]")
                output = "\n".join(parts) if parts else "(no output)"
                self.add_output(output[:2000], role="tool")
            except subprocess.TimeoutExpired:
                self.add_output(f"Command timed out: {command}", role="error")
            except Exception as e:
                self.add_output(f"Shell error: {e}", role="error")
        threading.Thread(target=_run, daemon=True).start()

    # ==================== 生命周期 ====================

    def _init_session(self) -> None:
        if self._enable_session and self.session_mgr:
            try:
                self.session = self.session_mgr.create_session(
                    title="REPL Session", directory=os.getcwd(),
                    metadata={
                        "model": DEFAULT_MODEL,
                        "provider": DEFAULT_PROVIDER,
                        "thinking": {"enabled": True, "effort": "medium", "display": "collapsed"},
                        "compress_threshold": 80000,
                    },
                )
                self.add_output(f"Session: {self.session.id[:12]}", role="system")
            except Exception as e:
                self.add_output(f"Session init failed: {e}", role="system")
                self.session = None

    def run(self) -> None:
        self._running, self._should_exit = True, False
        self._init_session()
        # Register /skill-name commands after session init
        register_skill_commands()
        if self._agent.init_agent_loop():
            self._cprint_output("Agent loop initialized.", role="system")
        else:
            self._cprint_output("AgentLoop not available. Falling back to echo mode.", role="system")

        try:
            self.app = Application(
                layout=self._build_layout(),
                key_bindings=self.kb,
                style=build_pt_style(self._theme),
                full_screen=False,
                mouse_support=False,       # 关键：禁用鼠标支持，让终端处理滚轮
                refresh_interval=0.0,
                erase_when_done=True,
            )
        except Exception as e:
            cprint(BANNER)
            self._run_fallback(f"prompt_toolkit 不可用 ({e})，使用降级模式。输入 /exit 退出。")
            return

        # 注册 invalidate 钩子（消费后台线程 UI 更新）
        def _on_invalidate(_sender=None):
            self._process_ui_updates()
        self.app.on_invalidate += _on_invalidate

        # 设置模块级事件循环引用（供 cprint 跨线程安全使用）
        if self.app.loop:
            set_event_loop(self.app.loop)

        # hermes 模式：patch_stdout 包裹 app.run()
        from prompt_toolkit.patch_stdout import patch_stdout
        try:
            with patch_stdout():
                # 打印 banner
                cprint(BANNER)
                cprint("  GrassFlow REPL\n  Type /help for commands, /exit to quit.")
                self.app.run()
        except (EOFError, KeyboardInterrupt, BrokenPipeError):
            pass
        except Exception as e:
            self._cprint_output(f"REPL error: {e}", role="error")
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
        # Shutdown MCP servers
        if hasattr(self._agent, '_mcp_manager') and self._agent._mcp_manager:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._agent._mcp_manager.stop_all())
                loop.close()
            except Exception:
                pass
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
        # Register /skill-name commands after session init
        register_skill_commands()
        cprint(BANNER)
        cprint("  GrassFlow REPL (async)\n  Type /help for commands, /exit to quit.")
        if self._agent.init_agent_loop():
            self._cprint_output("Agent loop initialized.", role="system")
        self.app = Application(
            layout=self._build_layout(),
            key_bindings=self.kb,
            style=build_pt_style(self._theme),
            full_screen=False,
            mouse_support=False,       # 关键：禁用鼠标支持，让终端处理滚轮
            refresh_interval=0.0,
            erase_when_done=True,
        )

        def _on_invalidate(_sender=None):
            self._process_ui_updates()

        self.app.on_invalidate += _on_invalidate

        # 设置模块级事件循环引用（供 cprint 跨线程安全使用）
        if self.app.loop:
            set_event_loop(self.app.loop)

        from prompt_toolkit.patch_stdout import patch_stdout
        try:
            with patch_stdout():
                await self.app.run_async()
        except (EOFError, KeyboardInterrupt, BrokenPipeError):
            pass
        except Exception as e:
            self._cprint_output(f"REPL error: {e}", role="error")
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

from tui.compat import (  # noqa: E402, F401
    MessageRole, Message, CommandResult, CommandHandler,
    InputHandler, MessageRenderer, REPL, create_repl,
)

if __name__ == "__main__":
    run_repl()

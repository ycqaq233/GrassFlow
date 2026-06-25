"""
GrassFlow REPL — 基于 prompt_toolkit 的交互式 TUI

布局（双缓冲渲染）：
┌─────────────────────────────────┐
│  Header: 模型名 | 会话ID | 模式  │  ← 顶部状态栏
├─────────────────────────────────┤
│                                 │
│  Output Area (scrollable)       │
│  Rich 渲染的 Markdown 消息       │
│  工具调用结果 / 错误消息         │
│                                 │
├─────────────────────────────────┤
│  Status: 13/5000 tokens | 5ms   │  ← 底部状态栏
├─────────────────────────────────┤
│  ❯ ▌ 用户输入                    │  ← 固定底部输入栏
└─────────────────────────────────┘

参考实现：Hermes cli.py — prompt_toolkit Application + KeyBindings
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shutil
import signal
import sys
import threading
import traceback
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set, Tuple

# ==================== prompt_toolkit ====================

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    Dimension,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    ScrollOffsets,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.styles import Style, merge_styles
from prompt_toolkit.widgets import Frame, TextArea

# ==================== Rich ====================

from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.style import Style as RichStyle
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text as RichText

# ==================== 内部模块 ====================

from core.config import config_manager
from tui.session import (
    SessionManager,
    SessionMessage,
    SessionInfo,
    SessionStatus,
    MessageRole as SessionMessageRole,
    session_manager,
)


# ==================== 常量 ====================

PROMPT = "❯ "
PROMPT_STYLE = "class:prompt"
BANNER = r"""
  ____                 _     _____ _
 / ___|_ __ __ _  ___ | |__ |  ___| | _____      __
| |  _| '__/ _` |/ __|| '_ \| |_  | |/ _ \ \ /\ / /
| |_| | | | (_| |\__ \| | | |  _| | | (_) \ V  V /
 \____|_|  \__,_||___/|_| |_|_|   |_|\___/ \_/\_/
"""

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_PROVIDER = "deepseek"
MAX_OUTPUT_LINES = 5000


# ==================== 数据模型 ====================


class OutputEntry:
    """输出区域的一条记录"""

    def __init__(
        self,
        text: str = "",
        role: str = "system",  # user / assistant / system / error / tool
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.text = text
        self.role = role
        self.timestamp = timestamp or datetime.now()
        self.metadata = metadata or {}


class REPLMode(str, Enum):
    """REPL 模式"""
    NORMAL = "normal"
    APPROVAL = "approval"
    BUSY = "busy"


class REPLTheme:
    """REPL 主题配置"""

    def __init__(
        self,
        name: str = "default",
        header_fg: str = "#ffffff",
        header_bg: str = "#1a1a2e",
        output_bg: str = "#0d0d0d",
        status_fg: str = "#888888",
        status_bg: str = "#1a1a2e",
        input_bg: str = "#16213e",
        prompt_color: str = "#00ff88",
        user_color: str = "#4fc3f7",
        assistant_color: str = "#81c784",
        system_color: str = "#888888",
        error_color: str = "#ef5350",
        tool_color: str = "#ce93d8",
        accent: str = "#ffd54f",
    ):
        self.name = name
        self.header_fg = header_fg
        self.header_bg = header_bg
        self.output_bg = output_bg
        self.status_fg = status_fg
        self.status_bg = status_bg
        self.input_bg = input_bg
        self.prompt_color = prompt_color
        self.user_color = user_color
        self.assistant_color = assistant_color
        self.system_color = system_color
        self.error_color = error_color
        self.tool_color = tool_color
        self.accent = accent


# 内置主题
BUILTIN_THEMES: Dict[str, REPLTheme] = {
    "default": REPLTheme(),
    "dark": REPLTheme(
        name="dark",
        header_bg="#0d1117",
        output_bg="#0d1117",
        status_bg="#0d1117",
        input_bg="#161b22",
        prompt_color="#58a6ff",
        accent="#f78166",
    ),
    "light": REPLTheme(
        name="light",
        header_fg="#1a1a1a",
        header_bg="#f6f8fa",
        output_bg="#ffffff",
        status_fg="#666666",
        status_bg="#f6f8fa",
        input_bg="#f0f0f0",
        prompt_color="#0550ae",
        user_color="#0969da",
        assistant_color="#1a7f37",
    ),
    "cyber": REPLTheme(
        name="cyber",
        header_bg="#000000",
        output_bg="#000000",
        status_bg="#000000",
        input_bg="#0a0a0a",
        prompt_color="#00ff41",
        user_color="#00ff41",
        assistant_color="#39ff14",
        accent="#ff00ff",
    ),
    "ocean": REPLTheme(
        name="ocean",
        header_bg="#0c2d48",
        output_bg="#0a1929",
        status_bg="#0c2d48",
        input_bg="#132f4c",
        prompt_color="#64b5f6",
        user_color="#4fc3f7",
        assistant_color="#80cbc4",
        accent="#ffd54f",
    ),
}


# ==================== 补全器 ====================


class SlashCommandCompleter(Completer):
    """斜杠命令 + 文件路径补全器"""

    # 所有可用的斜杠命令
    COMMANDS: Dict[str, str] = {
        "help": "显示帮助信息",
        "h": "显示帮助信息（别名）",
        "model": "切换模型  /model <name>",
        "models": "列出可用模型",
        "new": "创建新会话",
        "clear": "清空会话",
        "cls": "清屏",
        "compact": "手动压缩上下文",
        "sessions": "列出历史会话",
        "init": "分析项目创建 AGENTS.md",
        "undo": "撤销上次操作",
        "redo": "重做",
        "exit": "退出 REPL",
        "quit": "退出 REPL（别名）",
        "q": "退出 REPL（别名）",
        "theme": "切换主题  /theme <name>",
        "provider": "切换 provider  /provider <name>",
        "run": "执行工作流文件  /run <file>",
        "list": "列出已保存的工作流",
        "ls": "列出已保存的工作流（别名）",
        "history": "查看执行历史",
        "validate": "验证工作流文件",
        "templates": "列出可用模板",
        "config": "查看/修改配置",
        "stats": "显示上下文统计",
        "status": "显示当前会话状态",
    }

    def __init__(self):
        self._path_completer = PathCompleter(
            expanduser=True,
            file_filter=lambda f: not f.startswith("."),
        )

    def get_completions(self, document: Document, complete_event) -> List[Completion]:
        text = document.text_before_cursor

        # 斜杠命令补全
        if text.startswith("/"):
            cmd_part = text[1:]
            # 空格后走文件路径补全
            if " " in cmd_part:
                # 命令后跟文件路径
                space_idx = cmd_part.index(" ")
                file_part = cmd_part[space_idx + 1:]
                file_doc = Document(file_part, len(file_part))
                for comp in self._path_completer.get_completions(file_doc, complete_event):
                    yield Completion(
                        text=comp.text,
                        start_position=comp.start_position,
                        display=comp.display,
                    )
                return

            # 补全命令名
            for cmd_name, desc in sorted(self.COMMANDS.items()):
                if cmd_name.startswith(cmd_part):
                    yield Completion(
                        text=cmd_name,
                        start_position=-len(cmd_part),
                        display=f"/{cmd_name}  —  {desc}",
                        display_meta=desc,
                    )
            return

        # 文件路径补全（@file 语法）
        if text.startswith("@"):
            file_part = text[1:]
            file_doc = Document(file_part, len(file_part))
            for comp in self._path_completer.get_completions(file_doc, complete_event):
                yield Completion(
                    text=comp.text,
                    start_position=comp.start_position,
                    display=comp.display,
                )
            return

        return []


# ==================== prompt_toolkit Style 构建 ====================


def build_pt_style(theme: REPLTheme) -> Style:
    """将 REPLTheme 转换为 prompt_toolkit Style"""
    return Style.from_dict({
        # 主窗口
        "output-area": f"bg:{theme.output_bg}",
        "header": f"fg:{theme.header_fg} bg:{theme.header_bg} bold",
        "header-dim": f"fg:{theme.system_color} bg:{theme.header_bg}",
        "status-bar": f"fg:{theme.status_fg} bg:{theme.status_bg}",
        "status-bar-bright": f"fg:{theme.accent} bg:{theme.status_bg} bold",
        "input-area": f"fg:#e0e0e0 bg:{theme.input_bg}",
        "prompt": f"fg:{theme.prompt_color} bg:{theme.input_bg} bold",
        # 消息角色
        "msg-user": f"fg:{theme.user_color} bold",
        "msg-assistant": f"fg:{theme.assistant_color}",
        "msg-system": f"fg:{theme.system_color} italic",
        "msg-error": f"fg:{theme.error_color} bold",
        "msg-tool": f"fg:{theme.tool_color}",
        # 其他
        "scrollbar": f"fg:{theme.input_bg} bg:{theme.output_bg}",
        "scrollbar-arrow": f"fg:{theme.accent} bg:{theme.output_bg}",
        "frame-border": f"fg:{theme.header_bg}",
    })


# ==================== 主类 ====================


class GrassFlowREPL:
    """GrassFlow 交互式 REPL

    基于 prompt_toolkit 实现，提供类似 Claude Code 的 TUI 体验。

    使用方式::

        repl = GrassFlowREPL()
        repl.run()
    """

    def __init__(
        self,
        theme: Optional[REPLTheme] = None,
        enable_session: bool = True,
        enable_streaming: bool = True,
    ):
        # ---- 主题 ----
        self._theme = theme or self._load_theme()

        # ---- 核心组件 ----
        self.session: Optional[SessionInfo] = None
        self.session_mgr = session_manager if enable_session else None
        self._enable_session = enable_session

        # ---- Agent Loop（延迟初始化） ----
        self._agent_loop = None  # 类型: Optional[AgentLoop]
        self._enable_streaming = enable_streaming

        # ---- 状态 ----
        self.output: List[OutputEntry] = []
        self.mode = REPLMode.NORMAL
        self._running = False
        self._should_exit = False
        self._agent_running = False

        # ---- 队列 ----
        self._input_queue: queue.Queue = queue.Queue()
        self._interrupt_queue: queue.Queue = queue.Queue()
        # 线程安全 UI 更新队列：Agent Loop 线程 → UI 主线程
        self._ui_update_queue: queue.Queue = queue.Queue()

        # ---- 补全器 ----
        self._completer = SlashCommandCompleter()

        # ---- prompt_toolkit 组件 ----
        self.app: Optional[Application] = None
        self.input_buffer = Buffer(
            multiline=True,
            completer=self._completer,
            complete_while_typing=True,
            accept_handler=self._accept_input,
        )
        self.kb = KeyBindings()

        # ---- 撤销/重做 ----
        self._undo_stack: List[OutputEntry] = []
        self._redo_stack: List[OutputEntry] = []

        # ---- 统计 ----
        self._token_count = 0
        self._token_limit = 128000
        self._last_latency_ms = 0
        self._api_call_count = 0

        # ---- 注册快捷键 ----
        self._setup_keybindings()

        # ---- Rich console（用于 Markdown 渲染） ----
        self._rich_console = RichConsole(color_system="truecolor")

    # ==================== 主题 ====================

    def _load_theme(self) -> REPLTheme:
        """从配置加载主题"""
        try:
            theme_name = config_manager.get("display.theme", "default")
            return BUILTIN_THEMES.get(theme_name, BUILTIN_THEMES["default"])
        except Exception:
            return BUILTIN_THEMES["default"]

    def switch_theme(self, name: str) -> bool:
        """切换主题"""
        if name in BUILTIN_THEMES:
            self._theme = BUILTIN_THEMES[name]
            if self.app:
                self.app.style = build_pt_style(self._theme)
            return True
        return False

    @property
    def theme_names(self) -> List[str]:
        """列出可用主题名称"""
        return list(BUILTIN_THEMES.keys())

    # ==================== 输出管理 ====================

    def add_output(
        self,
        text: str,
        role: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加输出条目"""
        entry = OutputEntry(text=text, role=role, metadata=metadata)
        self.output.append(entry)

        # 限制输出行数
        if len(self.output) > MAX_OUTPUT_LINES:
            cutoff = len(self.output) - MAX_OUTPUT_LINES
            self.output = self.output[cutoff:]

    def clear_output(self) -> None:
        """清空输出"""
        self.output.clear()

    def _get_role_style(self, role: str) -> str:
        """获取角色的 prompt_toolkit style tag"""
        mapping = {
            "user": "msg-user",
            "assistant": "msg-assistant",
            "system": "msg-system",
            "error": "msg-error",
            "tool": "msg-tool",
        }
        return mapping.get(role, "msg-system")

    # ==================== 渲染回调 ====================

    def _get_header_text(self) -> List[Tuple[str, str]]:
        """获取顶部状态栏文本"""
        result: List[Tuple[str, str]] = []
        result.append(("class:header", " GrassFlow "))

        # 模型名
        if self.session and self.session.metadata.get("model"):
            model = self.session.metadata["model"]
            result.append(("class:header-dim", f" |  model: {model}"))
        else:
            result.append(("class:header-dim", f" |  model: {DEFAULT_MODEL}"))

        # 会话 ID
        if self.session:
            short_id = self.session.id[:12]
            result.append(("class:header-dim", f" |  session: {short_id}"))

        # 模式
        mode_text = {
            REPLMode.NORMAL: "NORMAL",
            REPLMode.BUSY: "BUSY",
            REPLMode.APPROVAL: "APPROVAL",
        }.get(self.mode, "NORMAL")
        result.append(("class:header-dim", f" |  {mode_text}"))

        # 消息计数
        msg_count = len(self.output)
        result.append(("class:header-dim", f" |  {msg_count} msgs"))

        return result

    def _get_output_text(self) -> List[Tuple[str, str]]:
        """获取输出区域文本（最近 N 条消息）"""
        result: List[Tuple[str, str]] = []

        if not self.output:
            result.append(("class:msg-system", "  Welcome to GrassFlow REPL!\n"))
            result.append(("class:msg-system", "  Type /help for available commands.\n"))
            result.append(("class:msg-system", "  Ctrl+X N for new session, Ctrl+X Q to exit.\n"))
            return result

        # 显示最近的消息（根据窗口高度自适应）
        # 这里取最近的消息，实际显示多少由 prompt_toolkit scroll 控制
        for entry in self.output:
            style = self._get_role_style(entry.role)
            timestamp = entry.timestamp.strftime("%H:%M:%S")
            # 前缀
            prefix = {
                "user": "  ❯ ",
                "assistant": "  ● ",
                "system": "  · ",
                "error": "  ✖ ",
                "tool": "  ⚒ ",
            }.get(entry.role, "  · ")

            # 添加时间戳 + 前缀
            result.append(("class:msg-system", f"[{timestamp}]"))
            result.append((f"class:{style}", f"{prefix}{entry.text}\n"))

        return result

    def _get_status_text(self) -> List[Tuple[str, str]]:
        """获取底部状态栏文本"""
        result: List[Tuple[str, str]] = []

        # Token 使用
        if self._token_count > 0:
            result.append(("class:status-bar", f" Tokens: {self._token_count}/{self._token_limit}"))
            pct = self._token_count / self._token_limit * 100
            if pct > 80:
                result.append(("class:status-bar-bright", f" ({int(pct)}%!) "))
            else:
                result.append(("class:status-bar", f" ({int(pct)}%) "))
        else:
            result.append(("class:status-bar", " Tokens: 0 "))

        # 延迟
        if self._last_latency_ms > 0:
            result.append(("class:status-bar", f"|  {self._last_latency_ms}ms "))

        # API 调用次数
        if self._api_call_count > 0:
            result.append(("class:status-bar", f"|  {self._api_call_count} API calls "))

        # 忙碌指示器
        if self._agent_running:
            result.append(("class:status-bar-bright", "|  ⏳ running... "))

        return result

    # ==================== 快捷键 ====================

    def _setup_keybindings(self) -> None:
        kb = self.kb

        @kb.add("enter")
        def handle_enter(event: KeyPressEvent) -> None:
            """回车：提交输入"""
            if self.mode == REPLMode.APPROVAL:
                # 审批模式下，回车 = 确认
                return
            if self._agent_running:
                # Agent 运行中，不处理
                return
            # 正常提交到 input_buffer 的 accept_handler
            buffer = event.app.current_buffer
            buffer.validate_and_handle()

        @kb.add("escape", "enter")
        def handle_alt_enter(event: KeyPressEvent) -> None:
            """Alt+Enter：多行输入换行"""
            buffer = event.app.current_buffer
            buffer.insert_text("\n")

        @kb.add("c-c", eager=True)
        def handle_ctrl_c(event: KeyPressEvent) -> None:
            """Ctrl+C：中断 Agent 或退出"""
            if self._agent_running:
                self._interrupt_agent()
                self.add_output("Interrupted by user", role="system")
                event.app.invalidate()
            else:
                # 不运行中时 Ctrl+C = 退出
                self._should_exit = True
                event.app.exit()

        @kb.add("c-d", eager=True)
        def handle_ctrl_d(event: KeyPressEvent) -> None:
            """Ctrl+D：EOF，退出"""
            buffer = event.app.current_buffer
            if buffer.text == "":
                self._should_exit = True
                event.app.exit()

        @kb.add("c-l")
        def handle_ctrl_l(event: KeyPressEvent) -> None:
            """Ctrl+L：清屏"""
            self.clear_output()
            event.app.invalidate()

        @kb.add("c-x", "c")
        def handle_compact(event: KeyPressEvent) -> None:
            """Ctrl+X C：压缩上下文"""
            self._handle_compact()
            event.app.invalidate()

        @kb.add("c-x", "n")
        def handle_new_session(event: KeyPressEvent) -> None:
            """Ctrl+X N：新会话"""
            self._handle_new_session()
            event.app.invalidate()

        @kb.add("c-x", "l")
        def handle_sessions(event: KeyPressEvent) -> None:
            """Ctrl+X L：列出会话"""
            self._handle_list_sessions()
            event.app.invalidate()

        @kb.add("c-x", "q")
        def handle_exit(event: KeyPressEvent) -> None:
            """Ctrl+X Q：退出"""
            self._should_exit = True
            event.app.exit()

        @kb.add("c-x", "u")
        def handle_undo(event: KeyPressEvent) -> None:
            """Ctrl+X U：撤销"""
            self._handle_undo()
            event.app.invalidate()

        @kb.add("c-x", "r")
        def handle_redo(event: KeyPressEvent) -> None:
            """Ctrl+X R：重做"""
            self._handle_redo()
            event.app.invalidate()

        @kb.add("c-x", "m")
        def handle_models(event: KeyPressEvent) -> None:
            """Ctrl+X M：列出模型"""
            self._handle_list_models()
            event.app.invalidate()

        @kb.add("tab")
        def handle_tab(event: KeyPressEvent) -> None:
            """Tab：命令/文件补全"""
            buffer = event.app.current_buffer
            if buffer.completer:
                # 让 prompt_toolkit 处理补全
                pass

        @kb.add("c-up")
        def handle_scroll_up(event: KeyPressEvent) -> None:
            """Ctrl+Up：向上滚动输出"""
            # prompt_toolkit layout 会自动处理 scroll
            pass

        @kb.add("c-down")
        def handle_scroll_down(event: KeyPressEvent) -> None:
            """Ctrl+Down：向下滚动输出"""
            pass

    # ==================== 输入处理 ====================

    def _accept_input(self, buffer: Buffer) -> bool:
        """接受输入回调 — 直接同步处理，不经过队列"""
        text = buffer.text.strip()
        if not text:
            buffer.reset()
            return True  # 空输入，清空 buffer

        buffer.reset()

        # 直接处理输入（命令同步处理，普通消息通过 Agent Loop 异步处理）
        self._process_entry(text)
        return True  # 返回 True 表示已处理

    # ==================== 布局构建 ====================

    def _build_layout(self) -> Layout:
        """构建 prompt_toolkit 布局"""
        # 输出区域（可滚动）
        output_window = Window(
            content=FormattedTextControl(
                text=self._get_output_text,
                focusable=False,
            ),
            wrap_lines=True,
            always_hide_cursor=True,
            scroll_offsets=ScrollOffsets(top=2, bottom=2),
            right_margins=[ScrollbarMargin()],
        )

        # 构建整体布局
        root_container = HSplit([
            # 顶部状态栏
            Window(
                content=FormattedTextControl(text=self._get_header_text),
                height=1,
                style="class:header",
            ),
            # 分隔线
            Window(
                height=1,
                char="─",
                style="class:header-dim",
            ),
            # 输出区域（占据主要空间）
            output_window,
            # 分隔线
            Window(
                height=1,
                char="─",
                style="class:header-dim",
            ),
            # 底部状态栏
            Window(
                content=FormattedTextControl(text=self._get_status_text),
                height=1,
                style="class:status-bar",
            ),
            # 输入区域
            Window(
                content=BufferControl(
                    buffer=self.input_buffer,
                    input_processors=[],
                ),
                height=3,
                style="class:input-area",
                wrap_lines=True,
                get_line_prefix=self._get_input_prefix,
            ),
        ])

        return Layout(root_container)

    def _get_input_prefix(self, line_number: int, wrap_count: int) -> List[Tuple[str, str]]:
        """获取输入区域每行的前缀"""
        if line_number == 0:
            return [("class:prompt", f"{PROMPT}")]
        else:
            return [("class:prompt", "  ")]

    # ==================== 命令处理 ====================

    def _dispatch_command(self, text: str) -> bool:
        """分发斜杠命令，返回 True 表示需要退出"""
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        # 移除前导 /
        if cmd.startswith("/"):
            cmd = cmd[1:]

        handlers: Dict[str, Callable[[List[str]], Optional[bool]]] = {
            "help": self._cmd_help,
            "h": self._cmd_help,
            "model": self._cmd_model,
            "models": self._cmd_list_models,
            "new": self._cmd_new_session,
            "clear": self._cmd_clear,
            "cls": self._cmd_clear,
            "compact": self._cmd_compact,
            "sessions": self._cmd_list_sessions,
            "init": self._cmd_init,
            "undo": self._cmd_undo,
            "redo": self._cmd_redo,
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
            "q": self._cmd_exit,
            "theme": self._cmd_theme,
            "provider": self._cmd_provider,
            "run": self._cmd_run,
            "list": self._cmd_list_workflows,
            "ls": self._cmd_list_workflows,
            "history": self._cmd_history,
            "validate": self._cmd_validate,
            "templates": self._cmd_templates,
            "config": self._cmd_config,
            "stats": self._cmd_stats,
            "status": self._cmd_status,
        }

        handler = handlers.get(cmd)
        if handler:
            result = handler(args)
            return result is True
        else:
            self.add_output(f"Unknown command: /{cmd}. Type /help for available commands.", role="error")
            return False

    def _dispatch_message(self, text: str) -> None:
        """处理普通消息"""
        self.add_output(text, role="user")

        # 如果有 Agent Loop，异步处理
        if self._agent_loop:
            self._process_with_agent_loop(text)
        else:
            self.add_output(
                "No agent loop available. Set up an LLM provider to enable AI responses.\n"
                "Use /help for available commands.",
                role="system",
            )

    def _process_with_agent_loop(self, text: str) -> None:
        """使用 AgentLoop 异步处理消息"""
        self._agent_running = True

        # 在后台线程中运行异步 Agent Loop
        def _run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._async_agent_loop(text))
                loop.close()
            except Exception as e:
                self._ui_update_queue.put(("error", {"message": f"Agent error: {e}"}))
            finally:
                self._agent_running = False
                # 通知主线程刷新
                self._ui_update_queue.put(("agent_done", {}))

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    async def _async_agent_loop(self, text: str) -> None:
        """异步 Agent Loop 处理（在后台线程中运行）

        UI 更新通过线程安全队列 _ui_update_queue 传递到主线程，
        避免从非 UI 线程直接调用 prompt_toolkit 的 invalidate()。
        """
        def _push_ui(action: str, **kwargs):
            """将 UI 更新推入线程安全队列"""
            self._ui_update_queue.put((action, kwargs))

        try:
            from tui.agent_loop import AgentLoop, LoopEvent

            agent_loop = self._agent_loop

            # 构建历史消息
            history = self._build_history()

            # 系统提示
            system_prompt = self._get_system_prompt()

            # 处理消息（流式）
            async for event in agent_loop.process_streaming(text, history, system_prompt):
                etype = event.type
                edata = event.data

                if etype == "loop_start":
                    pass  # 循环开始
                elif etype == "loop_end":
                    pass  # 循环结束
                elif etype == "text_delta":
                    # 流式 token 增量 — 追加到最近一条输出
                    token = edata.get("text", "")
                    _push_ui("text_delta", text=token)
                elif etype == "text_end":
                    # 文本结束 — 触发 UI 刷新
                    _push_ui("invalidate")
                elif etype == "thinking_delta":
                    # 思考过程增量（reasoning 模型）
                    token = edata.get("text", "")
                    _push_ui("thinking_delta", text=token)
                elif etype == "tool_call_start":
                    tool_name = edata.get("name", "?")
                    tool_args = edata.get("args", {})
                    _push_ui("tool_call_start", name=tool_name, args=tool_args)
                elif etype == "tool_call_end":
                    pass  # 工具调用参数结束
                elif etype == "tool_result":
                    result = edata.get("result", edata.get("output", ""))
                    _push_ui("tool_result", output=str(result)[:800])
                elif etype == "error":
                    msg = edata.get("message", str(edata))
                    _push_ui("error", message=msg)
                elif etype == "interrupted":
                    _push_ui("interrupted")
                    break
                elif etype == "usage":
                    # 使用统计
                    if isinstance(edata, dict):
                        self._token_count = edata.get("total_tokens", self._token_count)
                        self._api_call_count += 1
                    _push_ui("invalidate")

        except ImportError:
            _push_ui("error", message="AgentLoop module not found. Install required dependencies.")
        except Exception as e:
            _push_ui("error", message=f"Agent error: {e}\n{traceback.format_exc()}")

    def _build_history(self) -> List[Dict[str, Any]]:
        """从输出历史构建对话消息"""
        messages = []
        for entry in self.output:
            if entry.role == "user":
                messages.append({"role": "user", "content": entry.text})
            elif entry.role == "assistant":
                messages.append({"role": "assistant", "content": entry.text})
        return messages

    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        cwd = os.getcwd()
        return f"""You are GrassFlow AI assistant, running inside the GrassFlow REPL.

Current directory: {cwd}
You can help users with:
- Creating and managing workflows
- Writing code and analyzing files
- Running commands and debugging

Be concise and helpful. Use tools when needed to complete tasks."""

    def _interrupt_agent(self) -> None:
        """中断 Agent 执行"""
        if self._agent_loop:
            try:
                self._agent_loop.interrupt()
            except Exception:
                pass
        self._agent_running = False

    # ==================== 斜杠命令实现 ====================

    def _cmd_help(self, args: List[str]) -> None:
        """显示帮助"""
        lines = [
            "",
            "  Available commands:",
        ]
        for cmd_name, desc in sorted(SlashCommandCompleter.COMMANDS.items()):
            if len(cmd_name) == 1:
                continue  # 跳过单字母别名
            lines.append(f"    /{cmd_name:<14} —  {desc}")

        lines.extend([
            "",
            "  Keyboard shortcuts:",
            "    Enter           Submit input",
            "    Alt+Enter       New line (multi-line input)",
            "    Ctrl+C          Interrupt / Exit",
            "    Ctrl+D          EOF / Exit (empty input)",
            "    Ctrl+L          Clear screen",
            "    Tab             Complete command / file path",
            "    Ctrl+X C        Compact context",
            "    Ctrl+X N        New session",
            "    Ctrl+X L        List sessions",
            "    Ctrl+X U        Undo",
            "    Ctrl+X R        Redo",
            "    Ctrl+X Q        Exit",
            "    Ctrl+X M        List models",
            "",
        ])

        self.add_output("\n".join(lines), role="system")

    def _cmd_model(self, args: List[str]) -> None:
        """切换模型"""
        if not args:
            current = self.session.metadata.get("model", DEFAULT_MODEL) if self.session else DEFAULT_MODEL
            self.add_output(f"Current model: {current}\nUsage: /model <model_name>", role="system")
            return

        model_name = args[0]
        if self.session:
            self.session.metadata["model"] = model_name
        self.add_output(f"Model switched to: {model_name}", role="system")

    def _cmd_list_models(self, args: List[str]) -> None:
        """列出可用模型"""
        try:
            config = config_manager.load_config()
            lines = ["", "  Available models:"]
            for provider_name, provider_config in config.provider.items():
                lines.append(f"\n  [{provider_name}]")
                if provider_config.models:
                    for model_name, model_info in provider_config.models.items():
                        name = model_info.name or model_name
                        lines.append(f"    - {name}")
                else:
                    lines.append("    (no models configured)")
            self.add_output("\n".join(lines), role="system")
        except Exception as e:
            self.add_output(f"Failed to list models: {e}", role="error")

    def _cmd_new_session(self, args: List[str]) -> None:
        """创建新会话"""
        self._handle_new_session()

    def _cmd_clear(self, args: List[str]) -> None:
        """清空会话"""
        self.clear_output()
        self.add_output("Screen cleared.", role="system")

    def _cmd_compact(self, args: List[str]) -> None:
        """手动压缩上下文"""
        self._handle_compact()

    def _cmd_list_sessions(self, args: List[str]) -> None:
        """列出历史会话"""
        self._handle_list_sessions()

    def _cmd_init(self, args: List[str]) -> None:
        """分析项目创建 AGENTS.md"""
        self.add_output(
            "Run /init to analyze the current project and create an AGENTS.md file.\n"
            "This feature requires the init skill or an initialized agent.",
            role="system",
        )

    def _cmd_undo(self, args: List[str]) -> None:
        """撤销"""
        self._handle_undo()

    def _cmd_redo(self, args: List[str]) -> None:
        """重做"""
        self._handle_redo()

    def _cmd_exit(self, args: List[str]) -> None:
        """退出"""
        self._should_exit = True
        if self.app:
            self.app.exit()

    def _cmd_theme(self, args: List[str]) -> None:
        """切换主题"""
        if not args:
            themes = ", ".join(self.theme_names)
            current = self._theme.name
            self.add_output(f"Current theme: {current}\nAvailable: {themes}\nUsage: /theme <name>", role="system")
            return

        name = args[0].lower()
        if self.switch_theme(name):
            self.add_output(f"Theme switched to: {name}", role="system")
        else:
            available = ", ".join(self.theme_names)
            self.add_output(f"Unknown theme '{name}'. Available: {available}", role="error")

    def _cmd_provider(self, args: List[str]) -> None:
        """切换 provider"""
        if not args:
            try:
                config = config_manager.load_config()
                default = config.llm.default_provider
                self.add_output(f"Current provider: {default}\nUsage: /provider <provider_name>", role="system")
            except Exception:
                self.add_output(f"Usage: /provider <provider_name>", role="system")
            return

        name = args[0]
        self.add_output(f"Provider set to: {name}", role="system")
        # 实际切换需要重建 LLM 客户端

    def _cmd_run(self, args: List[str]) -> None:
        """执行工作流"""
        if not args:
            self.add_output("Usage: /run <workflow_file>", role="error")
            return
        self.add_output(f"Executing workflow: {args[0]}", role="system")

    def _cmd_list_workflows(self, args: List[str]) -> None:
        """列出工作流"""
        try:
            from core.storage import workflow_storage
            workflows = workflow_storage.list()
            if not workflows:
                self.add_output("No workflows found.", role="system")
                return
            lines = ["  Saved workflows:"]
            for wf in sorted(workflows):
                lines.append(f"    - {wf}")
            self.add_output("\n".join(lines), role="system")
        except ImportError:
            self.add_output("Storage module not available.", role="system")

    def _cmd_history(self, args: List[str]) -> None:
        """执行历史"""
        try:
            from core.db import execution_db
            limit = int(args[0]) if args else 10
            executions = execution_db.list_executions(limit=limit)
            if not executions:
                self.add_output("No execution history found.", role="system")
                return
            lines = ["  Execution history:"]
            for ex in executions:
                status = ex.get("status", "unknown")
                name = ex.get("workflow_name", "?")
                dur = ex.get("total_duration_ms")
                dur_s = f"{dur}ms" if dur else "N/A"
                lines.append(f"    [{ex.get('id', '?')}] {name} - {status} ({dur_s})")
            self.add_output("\n".join(lines), role="system")
        except ImportError:
            self.add_output("Database module not available.", role="system")

    def _cmd_validate(self, args: List[str]) -> None:
        """验证工作流"""
        if not args:
            self.add_output("Usage: /validate <workflow_file>", role="error")
            return
        self.add_output(f"Validating: {args[0]}", role="system")

    def _cmd_templates(self, args: List[str]) -> None:
        """列出模板"""
        try:
            from tui.templates import get_templates
            templates = get_templates()
            if not templates:
                self.add_output("No templates available.", role="system")
                return
            lines = ["  Available templates:"]
            for t in templates:
                lines.append(f"    - {t['name']}: {t['description']} ({t['agent_count']} agents)")
            self.add_output("\n".join(lines), role="system")
        except ImportError:
            self.add_output("Templates module not available.", role="system")

    def _cmd_config(self, args: List[str]) -> None:
        """查看配置"""
        try:
            config = config_manager.load_config()
            info = {
                "provider": config.llm.default_provider,
                "model": config.llm.default_model,
                "temperature": config.llm.temperature,
                "max_tokens": config.llm.max_tokens,
                "timeout": config.llm.timeout,
            }
            lines = ["  Current configuration:"]
            for k, v in info.items():
                lines.append(f"    {k}: {v}")
            self.add_output("\n".join(lines), role="system")
        except Exception as e:
            self.add_output(f"Config error: {e}", role="error")

    def _cmd_stats(self, args: List[str]) -> None:
        """显示上下文统计"""
        lines = [
            "  Context statistics:",
            f"    Output entries: {len(self.output)}",
            f"    Estimated tokens: {self._token_count}",
            f"    Token limit: {self._token_limit}",
            f"    API calls: {self._api_call_count}",
            f"    Last latency: {self._last_latency_ms}ms",
        ]
        if self.session:
            lines.append(f"    Session: {self.session.id[:16]}")
            lines.append(f"    Session status: {self.session.status.value}")
            lines.append(f"    Session messages: {self.session.message_count}")
        self.add_output("\n".join(lines), role="system")

    def _cmd_status(self, args: List[str]) -> None:
        """显示当前会话状态"""
        self._cmd_stats(args)

    # ==================== 操作处理 ====================

    def _handle_compact(self) -> None:
        """压缩上下文"""
        self.add_output("Context compaction triggered.", role="system")
        # TODO: 集成 ContextCompressor
        # 需要 LLM 客户端来生成摘要
        self._token_count = max(0, self._token_count // 2)

    def _handle_new_session(self) -> None:
        """创建新会话"""
        if self._enable_session and self.session_mgr:
            try:
                # 保存旧会话（如果有）
                old_id = self.session.id if self.session else None

                # 创建新会话
                directory = os.getcwd()
                self.session = self.session_mgr.create_session(
                    title=f"REPL Session",
                    directory=directory,
                )
                self.clear_output()
                self._reset_stats()
                self.add_output(
                    f"New session created: {self.session.id[:12]}",
                    role="system",
                )
                if old_id:
                    self.add_output(f"Previous session: {old_id[:12]}", role="system")
            except Exception as e:
                self.add_output(f"Failed to create session: {e}", role="error")
        else:
            self.clear_output()
            self._reset_stats()
            self.add_output("New session started (session manager disabled).", role="system")

    def _handle_list_sessions(self) -> None:
        """列出会话"""
        if not self._enable_session or not self.session_mgr:
            self.add_output("Session manager is disabled.", role="system")
            return

        try:
            sessions = self.session_mgr.list_sessions(limit=20)
            if not sessions:
                self.add_output("No saved sessions found.", role="system")
                return

            lines = ["  Recent sessions:"]
            for s in sessions:
                is_current = self.session and s.id == self.session.id
                marker = " *" if is_current else "  "
                title = s.title or "(untitled)"
                status = s.status.value
                updated = s.updated_at.strftime("%m/%d %H:%M") if s.updated_at else "?"
                lines.append(
                    f"  {marker} [{s.id[:8]}] {title} — {status} ({updated}) — {s.message_count} msgs"
                )

            self.add_output("\n".join(lines), role="system")
        except Exception as e:
            self.add_output(f"Failed to list sessions: {e}", role="error")

    def _handle_undo(self) -> None:
        """撤销上次操作"""
        if not self.output:
            self.add_output("Nothing to undo.", role="system")
            return

        entry = self.output.pop()
        self._undo_stack.append(entry)
        self.add_output(f"Undone: {entry.text[:80]}...", role="system")

    def _handle_redo(self) -> None:
        """重做"""
        if not self._undo_stack:
            self.add_output("Nothing to redo.", role="system")
            return

        entry = self._undo_stack.pop()
        self.output.append(entry)
        self.add_output(f"Redone: {entry.text[:80]}...", role="system")

    def _handle_list_models(self) -> None:
        """Ctrl+X M：列出模型"""
        self._cmd_list_models([])

    def _reset_stats(self) -> None:
        """重置统计"""
        self._token_count = 0
        self._last_latency_ms = 0
        self._api_call_count = 0

    # ==================== 主循环 ====================

    def _process_queue(self) -> None:
        """处理输入队列中的消息（保留用于降级模式和其他路径）"""
        try:
            while True:
                text = self._input_queue.get_nowait()
                self._process_entry(text)
        except queue.Empty:
            pass

    def _process_ui_updates(self) -> None:
        """处理来自 Agent Loop 后台线程的 UI 更新（线程安全）

        在 prompt_toolkit 主线程中调用，从 _ui_update_queue 消费更新并应用到 UI。
        """
        try:
            while True:
                action, kwargs = self._ui_update_queue.get_nowait()

                if action == "text_delta":
                    token = kwargs.get("text", "")
                    if self.output and self.output[-1].role == "assistant":
                        self.output[-1].text += token
                    else:
                        self.add_output(token, role="assistant")

                elif action == "thinking_delta":
                    token = kwargs.get("text", "")
                    if self.output and self.output[-1].role == "system" \
                            and self.output[-1].text.startswith("[thinking]"):
                        self.output[-1].text += token
                    else:
                        self.add_output(f"[thinking] {token}", role="system")

                elif action == "tool_call_start":
                    tool_name = kwargs.get("name", "?")
                    tool_args = kwargs.get("args", {})
                    self.add_output(f"[tool] Calling {tool_name}...", role="tool")
                    if tool_args:
                        self.add_output(
                            f"  args: {json.dumps(tool_args, ensure_ascii=False)[:300]}",
                            role="tool",
                        )

                elif action == "tool_result":
                    output = kwargs.get("output", "")
                    self.add_output(f"[tool result] {output}", role="tool")

                elif action == "error":
                    msg = kwargs.get("message", "Unknown error")
                    self.add_output(f"[error] {msg}", role="error")

                elif action == "interrupted":
                    self.add_output("Interrupted.", role="system")

                elif action == "agent_done":
                    # Agent Loop 结束，状态已更新
                    pass

                elif action == "invalidate":
                    pass  # 仅触发刷新

                if self.app:
                    self.app.invalidate()

        except queue.Empty:
            pass

    def _process_entry(self, text: str) -> None:
        """处理单条输入"""
        # 检查是否是命令
        if text.startswith("/"):
            should_exit = self._dispatch_command(text)
            if should_exit:
                self._should_exit = True
                if self.app:
                    self.app.exit()
            return

        # 检查是否是特殊语法
        if text.startswith("!"):
            # !command = 执行 shell 命令
            shell_cmd = text[1:].strip()
            self.add_output(f"! {shell_cmd}", role="user")
            self._execute_shell(shell_cmd)
            return

        # 普通消息
        self._dispatch_message(text)

    def _execute_shell(self, command: str) -> None:
        """执行 shell 命令"""
        import subprocess
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd(),
            )
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

    # ==================== Agent Loop 管理 ====================

    def _init_agent_loop(self) -> None:
        """初始化 Agent Loop"""
        try:
            from tui.agent_loop import AgentLoop, create_agent_loop_from_config
            from core.tool_registry import get_default_registry

            tool_registry = get_default_registry()
            self._agent_loop = create_agent_loop_from_config(tool_registry=tool_registry)
            self.add_output("Agent loop initialized.", role="system")
        except ImportError as e:
            self.add_output(
                f"AgentLoop not available: {e}\n"
                "Falling back to echo mode.",
                role="system",
            )
            self._agent_loop = None
        except Exception as e:
            self.add_output(f"Failed to initialize agent loop: {e}", role="system")
            self._agent_loop = None

    # ==================== 生命周期 ====================

    def _init_session(self) -> None:
        """初始化会话"""
        if self._enable_session and self.session_mgr:
            try:
                directory = os.getcwd()
                self.session = self.session_mgr.create_session(
                    title=f"REPL Session",
                    directory=directory,
                    metadata={"model": DEFAULT_MODEL, "provider": DEFAULT_PROVIDER},
                )
                self.add_output(
                    f"Session: {self.session.id[:12]}",
                    role="system",
                )
            except Exception as e:
                self.add_output(f"Session init failed: {e}", role="system")
                self.session = None

    def run(self) -> None:
        """运行 REPL 主循环"""
        self._running = True
        self._should_exit = False

        # 初始化会话
        self._init_session()

        # 初始化 Agent Loop
        self._init_agent_loop()

        # 尝试创建 prompt_toolkit Application
        try:
            self.app = Application(
                layout=self._build_layout(),
                key_bindings=self.kb,
                style=build_pt_style(self._theme),
                full_screen=True,
                mouse_support=True,
                enable_page_navigation_bindings=True,
            )
        except Exception as e:
            # Windows Git Bash / mintty 不支持全屏终端，降级为简单模式
            self._output_buffer = [(BANNER.strip(), "system")]
            self._run_fallback(f"prompt_toolkit 不可用 ({e})，使用降级模式。输入 /exit 退出。")
            return

        # 显示横幅
        self.add_output(BANNER.strip(), role="system")
        self.add_output("  GrassFlow REPL", role="system")
        self.add_output("  Type /help for commands, Ctrl+X Q to exit.", role="system")
        self.add_output("", role="system")

        # 注册 UI 更新处理器 — 每次 prompt_toolkit 重绘时消费线程安全队列
        def _process_ui_updates_from_agent():
            """从线程安全队列消费 Agent Loop 产出的 UI 更新（在 UI 线程执行）"""
            self._process_ui_updates()
            if self._should_exit:
                self.app.exit()

        # prompt_toolkit 的 on_invalidate 在每次渲染前被调用，是安全的 UI 线程回调
        # 使用 lambda 包装忽略 sender 参数（prompt_toolkit Event 系统会传入 sender）
        self.app.on_invalidate += lambda _: _process_ui_updates_from_agent()

        # 使用 asyncio 事件循环运行
        try:
            self.app.run()
        except Exception as e:
            self.add_output(f"REPL error: {e}", role="error")
        finally:
            self._running = False

        # 清理
        self._cleanup()

    def _run_fallback(self, notice: str = "") -> None:
        """降级模式：使用 input() 的简单 REPL（兼容 Git Bash / mintty / 非全屏终端）

        当 prompt_toolkit 的 Application 无法创建时使用。
        """
        self._running = True
        self._should_exit = False

        # 使用 Rich Console 渲染
        console = RichConsole(highlight=False)

        # 显示 banner 和通知
        console.print(Panel.fit(BANNER.strip(), style="bold cyan", title="GrassFlow REPL"))
        if notice:
            console.print(f"  [dim yellow]{notice}[/dim yellow]")
        console.print("  [dim]Type /help for commands, /exit to quit.[/dim]")
        console.print()

        while self._running and not self._should_exit:
            try:
                user_input = input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                console.print("\n  Goodbye!")
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            # 处理内部命令（不需要 Agent Loop）
            if stripped == "/exit" or stripped == "/quit" or stripped == "/q":
                console.print("  Goodbye!")
                break
            elif stripped == "/clear" or stripped == "/cls":
                console.clear()
                continue
            elif stripped == "/help":
                handler = CommandHandler()
                console.print(Markdown(handler.get_help_text()))
                continue

            # 流式调用 Agent Loop
            console.print()
            console.print(f"[bold blue]{PROMPT}[/bold blue]{stripped}")

            if self._agent_loop:
                full_text = ""
                try:
                    # 异步迭代：需要在 sync 代码中用 asyncio.run 消费
                    async def _consume():
                        nonlocal full_text
                        async for event in self._agent_loop.process_streaming(stripped):
                            etype = event.type
                            edata = event.data

                            if etype in ("text_delta",):
                                token = edata.get("text", "")
                                full_text += token
                                console.print(token, end="", highlight=False)
                            elif etype == "thinking_delta":
                                token = edata.get("text", "")
                                if not full_text and not getattr(_consume, "_thinking_shown", False):
                                    console.print("  [dim italic]思考中...[/dim italic]")
                                    _consume._thinking_shown = True
                            elif etype == "tool_call_start":
                                name = edata.get("name", "?")
                                args = edata.get("args", {})
                                args_str = json.dumps(args, ensure_ascii=False)[:200] if args else ""
                                console.print(f"\n  [bold yellow][tool] Calling {name}[/bold yellow]", highlight=False)
                                if args_str:
                                    console.print(f"  [dim]  args: {args_str}[/dim]", highlight=False)
                            elif etype == "tool_result":
                                result = edata.get("result", edata.get("output", ""))
                                is_err = edata.get("is_error", edata.get("success", True) is False)
                                style = "bold red" if is_err else "dim"
                                result_preview = str(result)[:500]
                                console.print(f"  [{style}][tool result] {result_preview}[/{style}]", highlight=False)
                            elif etype == "error":
                                msg = edata.get("message", str(edata))
                                console.print(f"\n  [bold red][error] {msg}[/bold red]", highlight=False)
                            elif etype == "interrupted":
                                console.print("\n  [yellow]Interrupted.[/yellow]", highlight=False)

                    asyncio.run(_consume())
                    console.print()  # 换行
                except Exception as e:
                    console.print(f"\n[bold red]Error: {e}[/bold red]")
            else:
                # 无 Agent Loop，回显模式
                console.print(f"  {stripped}")

            console.print()

    def _cleanup(self) -> None:
        """清理资源"""
        if self.session and self._enable_session and self.session_mgr:
            try:
                pass
            except Exception:
                pass

        print("\n  Goodbye!")
        print()

    def stop(self) -> None:
        """停止 REPL"""
        self._should_exit = True
        if self.app:
            self.app.exit()


# ==================== 异步运行支持 ====================


class AsyncGrassFlowREPL(GrassFlowREPL):
    """支持异步事件循环的 REPL 变体"""

    async def run_async(self) -> None:
        """异步运行 REPL"""
        self._running = True
        self._should_exit = False

        self._init_session()

        self.add_output(BANNER.strip(), role="system")
        self.add_output("  GrassFlow REPL (async)", role="system")
        self.add_output("  Type /help for commands, Ctrl+X Q to exit.", role="system")
        self.add_output("", role="system")

        self._init_agent_loop()

        self.app = Application(
            layout=self._build_layout(),
            key_bindings=self.kb,
            style=build_pt_style(self._theme),
            full_screen=True,
            mouse_support=True,
            enable_page_navigation_bindings=True,
        )

        try:
            await self.app.run_async()
        except Exception as e:
            self.add_output(f"REPL error: {e}", role="error")
        finally:
            self._running = False

        self._cleanup()


# ==================== 便捷函数 ====================


def _new_create_repl(
    theme: Optional[str] = None,
    enable_session: bool = True,
    enable_streaming: bool = True,
) -> GrassFlowREPL:
    """创建 GrassFlowREPL 实例（新版内部工厂）

    Args:
        theme: 主题名称
        enable_session: 是否启用会话管理
        enable_streaming: 是否启用流式输出

    Returns:
        GrassFlowREPL 实例
    """
    repl_theme = None
    if theme and theme in BUILTIN_THEMES:
        repl_theme = BUILTIN_THEMES[theme]

    return GrassFlowREPL(
        theme=repl_theme,
        enable_session=enable_session,
        enable_streaming=enable_streaming,
    )


def run_repl(
    theme: Optional[str] = None,
    enable_session: bool = True,
    enable_streaming: bool = True,
) -> None:
    """运行 REPL

    Args:
        theme: 主题名称
        enable_session: 是否启用会话管理
        enable_streaming: 是否启用流式输出
    """
    repl = _new_create_repl(
        theme=theme,
        enable_session=enable_session,
        enable_streaming=enable_streaming,
    )
    repl.run()


async def run_repl_async(
    theme: Optional[str] = None,
    enable_session: bool = True,
    enable_streaming: bool = True,
) -> None:
    """异步运行 REPL"""
    repl_theme = None
    if theme and theme in BUILTIN_THEMES:
        repl_theme = BUILTIN_THEMES[theme]

    repl = AsyncGrassFlowREPL(
        theme=repl_theme,
        enable_session=enable_session,
        enable_streaming=enable_streaming,
    )
    await repl.run_async()


# ==================== 向后兼容层 ====================

from dataclasses import dataclass
from datetime import datetime as _dt
from enum import Enum as _Enum


class MessageRole(str, _Enum):
    """消息角色（向后兼容）"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"


@dataclass
class Message:
    """消息类（向后兼容）"""
    role: MessageRole
    content: str
    timestamp: datetime = None
    metadata: dict = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _dt.now()
        if self.metadata is None:
            self.metadata = {}

    def __repr__(self):
        content_preview = self.content[:30] + "..." if len(self.content) > 30 else self.content
        return f"Message(role={self.role.value}, content='{content_preview}')"


@dataclass
class CommandResult:
    """命令结果（向后兼容）"""
    success: bool = True
    message: str = ""
    should_exit: bool = False
    data: dict = None


class CommandHandler:
    """命令处理器（向后兼容，映射到新 REPL 的命令系统）"""

    KNOWN_COMMANDS = {
        "help": "Show available commands",
        "run": "Run a workflow file",
        "validate": "Validate a workflow file",
        "clear": "Clear the screen",
        "exit": "Exit REPL",
        "quit": "Exit REPL (alias)",
        "q": "Exit REPL (alias)",
        "model": "Switch model",
        "models": "List models",
        "session": "Session management",
        "sessions": "List sessions",
        "compact": "Compact context",
        "theme": "Switch theme",
        "init": "Initialize AGENTS.md",
        "undo": "Undo last change",
        "redo": "Redo last undo",
    }

    def __init__(self):
        self._custom_commands = {}

    def parse(self, text: str):
        """解析命令"""
        if not text.startswith("/"):
            return None
        parts = text[1:].strip().split()
        if not parts or not parts[0]:
            return None
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        return (cmd, args)

    def execute(self, text: str) -> CommandResult:
        """执行命令"""
        parsed = self.parse(text)
        if parsed is None:
            return CommandResult(success=False, message="Not a command")

        cmd, args = parsed

        if cmd == "help":
            return CommandResult(success=True, message=self.get_help_text())
        elif cmd in ("exit", "quit", "q"):
            return CommandResult(success=True, message="Goodbye!", should_exit=True)
        elif cmd == "clear":
            return CommandResult(success=True, data={"action": "clear"})
        elif cmd == "run":
            if not args:
                return CommandResult(success=False, message="Usage: /run <file.af>")
            return CommandResult(success=True, data={"action": "run", "file": args[0]})
        elif cmd == "validate":
            if not args:
                return CommandResult(success=False, message="Usage: /validate <file.af>")
            return CommandResult(success=True, data={"action": "validate", "file": args[0]})
        elif cmd in self._custom_commands:
            return self._custom_commands[cmd](args)

        return CommandResult(success=False, message=f"Unknown command: /{cmd}")

    def register(self, name: str, handler, description: str = ""):
        """注册自定义命令"""
        self._custom_commands[name] = handler
        self.KNOWN_COMMANDS[name] = description

    def get_help_text(self) -> str:
        """获取帮助文本"""
        lines = ["Available commands:", ""]
        for name, desc in self.KNOWN_COMMANDS.items():
            if name in ("quit", "q"):
                continue
            alias = ""
            if name == "exit":
                alias = " (alias: /quit, /q)"
            lines.append(f"  /{name}{alias} - {desc}")
        return "\n".join(lines)


class InputHandler:
    """输入处理器（向后兼容，模拟旧版 prompt_toolkit 之前的行为）"""

    def __init__(self, history_max_size: int = 100):
        self.history = []
        self.history_max_size = history_max_size
        self.history_index = 0
        self._interrupted = False

    @property
    def is_interrupted(self) -> bool:
        return self._interrupted

    def signal_interrupt(self):
        self._interrupted = True

    def clear_interrupt(self):
        self._interrupted = False

    def add_to_history(self, entry: str):
        """添加历史记录"""
        entry = entry.strip()
        if not entry:
            return
        # 去重
        if self.history and self.history[-1] == entry:
            return
        self.history.append(entry)
        # 限制大小
        if len(self.history) > self.history_max_size:
            self.history = self.history[-self.history_max_size:]

    def reset_history_index(self):
        self.history_index = len(self.history)

    def get_previous(self) -> str:
        """获取上一条历史"""
        if not self.history:
            return ""
        if self.history_index > 0:
            self.history_index -= 1
        return self.history[self.history_index]

    def get_next(self) -> str:
        """获取下一条历史"""
        if self.history_index >= len(self.history) - 1:
            self.history_index = len(self.history)
            return ""
        self.history_index += 1
        return self.history[self.history_index]


class MessageRenderer:
    """消息渲染器（向后兼容，使用 Rich）"""

    def __init__(self, console=None):
        if console is None:
            try:
                from rich.console import Console
                self.console = Console()
            except ImportError:
                self.console = MagicMock() if "MagicMock" in globals() else None
        else:
            self.console = console

    def render_message(self, msg: Message):
        """渲染消息"""
        if self.console:
            try:
                prefix = {"user": "You: ", "assistant": "Assistant: ", "system": "", "error": "[ERROR] "}.get(
                    msg.role.value if hasattr(msg.role, 'value') else msg.role, "")
                self.console.print(f"{prefix}{msg.content}")
            except Exception:
                pass

    def render_markdown(self, text: str):
        """渲染 Markdown"""
        if self.console:
            try:
                from rich.markdown import Markdown
                self.console.print(Markdown(text))
            except ImportError:
                self.console.print(text)

    def render_code(self, code: str, language: str = ""):
        """渲染代码块"""
        if self.console:
            try:
                from rich.syntax import Syntax
                lang = language if language else "text"
                self.console.print(Syntax(code, lang))
            except ImportError:
                self.console.print(code)

    def render_table(self, title: str, headers: list, rows: list):
        """渲染表格"""
        if self.console:
            try:
                from rich.table import Table
                table = Table(title=title)
                for h in headers:
                    table.add_column(h)
                for row in rows:
                    table.add_row(*[str(c) for c in row])
                self.console.print(table)
            except ImportError:
                pass

    def render_panel(self, content: str, title: str = ""):
        """渲染面板"""
        if self.console:
            try:
                from rich.panel import Panel
                self.console.print(Panel(content, title=title))
            except ImportError:
                self.console.print(content)

    def _looks_like_markdown(self, text: str) -> bool:
        """检测是否包含 Markdown 语法"""
        import re
        md_patterns = [
            r'^#{1,6}\s',       # 标题
            r'\*\*.*\*\*',      # 粗体
            r'```[\s\S]*```',   # 代码块
            r'`[^`]+`',         # 行内代码
            r'^\s*[-*+]\s',     # 列表
            r'^\s*\d+\.\s',     # 有序列表
        ]
        return any(re.search(p, text, re.MULTILINE) for p in md_patterns)


# ---- REPL（旧版兼容包装） ----

class REPL:
    """REPL 旧版兼容包装

    将旧版 REPL API 委托给新的 GrassFlowREPL 实现。
    保持与 tests/test_repl.py 的完全兼容。

    旧版 API::

        repl = REPL(console=mock)
        repl = REPL(on_message=callback)
        repl._process_input("/help")   # → bool (True = should exit)
        repl._process_input("message")  # → bool
        repl._clear_screen()
        repl.stop()
        print(repl.messages)
    """

    def __init__(self, console=None, on_message=None):
        self.console = console
        self.on_message = on_message
        self.messages: List[Message] = []

        # 内部使用新的 GrassFlowREPL 实现
        self._repl = GrassFlowREPL(enable_session=False)

        # 旧版组件
        self._command_handler = CommandHandler()
        self._renderer = MessageRenderer(console=console)
        self._input_handler = InputHandler()

        # 旧版状态
        self._running = False

    def _process_input(self, text: str) -> bool:
        """处理单行输入

        Returns:
            True 表示需要退出，False 表示继续
        """
        stripped = text.strip() if text else ""

        # 空输入 / 纯空白
        if not stripped:
            return False

        # 添加到输入历史
        self._input_handler.add_to_history(stripped)

        # 命令处理
        if stripped.startswith("/"):
            result = self._command_handler.execute(stripped)
            self.messages.append(Message(
                MessageRole.SYSTEM,
                result.message,
                metadata={"success": result.success},
            ))

            # 特殊处理 clear
            if result.data and result.data.get("action") == "clear":
                self._clear_screen()
                return False

            if result.should_exit:
                self._running = False
                return True

            # help 命令渲染
            if stripped in ("/help", "/h"):
                self._renderer.render_markdown(result.message)

            return False

        # 普通消息 — 通过 on_message 回调处理
        user_msg = Message(MessageRole.USER, stripped)
        self.messages.append(user_msg)

        if self.on_message:
            try:
                response = self.on_message(stripped)
                if response:
                    assistant_msg = Message(MessageRole.ASSISTANT, response)
                    self.messages.append(assistant_msg)
                    self._renderer.render_message(assistant_msg)
            except Exception as e:
                error_msg = Message(MessageRole.ERROR, str(e))
                self.messages.append(error_msg)
                self._renderer.render_message(error_msg)

        return False

    def _clear_screen(self) -> None:
        """清屏"""
        if self.console and hasattr(self.console, 'clear'):
            self.console.clear()

    def _get_prompt_text(self) -> str:
        """获取提示符文本"""
        return ">>> "

    def stop(self) -> None:
        """停止 REPL"""
        self._running = False
        self._repl.stop()

    def run(self) -> None:
        """运行 REPL（委托给新实现）"""
        self._running = True
        self._repl.run()
        self._running = False


# ---- 旧版工厂函数（覆盖新的 create_repl，提供向后兼容） ----

def create_repl(on_message=None, console=None):
    """创建 REPL 实例（向后兼容旧版 API）

    Args:
        on_message: 消息回调，接收用户输入字符串，返回响应字符串
        console: Rich console 实例

    Returns:
        REPL 实例（旧版兼容包装）
    """
    return REPL(console=console, on_message=on_message)


# ==================== 入口 ====================

if __name__ == "__main__":
    run_repl()

"""
GrassFlow 向后兼容层

提供旧版 API 的兼容实现，委托给新的 GrassFlowREPL。
旧代码中 `from tui.repl import Message, MessageRole, CommandResult` 等
仍然可用，repl.py 会 re-export 这些类。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as _dt
from enum import Enum as _Enum
from typing import Any, Callable, Dict, List, Optional


# ==================== 数据模型 ====================


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
    timestamp: _dt = None
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


# ==================== 命令 / 输入 / 渲染 ====================


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


# ==================== REPL 旧版包装 ====================


class REPL:
    """REPL 旧版兼容包装

    将旧版 REPL API 委托给新的 GrassFlowREPL 实现。
    保持与 tests/test_repl.py 的完全兼容。

    旧版 API::

        repl = REPL(console=mock)
        repl = REPL(on_message=callback)
        repl._process_input("/help")   # -> bool (True = should exit)
        repl._process_input("message")  # -> bool
        repl._clear_screen()
        repl.stop()
        print(repl.messages)
    """

    def __init__(self, console=None, on_message=None):
        self.console = console
        self.on_message = on_message
        self.messages: List[Message] = []

        # 内部使用新的 GrassFlowREPL 实现（延迟导入避免循环依赖）
        from tui.repl import GrassFlowREPL
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


# ==================== 工厂函数 ====================


def create_repl(on_message=None, console=None):
    """创建 REPL 实例（向后兼容旧版 API）

    Args:
        on_message: 消息回调，接收用户输入字符串，返回响应字符串
        console: Rich console 实例

    Returns:
        REPL 实例（旧版兼容包装）
    """
    return REPL(console=console, on_message=on_message)

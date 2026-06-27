"""
GrassFlow REPL Layout — prompt_toolkit 布局、样式和快捷键（hermes patch_stdout 模式）

从 repl.py 中提取的 UI 层逻辑，包括：
- 常量：BANNER, PROMPT, PROMPT_STYLE
- 样式：build_pt_style()
- 布局：build_layout()（只有底部 chrome，输出走 patch_stdout）
- 快捷键：build_keybindings()
- 输出函数：cprint(), format_output_line(), ChatConsole, OutputHistory
- 渲染回调：_get_header_text, _get_status_text, _get_input_prefix
- 数据模型：OutputEntry, REPLMode, REPLTheme, BUILTIN_THEMES

重写说明（hermes patch_stdout 模式）：
- 输出不再通过 FormattedTextControl 渲染在 widget 树中
- 所有输出通过 cprint() 打印到终端 scrollback，终端模拟器原生处理滚动
- mouse_support=False — 禁用 prompt_toolkit 的鼠标事件拦截
- Layout 只有底部 chrome：spacer + status_bar + input_area
"""

from __future__ import annotations

import re as _re
import shutil
from collections import deque
from io import StringIO
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

# ==================== prompt_toolkit ====================

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.layout.dimension import Dimension


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

DEFAULT_MODEL = "deepseek-v4-flash"
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


# ==================== 辅助函数 ====================


def get_role_style(role: str) -> str:
    """获取角色的 prompt_toolkit style tag"""
    mapping = {
        "user": "msg-user",
        "assistant": "msg-assistant",
        "system": "msg-system",
        "error": "msg-error",
        "tool": "msg-tool",
    }
    return mapping.get(role, "msg-system")


# ==================== Style 构建 ====================


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


# ==================== 输出函数（hermes cprint 模式） ====================

# ANSI escape pattern for stripping
_OSC_ESCAPE_RE = _re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")

# Output history for resize replay
_OUTPUT_HISTORY: deque = deque(maxlen=200)
_OUTPUT_HISTORY_ENABLED = True

# Global event loop reference for cross-thread cprint (set by repl.py)
_loop: Optional[Any] = None


def set_event_loop(loop: Any) -> None:
    """Set the module-level event loop reference (called by repl.py)."""
    global _loop
    _loop = loop


def _record_output_history(text: str) -> None:
    """Record output to history for resize replay."""
    if _OUTPUT_HISTORY_ENABLED:
        _OUTPUT_HISTORY.append(text)


class OutputHistory:
    """Output history manager for resize replay."""
    history = _OUTPUT_HISTORY
    enabled = _OUTPUT_HISTORY_ENABLED

    @staticmethod
    def record(text: str) -> None:
        _record_output_history(text)

    @staticmethod
    def replay() -> None:
        replay_output_history()


def replay_output_history() -> None:
    """Repaint recent output above the prompt after a full screen clear."""
    if not _OUTPUT_HISTORY_ENABLED or not _OUTPUT_HISTORY:
        return
    try:
        rendered_lines = []
        for entry in tuple(_OUTPUT_HISTORY):
            if callable(entry):
                lines = entry()
                if isinstance(lines, str):
                    lines = lines.splitlines()
            else:
                lines = [entry]
            rendered_lines.extend(str(line) for line in lines)
        if rendered_lines:
            from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
            from prompt_toolkit import print_formatted_text as _pt_print
            _pt_print(_PT_ANSI("\n".join(rendered_lines)))
    except Exception:
        pass


def format_output_line(entry: OutputEntry) -> str:
    """Format an OutputEntry as an ANSI-colored string for terminal output."""
    timestamp = entry.timestamp.strftime("%H:%M:%S")
    prefix_map = {
        "user": "  ❯ ",       # >
        "assistant": "  ● ",  # bullet
        "system": "  · ",    # middle dot
        "error": "  ✖ ",     # X
        "tool": "  ⚒ ",      # hammer
    }
    prefix = prefix_map.get(entry.role, "  · ")
    role_color_map = {
        "user": "\033[1;94m",       # bold blue
        "assistant": "\033[32m",    # green
        "system": "\033[2;37m",     # dim white
        "error": "\033[1;31m",      # bold red
        "tool": "\033[35m",         # magenta
    }
    color = role_color_map.get(entry.role, "\033[0m")
    reset = "\033[0m"
    dim = "\033[2m"
    return f"{dim}[{timestamp}]{reset}{color}{prefix}{entry.text}{reset}"


def cprint(text: str) -> None:
    """Print ANSI-colored text through prompt_toolkit's native renderer (hermes _cprint).

    Routes text through print_formatted_text(ANSI(...)) so it appears above
    the prompt input in terminal scrollback.
    """
    _record_output_history(text)
    try:
        from prompt_toolkit.application import get_app_or_none, run_in_terminal
        from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
        from prompt_toolkit import print_formatted_text as _pt_print
    except Exception:
        print(text)
        return

    app = None
    try:
        app = get_app_or_none()
    except Exception:
        app = None

    # No active app, or we're already on the app's main thread
    if app is None or not getattr(app, "_is_running", False):
        try:
            _pt_print(_PT_ANSI(text))
        except Exception:
            try:
                print(text)
            except Exception:
                pass
        return

    # Cross-thread emission: ask the app's event loop to schedule
    # a run_in_terminal that wraps _pt_print
    def _schedule():
        try:
            import asyncio as _aio
            import inspect as _inspect
            coro = run_in_terminal(lambda: _pt_print(_PT_ANSI(text)))
            if coro is not None and (_inspect.isawaitable(coro) or _inspect.iscoroutine(coro)):
                _aio.ensure_future(coro)
        except Exception:
            pass

    try:
        _loop.call_soon_threadsafe(_schedule)
    except Exception:
        try:
            _pt_print(_PT_ANSI(text))
        except Exception:
            try:
                print(text)
            except Exception:
                pass


class ChatConsole:
    """Rich Console adapter for prompt_toolkit's patch_stdout context (hermes ChatConsole).

    Captures Rich's rendered ANSI output into a StringIO, then routes each line
    through cprint() so it works inside prompt_toolkit's patch_stdout context.
    """

    def __init__(self):
        self._buffer = StringIO()
        try:
            from rich.console import Console
            self._inner = Console(
                file=self._buffer, force_terminal=True,
                color_system="truecolor", highlight=False,
            )
        except ImportError:
            self._inner = None

    def print(self, *args, **kwargs):
        if self._inner is None:
            # Fallback: plain print
            text = " ".join(str(a) for a in args)
            cprint(text)
            return
        self._buffer.seek(0)
        self._buffer.truncate()
        self._inner.width = shutil.get_terminal_size((80, 24)).columns
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        output = _OSC_ESCAPE_RE.sub("", output)
        for line in output.rstrip("\n").split("\n"):
            cprint(line)


# ==================== 渲染回调工厂 ====================


def make_header_text_cb(
    session: Any,
    output: List[OutputEntry],
    mode: Any,
    default_model: str = "deepseek-v4-flash",
) -> Callable[[], List[Tuple[str, str]]]:
    """创建顶部状态栏渲染回调

    Args:
        session: SessionInfo 实例（或 None）
        output: 输出条目列表（用于消息计数）
        mode: 当前 REPL 模式（REPLMode 值或返回 REPLMode 的 callable）
        default_model: 默认模型名称

    Returns:
        返回 formatted text 的回调函数
    """

    def _get_header_text() -> List[Tuple[str, str]]:
        result: List[Tuple[str, str]] = []
        result.append(("class:header", " GrassFlow "))

        # 模型名
        if session and session.metadata.get("model"):
            model = session.metadata["model"]
            result.append(("class:header-dim", f" |  model: {model}"))
        else:
            result.append(("class:header-dim", f" |  model: {default_model}"))

        # 会话 ID
        if session:
            short_id = session.id[:12]
            result.append(("class:header-dim", f" |  session: {short_id}"))

        # 模式（动态读取）
        current_mode = mode() if callable(mode) else mode
        mode_text = {
            REPLMode.NORMAL: "NORMAL",
            REPLMode.BUSY: "BUSY",
            REPLMode.APPROVAL: "APPROVAL",
        }.get(current_mode, "NORMAL")
        result.append(("class:header-dim", f" |  {mode_text}"))

        # Thinking 模式
        thinking_config = None
        if session:
            thinking_config = session.metadata.get("thinking") if hasattr(session, 'metadata') else None
        if thinking_config and isinstance(thinking_config, dict) and thinking_config.get("enabled", False):
            effort = thinking_config.get("effort", "medium")
            result.append(("class:header-dim", f" | 🧠 {effort}"))

        # 消息计数
        msg_count = len(output)
        result.append(("class:header-dim", f" |  {msg_count} msgs"))

        return result

    return _get_header_text


def make_status_text_cb(
    token_count: int = 0,
    token_limit: int = 128000,
    last_latency_ms: int = 0,
    api_call_count: int = 0,
    agent_running: bool = False,
) -> Callable[[], List[Tuple[str, str]]]:
    """创建底部状态栏渲染回调

    注意：数值类型参数在创建回调时被快照。如果需要动态更新，
    请传入可变容器或在每次 invalidate 时重建回调。

    Args:
        token_count: 当前 token 计数
        token_limit: token 上限
        last_latency_ms: 最近一次 API 延迟
        api_call_count: API 调用次数
        agent_running: Agent 是否正在运行

    Returns:
        返回 formatted text 的回调函数
    """

    def _get_status_text() -> List[Tuple[str, str]]:
        result: List[Tuple[str, str]] = []

        # Token 使用
        if token_count > 0:
            result.append(("class:status-bar", f" Tokens: {token_count}/{token_limit}"))
            pct = token_count / token_limit * 100
            if pct > 80:
                result.append(("class:status-bar-bright", f" ({int(pct)}%!) "))
            else:
                result.append(("class:status-bar", f" ({int(pct)}%) "))
        else:
            result.append(("class:status-bar", " Tokens: 0 "))

        # 延迟
        if last_latency_ms > 0:
            result.append(("class:status-bar", f"|  {last_latency_ms}ms "))

        # API 调用次数
        if api_call_count > 0:
            result.append(("class:status-bar", f"|  {api_call_count} API calls "))

        # 忙碌指示器
        if agent_running:
            result.append(("class:status-bar-bright", "|  ⏳ running... "))

        return result

    return _get_status_text


def make_status_text_from_repl(repl: Any) -> Callable[[], List[Tuple[str, str]]]:
    """从 REPL 实例创建底部状态栏渲染回调（动态读取属性）

    与 make_status_text_cb 不同，此函数在每次调用时从 repl 实例
    读取最新值，适合需要实时更新的场景。

    Args:
        repl: GrassFlowREPL 实例

    Returns:
        返回 formatted text 的回调函数
    """

    def _get_status_text() -> List[Tuple[str, str]]:
        result: List[Tuple[str, str]] = []

        token_count = repl._token_count
        token_limit = repl._token_limit
        last_latency_ms = repl._last_latency_ms
        api_call_count = repl._api_call_count
        agent_running = repl._agent_running

        # Token 使用
        if token_count > 0:
            result.append(("class:status-bar", f" Tokens: {token_count}/{token_limit}"))
            pct = token_count / token_limit * 100
            if pct > 80:
                result.append(("class:status-bar-bright", f" ({int(pct)}%!) "))
            else:
                result.append(("class:status-bar", f" ({int(pct)}%) "))
        else:
            result.append(("class:status-bar", " Tokens: 0 "))

        # 延迟
        if last_latency_ms > 0:
            result.append(("class:status-bar", f"|  {last_latency_ms}ms "))

        # API 调用次数
        if api_call_count > 0:
            result.append(("class:status-bar", f"|  {api_call_count} API calls "))

        # 忙碌指示器
        if agent_running:
            result.append(("class:status-bar-bright", "|  ⏳ running... "))

        return result

    return _get_status_text


def get_input_prefix(line_number: int = 0, wrap_count: int = 0) -> List[Tuple[str, str]]:
    """获取输入区域每行的前缀"""
    if line_number == 0:
        return [("class:prompt", f"{PROMPT}")]
    else:
        return [("class:prompt", "  ")]


# ==================== Layout 构建（hermes 模式 — 只有底部 chrome） ====================


def build_layout(
    input_buffer: Buffer,
    status_text_cb: Callable[[], List[Tuple[str, str]]],
) -> Layout:
    """构建 hermes 模式布局 — 只有底部 chrome

    输出不存在于 layout 中。所有输出通过 patch_stdout() 打印到终端 scrollback，
    由终端模拟器原生处理滚动。

    布局结构（从上到下）::

        1. Window(height=0)  — 不可见顶部锚点
        2. spacer             — Window(hint text)，动态高度，填充剩余空间
        3. status_bar         — height=1
        4. input_rule_top     — Window(char='─', height=1)
        5. input_area         — TextArea, height=1~8 动态
        6. input_rule_bot     — Window(char='─', height=1)
        7. completions_menu   — CompletionsMenu, max_height=12

    Args:
        input_buffer: prompt_toolkit Buffer 实例
        status_text_cb: 底部状态栏文本回调

    Returns:
        prompt_toolkit Layout 实例
    """
    # Spacer：填充 header 和 input 之间的空间
    spacer = Window(
        content=FormattedTextControl(lambda: [("", "")]),
        height=Dimension(weight=1),
    )

    # Status bar
    status_bar = Window(
        content=FormattedTextControl(text=status_text_cb),
        height=1,
        style="class:status-bar",
        wrap_lines=False,
    )

    # 输入区域：hermes 风格，1~8 行动态高度
    input_area = TextArea(
        height=Dimension(min=1, max=8, preferred=1),
        prompt=get_input_prefix,
        style='class:input-area',
        multiline=True,
        wrap_lines=True,
    )
    # Replace TextArea's internal buffer with the caller's buffer.
    # Must update both the attribute AND the BufferControl reference,
    # otherwise the BufferControl still uses the auto-created buffer.
    input_area.buffer = input_buffer
    input_area.control.buffer = input_buffer

    # 分隔线
    input_rule_top = Window(height=1, char="─", style="class:frame-border")
    input_rule_bot = Window(height=1, char="─", style="class:frame-border")

    # Completions menu
    from prompt_toolkit.layout.menus import CompletionsMenu

    completions_menu = CompletionsMenu(max_height=12)

    root_container = HSplit([
        Window(height=0),       # 不可见锚点
        spacer,                 # 填充空间
        status_bar,             # 状态栏
        input_rule_top,         # 分隔线
        input_area,             # 输入区
        input_rule_bot,         # 分隔线
        completions_menu,       # 补全菜单
    ])

    return Layout(root_container)


def build_layout_from_repl(repl: Any) -> Layout:
    """从 REPL 实例构建布局（便捷函数）

    直接使用 repl 实例的属性和方法构建布局，
    内部回调动态读取 repl 的最新状态。

    Args:
        repl: GrassFlowREPL 实例

    Returns:
        prompt_toolkit Layout 实例
    """
    status_cb = make_status_text_from_repl(repl)

    layout = build_layout(
        input_buffer=repl.input_buffer,
        status_text_cb=status_cb,
    )
    return layout


# ==================== KeyBindings 构建（hermes 模式） ====================


class KeybindingCallbacks:
    """快捷键回调集合

    将 REPL 实例的命令处理方法封装为回调对象，
    供 build_keybindings 使用。
    """

    def __init__(
        self,
        mode: Callable[[], REPLMode],
        agent_running: Callable[[], bool],
        should_exit: Callable[[], bool],
        set_should_exit: Callable[[], None],
        interrupt_agent: Callable[[], None],
        add_output: Callable[[str, str], None],
        clear_output: Callable[[], None],
        handle_compact: Callable[[], None],
        handle_new_session: Callable[[], None],
        handle_list_sessions: Callable[[], None],
        handle_undo: Callable[[], None],
        handle_redo: Callable[[], None],
        handle_list_models: Callable[[], None],
        get_app: Callable[[], Any],
        process_input: Optional[Callable[[str], None]] = None,
    ):
        self.mode = mode
        self.agent_running = agent_running
        self.should_exit = should_exit
        self.set_should_exit = set_should_exit
        self.interrupt_agent = interrupt_agent
        self.add_output = add_output
        self.clear_output = clear_output
        self.handle_compact = handle_compact
        self.handle_new_session = handle_new_session
        self.handle_list_sessions = handle_list_sessions
        self.handle_undo = handle_undo
        self.handle_redo = handle_redo
        self.handle_list_models = handle_list_models
        self.get_app = get_app
        self.process_input = process_input


def build_keybindings(callbacks: KeybindingCallbacks) -> KeyBindings:
    """构建 prompt_toolkit KeyBindings（hermes 模式）

    注册所有 REPL 快捷键：
    - Enter: 提交输入
    - Alt+Enter: 多行换行
    - Ctrl+C: 中断 Agent 或退出
    - Ctrl+D: EOF 退出
    - Ctrl+L: 清屏
    - Ctrl+X C/N/L/Q/U/R/M: 压缩/新会话/列出会话/退出/撤销/重做/列出模型
    - Tab: 补全

    注意：不再注册 Ctrl+Up/Down 和 <scroll-up>/<scroll-down>。
    滚动由终端模拟器原生处理（mouse_support=False 让终端处理鼠标滚轮）。

    Args:
        callbacks: 快捷键回调集合

    Returns:
        KeyBindings 实例
    """
    kb = KeyBindings()

    # ---- Enter 键：hermes 模式 ----
    @kb.add("enter")
    def handle_enter(event: KeyPressEvent) -> None:
        """回车：提交输入（hermes 模式）"""
        if callbacks.mode() == REPLMode.APPROVAL:
            return
        if callbacks.agent_running():
            callbacks.add_output("Agent is running. Press Ctrl+C to interrupt first.", "system")
            app = callbacks.get_app()
            if app:
                app.invalidate()
            return

        buffer = event.app.current_buffer
        text = buffer.text.strip()
        buffer.reset()

        if not text:
            return

        if callbacks.process_input:
            callbacks.process_input(text)

    @kb.add("escape", "enter")
    def handle_alt_enter(event: KeyPressEvent) -> None:
        """Alt+Enter：多行输入换行"""
        buffer = event.app.current_buffer
        buffer.insert_text("\n")

    @kb.add("c-c", eager=True)
    def handle_ctrl_c(event: KeyPressEvent) -> None:
        """Ctrl+C：中断 Agent 或退出"""
        if callbacks.agent_running():
            callbacks.interrupt_agent()
            callbacks.add_output("Interrupted by user", "system")
            event.app.invalidate()
        else:
            callbacks.set_should_exit()
            async def _deferred_exit():
                event.app.exit()
            event.app.create_background_task(_deferred_exit())

    @kb.add("c-d", eager=True)
    def handle_ctrl_d(event: KeyPressEvent) -> None:
        """Ctrl+D：EOF，退出"""
        buffer = event.app.current_buffer
        if buffer.text == "":
            callbacks.set_should_exit()
            async def _deferred_exit():
                event.app.exit()
            event.app.create_background_task(_deferred_exit())

    @kb.add("c-l")
    def handle_ctrl_l(event: KeyPressEvent) -> None:
        """Ctrl+L：清屏"""
        callbacks.clear_output()
        event.app.invalidate()

    @kb.add("c-x", "c")
    def handle_compact(event: KeyPressEvent) -> None:
        """Ctrl+X C：压缩上下文"""
        callbacks.handle_compact()
        event.app.invalidate()

    @kb.add("c-x", "n")
    def handle_new_session(event: KeyPressEvent) -> None:
        """Ctrl+X N：新会话"""
        callbacks.handle_new_session()
        event.app.invalidate()

    @kb.add("c-x", "l")
    def handle_sessions(event: KeyPressEvent) -> None:
        """Ctrl+X L：列出会话"""
        callbacks.handle_list_sessions()
        event.app.invalidate()

    @kb.add("c-x", "q")
    def handle_exit(event: KeyPressEvent) -> None:
        """Ctrl+X Q：退出"""
        callbacks.set_should_exit()
        async def _deferred_exit():
            event.app.exit()
        event.app.create_background_task(_deferred_exit())

    @kb.add("c-x", "u")
    def handle_undo(event: KeyPressEvent) -> None:
        """Ctrl+X U：撤销"""
        if callbacks.agent_running():
            callbacks.add_output("Agent is running.", "system")
            event.app.invalidate()
            return
        callbacks.handle_undo()
        event.app.invalidate()

    @kb.add("c-x", "r")
    def handle_redo(event: KeyPressEvent) -> None:
        """Ctrl+X R：重做"""
        if callbacks.agent_running():
            callbacks.add_output("Agent is running.", "system")
            event.app.invalidate()
            return
        callbacks.handle_redo()
        event.app.invalidate()

    @kb.add("c-x", "m")
    def handle_models(event: KeyPressEvent) -> None:
        """Ctrl+X M：列出模型"""
        callbacks.handle_list_models()
        event.app.invalidate()

    @kb.add("tab")
    def handle_tab(event: KeyPressEvent) -> None:
        """Tab：命令/文件补全，无补全器时插入 4 空格"""
        buffer = event.app.current_buffer
        if buffer.completer:
            buffer.start_completion()
        else:
            buffer.insert_text("    ")

    return kb


def build_keybindings_from_repl(repl: Any) -> KeyBindings:
    """从 REPL 实例构建 KeyBindings（便捷函数）

    Args:
        repl: GrassFlowREPL 实例

    Returns:
        KeyBindings 实例
    """
    callbacks = KeybindingCallbacks(
        mode=lambda: repl.mode,
        agent_running=lambda: repl._agent_running,
        should_exit=lambda: repl._should_exit,
        set_should_exit=lambda: setattr(repl, "_should_exit", True),
        interrupt_agent=repl._interrupt_agent,
        add_output=lambda text, role="system": repl.add_output(text, role=role),
        clear_output=repl.clear_output,
        handle_compact=repl._handle_compact,
        handle_new_session=repl._handle_new_session,
        handle_list_sessions=repl._handle_list_sessions,
        handle_undo=repl._handle_undo,
        handle_redo=repl._handle_redo,
        handle_list_models=repl._handle_list_models,
        get_app=lambda: repl.app,
        process_input=repl._process_user_input,
    )
    return build_keybindings(callbacks)

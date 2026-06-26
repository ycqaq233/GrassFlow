"""
GrassFlow REPL Layout — prompt_toolkit 布局、样式和快捷键

从 repl.py 中提取的 UI 层逻辑，包括：
- 常量：BANNER, PROMPT, PROMPT_STYLE
- 样式：build_pt_style()
- 布局：build_layout()
- 快捷键：build_keybindings()
- 渲染回调：_get_header_text, _get_output_text, _get_status_text, _get_input_prefix
- 数据模型：OutputEntry, REPLMode, REPLTheme, BUILTIN_THEMES
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

# ==================== prompt_toolkit ====================

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    Float,
    FloatContainer,
    HSplit,
    Layout,
    ScrollOffsets,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.styles import Style


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


# ==================== 渲染回调工厂 ====================


def make_header_text_cb(
    session: Any,
    output: List[OutputEntry],
    mode: REPLMode,
    default_model: str = "deepseek-chat",
) -> Callable[[], List[Tuple[str, str]]]:
    """创建顶部状态栏渲染回调

    Args:
        session: SessionInfo 实例（或 None）
        output: 输出条目列表（用于消息计数）
        mode: 当前 REPL 模式
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

        # 模式
        mode_text = {
            REPLMode.NORMAL: "NORMAL",
            REPLMode.BUSY: "BUSY",
            REPLMode.APPROVAL: "APPROVAL",
        }.get(mode, "NORMAL")
        result.append(("class:header-dim", f" |  {mode_text}"))

        # 消息计数
        msg_count = len(output)
        result.append(("class:header-dim", f" |  {msg_count} msgs"))

        return result

    return _get_header_text


def make_output_text_cb(
    output: List[OutputEntry],
) -> Callable[[], List[Tuple[str, str]]]:
    """创建输出区域渲染回调

    Args:
        output: 输出条目列表（共享引用，每次调用时读取最新状态）

    Returns:
        返回 formatted text 的回调函数
    """

    def _get_output_text() -> List[Tuple[str, str]]:
        result: List[Tuple[str, str]] = []

        if not output:
            result.append(("class:msg-system", "  Welcome to GrassFlow REPL!\n"))
            result.append(("class:msg-system", "  Type /help for available commands.\n"))
            result.append(("class:msg-system", "  Ctrl+X N for new session, Ctrl+X Q to exit.\n"))
            return result

        for entry in output:
            style = get_role_style(entry.role)
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

    return _get_output_text


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


def get_input_prefix(line_number: int, wrap_count: int) -> List[Tuple[str, str]]:
    """获取输入区域每行的前缀"""
    if line_number == 0:
        return [("class:prompt", f"{PROMPT}")]
    else:
        return [("class:prompt", "  ")]


# ==================== Layout 构建 ====================


def build_layout(
    input_buffer: Buffer,
    header_text_cb: Callable[[], List[Tuple[str, str]]],
    output_text_cb: Callable[[], List[Tuple[str, str]]],
    status_text_cb: Callable[[], List[Tuple[str, str]]],
) -> Layout:
    """构建 prompt_toolkit 布局

    布局结构::

        ┌─────────────────────────────────┐
        │  Header: 模型名 | 会话ID | 模式  │  ← 顶部状态栏
        ├─────────────────────────────────┤
        │                                 │
        │  Output Area (scrollable)       │
        │                                 │
        ├─────────────────────────────────┤
        │  Status: tokens | latency       │  ← 底部状态栏
        ├─────────────────────────────────┤
        │  ❯ ▌ 用户输入                    │  ← 固定底部输入栏
        └─────────────────────────────────┘

    Args:
        input_buffer: prompt_toolkit Buffer 实例
        header_text_cb: 顶部状态栏文本回调
        output_text_cb: 输出区域文本回调
        status_text_cb: 底部状态栏文本回调

    Returns:
        prompt_toolkit Layout 实例
    """
    # 输出区域（可滚动）
    output_window = Window(
        content=FormattedTextControl(
            text=output_text_cb,
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
            content=FormattedTextControl(text=header_text_cb),
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
            content=FormattedTextControl(text=status_text_cb),
            height=1,
            style="class:status-bar",
        ),
        # 输入区域
        Window(
            content=BufferControl(
                buffer=input_buffer,
                input_processors=[],
            ),
            height=3,
            style="class:input-area",
            wrap_lines=True,
            get_line_prefix=get_input_prefix,
        ),
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
    header_cb = make_header_text_cb(
        session=repl.session,
        output=repl.output,
        mode=repl.mode,
        default_model=getattr(repl, "_default_model", "deepseek-chat"),
    )
    output_cb = make_output_text_cb(output=repl.output)
    status_cb = make_status_text_from_repl(repl)

    return build_layout(
        input_buffer=repl.input_buffer,
        header_text_cb=header_cb,
        output_text_cb=output_cb,
        status_text_cb=status_cb,
    )


# ==================== KeyBindings 构建 ====================


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


def build_keybindings(callbacks: KeybindingCallbacks) -> KeyBindings:
    """构建 prompt_toolkit KeyBindings

    注册所有 REPL 快捷键：
    - Enter: 提交输入
    - Alt+Enter: 多行换行
    - Ctrl+C: 中断 Agent 或退出
    - Ctrl+D: EOF 退出
    - Ctrl+L: 清屏
    - Ctrl+X C/N/L/Q/U/R/M: 压缩/新会话/列出会话/退出/撤销/重做/列出模型
    - Tab: 补全
    - Ctrl+Up/Down: 滚动

    Args:
        callbacks: 快捷键回调集合

    Returns:
        KeyBindings 实例
    """
    kb = KeyBindings()

    @kb.add("enter")
    def handle_enter(event: KeyPressEvent) -> None:
        """回车：提交输入"""
        if callbacks.mode() == REPLMode.APPROVAL:
            # 审批模式下，回车 = 确认
            return
        if callbacks.agent_running():
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
        if callbacks.agent_running():
            callbacks.interrupt_agent()
            callbacks.add_output("Interrupted by user", "system")
            event.app.invalidate()
        else:
            # 不运行中时 Ctrl+C = 退出
            callbacks.set_should_exit()
            event.app.exit()

    @kb.add("c-d", eager=True)
    def handle_ctrl_d(event: KeyPressEvent) -> None:
        """Ctrl+D：EOF，退出"""
        buffer = event.app.current_buffer
        if buffer.text == "":
            callbacks.set_should_exit()
            event.app.exit()

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
        event.app.exit()

    @kb.add("c-x", "u")
    def handle_undo(event: KeyPressEvent) -> None:
        """Ctrl+X U：撤销"""
        callbacks.handle_undo()
        event.app.invalidate()

    @kb.add("c-x", "r")
    def handle_redo(event: KeyPressEvent) -> None:
        """Ctrl+X R：重做"""
        callbacks.handle_redo()
        event.app.invalidate()

    @kb.add("c-x", "m")
    def handle_models(event: KeyPressEvent) -> None:
        """Ctrl+X M：列出模型"""
        callbacks.handle_list_models()
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
    )
    return build_keybindings(callbacks)

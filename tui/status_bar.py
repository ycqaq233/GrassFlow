"""
GrassFlow 状态栏组件

参考 opencode/claude-code 底部状态栏设计
显示模型、tokens、成本、延迟、模式等信息
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum

try:
    from rich.console import Console, RenderableType
    from rich.text import Text
    from rich.style import Style
    from rich.panel import Panel
    from rich.table import Table
    from rich.columns import Columns
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class Mode(Enum):
    """运行模式"""
    BUILD = "Build"
    CHAT = "Chat"
    PLAN = "Plan"
    REVIEW = "Review"
    ARCHITECT = "Architect"


@dataclass
class StatusContext:
    """状态栏上下文数据"""
    model: str = ""
    provider: str = ""
    token_used: int = 0
    token_limit: int = 0
    latency_ms: float = 0
    mode: str = "Build"
    tools_count: int = 0
    session_id: str = ""
    cost_usd: float = 0.0
    workflow_name: str = ""
    agent_count: int = 0
    agents_completed: int = 0
    project_dir: str = ""
    context_length: int = 0
    thinking_depth: str = ""
    permission_mode: str = "ask"

    @property
    def token_percent(self) -> float:
        """token 使用百分比"""
        if self.token_limit == 0:
            return 0.0
        return min(self.token_used / self.token_limit * 100, 100.0)

    @property
    def token_bar_width(self) -> int:
        """token 进度条宽度 (字符数)"""
        if self.token_limit == 0:
            return 0
        return max(1, int(self.token_percent / 100 * 10))


class StatusBar:
    """
    终端底部状态栏

    显示信息：
    - 当前模型和 provider
    - token 使用情况 (带进度条)
    - 成本估算
    - 运行模式
    - 延迟
    - 工具调用次数
    - 会话 ID

    使用示例:
        bar = StatusBar()
        ctx = StatusContext(
            model="gpt-4",
            provider="openai",
            token_used=1500,
            token_limit=8192,
            latency_ms=234.5,
            mode="Build",
            tools_count=3,
            session_id="abc123",
            cost_usd=0.045,
            workflow_name="ticket_processing",
        )
        console.print(bar.render(ctx))
    """

    # 配色方案
    COLORS = {
        "bar_bg": "dim",
        "separator": "dim",
        "label": "dim",
        "model": "cyan",
        "provider": "blue",
        "token_ok": "green",
        "token_warn": "yellow",
        "token_critical": "red",
        "cost": "yellow",
        "latency": "magenta",
        "mode": "bold cyan",
        "mode_build": "bold cyan",
        "mode_chat": "bold green",
        "mode_plan": "bold yellow",
        "mode_review": "bold magenta",
        "mode_architect": "bold blue",
        "project_dir": "dim",
        "context": "green",
        "thinking": "bold yellow",
        "permission": "bold magenta",
    }

    # 模式颜色映射
    MODE_COLORS = {
        "Build": "bold cyan",
        "Chat": "bold green",
        "Plan": "bold yellow",
        "Review": "bold magenta",
        "Architect": "bold blue",
    }

    def __init__(self, console: Optional[Any] = None, compact: bool = False):
        """
        初始化状态栏

        Args:
            console: Rich Console 实例
            compact: 紧凑模式 (减少信息显示)
        """
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None
        self.compact = compact

    def render(self, ctx: StatusContext) -> str:
        """
        渲染状态栏

        Args:
            ctx: 状态上下文

        Returns:
            渲染后的字符串
        """
        if not HAS_RICH:
            return self._render_plain(ctx)

        return self._render_rich(ctx)

    def render_live(self, ctx: StatusContext) -> Any:
        """
        渲染 Rich renderable，用于 Live display

        Args:
            ctx: 状态上下文

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            return None
        return self._build_status_text(ctx)

    def _render_rich(self, ctx: StatusContext) -> str:
        """使用 Rich 渲染状态栏"""
        text = self._build_status_text(ctx)

        # 用 Panel 包裹
        import shutil
        width = shutil.get_terminal_size().columns

        panel = Panel(
            text,
            box=box.SIMPLE,
            border_style="dim",
            padding=(0, 1),
            width=width,
        )

        # 捕获为字符串
        with self.console.capture() as capture:
            self.console.print(panel)
        return capture.get()

    def _build_status_text(self, ctx: StatusContext) -> Text:
        """构建 Rich Text 状态内容"""
        parts = []

        # 分隔符
        sep = Text(" │ ", style=self.COLORS["separator"])

        # --- 模式 ---
        mode_color = self.MODE_COLORS.get(ctx.mode, "bold white")
        mode_icon = self._mode_icon(ctx.mode)
        parts.append(Text(f"{mode_icon} ", style=mode_color))
        parts.append(Text(ctx.mode, style=mode_color))

        # --- 模型 ---
        if ctx.model:
            parts.append(sep)
            parts.append(Text(f"{ctx.provider}:", style=self.COLORS["provider"]) if ctx.provider else Text(""))
            parts.append(Text(ctx.model, style=self.COLORS["model"]))

        # --- 项目目录 ---
        if ctx.project_dir and not self.compact:
            parts.append(sep)
            abbreviated = self._abbreviate_path(ctx.project_dir)
            parts.append(Text(abbreviated, style=self.COLORS["project_dir"]))

        # --- 上下文长度 ---
        if ctx.context_length > 0:
            parts.append(sep)
            parts.append(Text(f"{ctx.context_length} msgs", style=self.COLORS["context"]))

        # --- 思考深度 ---
        if ctx.thinking_depth:
            parts.append(sep)
            parts.append(Text(f"thinking:{ctx.thinking_depth}", style=self.COLORS["thinking"]))

        # --- Token 使用 ---
        if ctx.token_used > 0 or ctx.token_limit > 0:
            parts.append(sep)
            token_style = self._token_style(ctx.token_percent)
            token_text = self._format_tokens(ctx.token_used, ctx.token_limit)
            parts.append(Text(token_text, style=token_style))

        # --- Token 进度条 ---
        if ctx.token_limit > 0:
            bar = self._token_bar(ctx)
            parts.append(Text(" "))
            parts.append(bar)

        # --- 权限模式 ---
        if ctx.permission_mode:
            parts.append(sep)
            parts.append(Text(ctx.permission_mode, style=self.COLORS["permission"]))

        # --- 成本 ---
        if ctx.cost_usd > 0:
            parts.append(sep)
            parts.append(Text(f"${ctx.cost_usd:.4f}", style=self.COLORS["cost"]))

        # --- 延迟 ---
        if ctx.latency_ms > 0:
            parts.append(sep)
            latency_text = self._format_latency(ctx.latency_ms)
            parts.append(Text(latency_text, style=self.COLORS["latency"]))

        # --- 工具数 ---
        if ctx.tools_count > 0 and not self.compact:
            parts.append(sep)
            tools_text = f"{ctx.tools_count} tools" if ctx.tools_count != 1 else "1 tool"
            parts.append(Text(tools_text, style="dim"))

        # --- 工作流进度 ---
        if ctx.workflow_name and not self.compact:
            parts.append(sep)
            progress = f"{ctx.agents_completed}/{ctx.agent_count}" if ctx.agent_count > 0 else ctx.workflow_name
            parts.append(Text(progress, style="dim"))

        # --- 会话 ID ---
        if ctx.session_id and not self.compact:
            parts.append(sep)
            short_id = ctx.session_id[:8]
            parts.append(Text(f"#{short_id}", style="dim"))

        return Text.assemble(*parts) if parts else Text("")

    def _render_plain(self, ctx: StatusContext) -> str:
        """纯文本渲染"""
        parts = []

        mode_icon = self._mode_icon(ctx.mode)
        parts.append(f"{mode_icon} {ctx.mode}")

        if ctx.model:
            provider_part = f"{ctx.provider}:" if ctx.provider else ""
            parts.append(f"{provider_part}{ctx.model}")

        if ctx.project_dir and not self.compact:
            parts.append(self._abbreviate_path(ctx.project_dir))

        if ctx.context_length > 0:
            parts.append(f"{ctx.context_length} msgs")

        if ctx.thinking_depth:
            parts.append(f"thinking:{ctx.thinking_depth}")

        if ctx.token_used > 0 or ctx.token_limit > 0:
            parts.append(self._format_tokens(ctx.token_used, ctx.token_limit))

        if ctx.permission_mode:
            parts.append(ctx.permission_mode)

        if ctx.cost_usd > 0:
            parts.append(f"${ctx.cost_usd:.4f}")

        if ctx.latency_ms > 0:
            parts.append(self._format_latency(ctx.latency_ms))

        if ctx.tools_count > 0 and not self.compact:
            suffix = "" if ctx.tools_count == 1 else "s"
            parts.append(f"{ctx.tools_count} tool{suffix}")

        return " | ".join(parts)

    def _token_bar(self, ctx: StatusContext) -> Text:
        """构建 token 进度条"""
        bar_width = 10
        filled = max(1, int(ctx.token_percent / 100 * bar_width))
        empty = bar_width - filled

        style = self._token_style(ctx.token_percent)
        filled_style = Style(color=style)

        bar = Text()
        bar.append("▐", style=filled_style)
        bar.append("█" * filled, style=filled_style)
        bar.append("░" * empty, style="dim")
        bar.append("▌", style="dim")

        return bar

    def _token_style(self, percent: float) -> str:
        """根据 token 使用百分比返回颜色样式"""
        if percent > 90:
            return self.COLORS["token_critical"]
        elif percent > 70:
            return self.COLORS["token_warn"]
        return self.COLORS["token_ok"]

    def _format_tokens(self, used: int, limit: int) -> str:
        """格式化 token 数量"""
        if limit == 0:
            return f"{self._fmt_num(used)} tok"
        return f"{self._fmt_num(used)}/{self._fmt_num(limit)} tok"

    @staticmethod
    def _fmt_num(n: int) -> str:
        """格式化数字 (1.5k, 2.3M 等)"""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    @staticmethod
    def _format_latency(ms: float) -> str:
        """格式化延迟"""
        if ms < 1:
            return f"{ms * 1000:.0f}µs"
        if ms < 1000:
            return f"{ms:.0f}ms"
        return f"{ms / 1000:.1f}s"

    @staticmethod
    def _mode_icon(mode: str) -> str:
        """模式图标"""
        icons = {
            "Build": "⚒",        # ⚒
            "Chat": "\U0001F4AC",     # 💬
            "Plan": "\U0001F4CB",     # 📋
            "Review": "\U0001F50D",   # 🔍
            "Architect": "\U0001F3D7", # 🏗
        }
        return icons.get(mode, "◆")  # ◆ default

    @staticmethod
    def _abbreviate_path(path: str, max_segments: int = 2) -> str:
        """缩略路径，只保留最后 max_segments 段"""
        if not path:
            return ""
        parts = path.replace("\\", "/").split("/")
        parts = [p for p in parts if p]
        if len(parts) <= max_segments:
            return path
        return ".../" + "/".join(parts[-max_segments:])


class StatusDisplay:
    """
    状态栏显示管理器

    管理多个状态栏的显示和更新，支持 Live 刷新
    """

    def __init__(self, console: Optional[Any] = None):
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None
        self._status_bar = StatusBar(console=self.console)
        self._context = StatusContext()
        self._live = None

    @property
    def context(self) -> StatusContext:
        return self._context

    def update(self, **kwargs) -> None:
        """更新状态上下文"""
        for key, value in kwargs.items():
            if hasattr(self._context, key):
                setattr(self._context, key, value)

    def render(self) -> str:
        """渲染当前状态"""
        return self._status_bar.render(self._context)

    def render_live(self):
        """获取 Live renderable"""
        return self._status_bar.render_live(self._context)


# 全局实例
status_display = StatusDisplay()

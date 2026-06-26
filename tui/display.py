"""
GrassFlow 终端进度展示

使用 Rich 库展示执行进度和状态
"""

from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from enum import Enum

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TaskProgressColumn
    from rich.live import Live
    from rich.tree import Tree
    from rich.text import Text
    from rich.syntax import Syntax
    from rich.columns import Columns
    from rich import box
    from rich.markup import escape as _markup_escape
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from core.models import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
    HAS_MODELS = True
except ImportError:
    HAS_MODELS = False
    # Provide stub types so the module loads even without core.models
    from enum import Enum as _Enum
    from typing import Any as _Any
    class ExecutionStatus(str, _Enum):  # type: ignore[no-redef]
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"
    ExecutionRecord = None  # type: ignore[assignment,misc]
    AgentExecutionRecord = None  # type: ignore[assignment,misc]


class NotificationLevel(Enum):
    """通知级别"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class Display:
    """终端展示"""

    STATUS_COLORS = {
        "pending": "yellow",
        "running": "blue",
        "completed": "green",
        "failed": "red",
        "skipped": "dim",
    }

    def __init__(self, console: Optional[Any] = None):
        """
        初始化展示

        Args:
            console: Rich Console 实例
        """
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    def print_workflow_info(self, workflow_name: str, agents: List[str], edges: int) -> None:
        """
        打印工作流信息

        Args:
            workflow_name: 工作流名称
            agents: Agent 名称列表
            edges: 边数量
        """
        if not HAS_RICH:
            print(f"Workflow: {workflow_name}")
            print(f"Agents: {', '.join(agents)}")
            print(f"Edges: {edges}")
            return

        tree = Tree(f"[bold blue]Workflow: {workflow_name}[/bold blue]")
        tree.add(f"[green]Agents ({len(agents)}):[/green] {', '.join(agents)}")
        tree.add(f"[green]Edges:[/green] {edges}")
        self.console.print(tree)
        self.console.print()

    def print_execution_start(self, workflow_name: str) -> None:
        """
        打印执行开始信息

        Args:
            workflow_name: 工作流名称
        """
        if not HAS_RICH:
            print(f"Executing workflow: {workflow_name}")
            return

        self.console.print(f"[bold {self._theme_color('success', 'green')}]Executing workflow:[/bold {self._theme_color('success', 'green')}] {workflow_name}")
        self.console.print()

    def print_agent_status(self, agent_name: str, status: str, duration: Optional[int] = None) -> None:
        """
        打印 Agent 状态

        Args:
            agent_name: Agent 名称
            status: 状态
            duration: 耗时（毫秒）
        """
        if not HAS_RICH:
            duration_str = f" ({duration}ms)" if duration is not None else ""
            print(f"  {agent_name}: {status}{duration_str}")
            return

        color = self.STATUS_COLORS.get(status, "white")
        duration_str = f" ({duration}ms)" if duration is not None else ""

        self.console.print(f"  [{color}]{agent_name}: {status}{duration_str}[/{color}]")

    def print_execution_result(self, record: ExecutionRecord) -> None:
        """
        打印执行结果

        Args:
            record: 执行记录
        """
        if not HAS_MODELS:
            self.print_error("Cannot display execution result: core.models not available")
            return

        if not HAS_RICH:
            print(f"\nExecution Complete")
            print(f"Status: {record.status.value}")
            print(f"Duration: {record.total_duration_ms}ms")
            if record.agent_records:
                print("\nAgent Results:")
                for name, agent_record in record.agent_records.items():
                    print(f"  {name}: {agent_record.status.value}")
            return

        self.console.print()
        self.console.print("=" * 50)

        # 创建结果表格
        table = Table(title="Execution Result", show_header=True, header_style="bold magenta")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Workflow", record.workflow_name)
        table.add_row("Status", record.status.value)
        table.add_row("Duration", f"{record.total_duration_ms}ms" if record.total_duration_ms else "N/A")

        if record.error:
            table.add_row("Error", record.error)

        self.console.print(table)

        # 打印 Agent 结果
        if record.agent_records:
            self.console.print()
            agent_table = Table(title="Agent Results", show_header=True, header_style="bold magenta")
            agent_table.add_column("Agent", style="cyan")
            agent_table.add_column("Status", style="green")
            agent_table.add_column("Duration", style="yellow")
            agent_table.add_column("Error", style="red")

            for name, agent_record in record.agent_records.items():
                status_color = self.STATUS_COLORS.get(agent_record.status.value, "white")
                duration = f"{agent_record.duration_ms}ms" if agent_record.duration_ms else "N/A"
                error = agent_record.error or ""

                agent_table.add_row(
                    name,
                    f"[{status_color}]{agent_record.status.value}[/{status_color}]",
                    duration,
                    error,
                )

            self.console.print(agent_table)

    def print_error(self, error: str) -> None:
        """
        打印错误信息

        Args:
            error: 错误信息
        """
        if not HAS_RICH:
            print(f"Error: {error}")
            return

        self.console.print(f"[bold {self._theme_color('error', 'red')}]Error:[/bold {self._theme_color('error', 'red')}] {error}")

    def print_success(self, message: str) -> None:
        """
        打印成功信息

        Args:
            message: 成功信息
        """
        if not HAS_RICH:
            print(message)
            return

        self.console.print(f"[bold {self._theme_color('success', 'green')}]{message}[/bold {self._theme_color('success', 'green')}]")

    def print_info(self, message: str) -> None:
        """
        打印信息

        Args:
            message: 信息
        """
        if not HAS_RICH:
            print(message)
            return

        self.console.print(message)

    # ========================================================================
    # 主题辅助方法
    # ========================================================================

    def _theme_color(self, key: str, fallback: str) -> str:
        """从活动主题获取颜色，失败时回退到 fallback"""
        try:
            from tui.themes import get_active_theme
            return get_active_theme().get_color(key, fallback)
        except Exception:
            return fallback

    def _get_code_theme(self) -> str:
        """获取代码语法高亮主题"""
        try:
            from tui.themes import get_active_theme
            return get_active_theme().code_theme
        except Exception:
            return "monokai"

    # ========================================================================
    # 工具调用渲染
    # ========================================================================

    def render_tool_call(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        tool_emoji: str = "\U0001F527",
        indent: int = 2,
    ) -> None:
        """
        渲染工具调用信息

        以类似 Claude Code 的格式展示工具调用:
           read_file("path/to/file.py")

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            tool_emoji: 工具图标
            indent: 缩进空格数
        """
        if not HAS_RICH:
            self._print_tool_call_plain(tool_name, arguments, indent)
            return

        prefix = " " * indent

        # 构建参数显示
        args_display = ""
        if arguments:
            arg_parts = []
            for key, value in arguments.items():
                formatted = self._format_arg_value(value)
                arg_parts.append(f"{key}={formatted}")
            args_display = ", ".join(arg_parts)

        # 渲染工具调用行
        text = Text()
        text.append(f"{prefix}{tool_emoji} ", style="")
        text.append(tool_name, style="bold cyan")
        if args_display:
            text.append("(", style="dim")
            text.append(args_display, style="yellow")
            text.append(")", style="dim")
        else:
            text.append("()", style="dim")

        self.console.print(text)

    def render_tool_result(
        self,
        tool_name: str,
        result: Any = None,
        success: bool = True,
        duration_ms: Optional[float] = None,
        compact: bool = True,
        indent: int = 4,
    ) -> None:
        """
        渲染工具执行结果

        Args:
            tool_name: 工具名称
            result: 执行结果
            success: 是否成功
            duration_ms: 耗时 (毫秒)
            compact: 紧凑模式 (截断长输出)
            indent: 缩进空格数
        """
        if not HAS_RICH:
            self._print_tool_result_plain(tool_name, result, success, duration_ms)
            return

        prefix = " " * indent

        # 状态图标
        status_icon = "✅" if success else "❌"  # ✅ or ❌
        status_style = "green" if success else "red"

        # 耗时
        duration_str = ""
        if duration_ms is not None:
            if duration_ms < 1000:
                duration_str = f" [{duration_ms:.0f}ms]"
            else:
                duration_str = f" [{duration_ms / 1000:.1f}s]"

        text = Text()
        text.append(f"{prefix}{status_icon} ", style=status_style)
        text.append(tool_name, style="dim")
        text.append(duration_str, style="dim")

        self.console.print(text)

        # 渲染结果内容
        if result is not None:
            result_str = self._format_result(result)
            original_len = len(result_str)
            if compact and original_len > 500:
                result_str = result_str[:500] + f"\n{prefix}  ... [dim](truncated, {original_len} chars total)[/dim]"

            if "\n" in result_str or len(result_str) > 80:
                # 多行结果用 Panel 包裹
                panel = Panel(
                    Text(result_str, style=""),
                    border_style="dim",
                    box=box.SIMPLE,
                    padding=(0, 1),
                )
                self.console.print(Text(f"{prefix}  ", style="") + panel)
            else:
                self.console.print(f"{prefix}  {_markup_escape(result_str)}")

    def render_tool_call_live(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        tool_emoji: str = "\U0001F527",
    ) -> Any:
        """
        创建工具调用的 Live renderable (用于 Live 上下文)

        返回一个 renderable 对象，可以在 Live display 中更新

        Args:
            tool_name: 工具名称
            arguments: 参数
            tool_emoji: 图标

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            return self._format_tool_call_plain(tool_name, arguments)

        args_display = ""
        if arguments:
            arg_parts = []
            for key, value in arguments.items():
                formatted = self._format_arg_value(value)
                arg_parts.append(f"{key}={formatted}")
            args_display = ", ".join(arg_parts)

        text = Text()
        text.append(f"  {tool_emoji} ", style="")
        text.append(tool_name, style="bold cyan")
        if args_display:
            text.append("(", style="dim")
            text.append(args_display, style="yellow")
            text.append(")", style="dim")
        else:
            text.append("()", style="dim")
        return text

    # ========================================================================
    # 通知渲染
    # ========================================================================

    def render_notification(
        self,
        message: str,
        level: Union[NotificationLevel, str] = NotificationLevel.INFO,
        title: str = "",
        details: Optional[str] = None,
        dismissible: bool = False,
    ) -> None:
        """
        渲染通知消息

        支持多种通知级别，类似 IDE 的 toast 通知

        Args:
            message: 通知消息
            level: 通知级别
            title: 标题
            details: 详细信息 (可展开)
            dismissible: 是否可关闭
        """
        if not HAS_RICH:
            self._print_notification_plain(message, level, title, details)
            return

        if isinstance(level, str):
            level = NotificationLevel(level)

        # 级别配置
        level_config = {
            NotificationLevel.INFO: {
                "icon": "ℹ️",   # ℹ️
                "style": "blue",
                "border": "blue",
                "label": "INFO",
            },
            NotificationLevel.SUCCESS: {
                "icon": "✅",         # ✅
                "style": "green",
                "border": "green",
                "label": "SUCCESS",
            },
            NotificationLevel.WARNING: {
                "icon": "⚠️",   # ⚠️
                "style": "yellow",
                "border": "yellow",
                "label": "WARNING",
            },
            NotificationLevel.ERROR: {
                "icon": "❌",         # ❌
                "style": "red",
                "border": "red",
                "label": "ERROR",
            },
            NotificationLevel.DEBUG: {
                "icon": "\U0001F41B",     # 🐛
                "style": "dim",
                "border": "dim",
                "label": "DEBUG",
            },
        }

        config = level_config[level]
        rich_style = config["style"]

        # 构建内容
        content = Text()
        content.append(f"{config['icon']} ", style=rich_style)

        if title:
            content.append(f"{title}: ", style=f"bold {rich_style}")

        content.append(message, style=rich_style)

        if details:
            content.append("\n", style="")
            content.append(details, style="dim italic")

        if dismissible:
            content.append("\n[Enter to dismiss]", style="dim")

        # 用 Panel 包裹
        panel = Panel(
            content,
            border_style=config["border"],
            box=box.ROUNDED,
            padding=(0, 1),
        )

        self.console.print()
        self.console.print(panel)

    def render_banner(
        self,
        title: str,
        subtitle: str = "",
        version: str = "",
    ) -> None:
        """
        渲染横幅标题 (类似应用启动 banner)

        Args:
            title: 标题
            subtitle: 副标题
            version: 版本号
        """
        if not HAS_RICH:
            print(f"\n=== {title} ===\n")
            if subtitle:
                print(subtitle)
            if version:
                print(f"v{version}")
            return

        lines = []

        # 主标题
        title_text = Text()
        title_text.append(" " * 2, style="")
        title_text.append(title, style="bold green")
        if version:
            title_text.append(f"  v{version}", style="dim italic")
        lines.append(title_text)

        if subtitle:
            sub = Text()
            sub.append(" " * 2, style="")
            sub.append(subtitle, style="dim")
            lines.append(sub)

        if len(lines) > 1:
            parts = []
            for i, line in enumerate(lines):
                if i > 0:
                    parts.append(Text("\n"))
                parts.append(line)
            banner_content = Text.assemble(*parts)
        else:
            banner_content = lines[0]

        banner = Panel(
            banner_content,
            border_style=self._theme_color("success", "green"),
            box=box.DOUBLE,
        )

        self.console.print()
        self.console.print(banner)
        self.console.print()

    def render_divider(self, text: str = "", style: str = "dim") -> None:
        """
        渲染分隔线

        Args:
            text: 分隔线中间的文本
            style: 样式
        """
        if not HAS_RICH:
            if text:
                print(f"\n--- {text} ---\n")
            else:
                print("\n---\n")
            return

        if text:
            self.console.rule(f"[{self._theme_color('dim', style)}]{text}[/{self._theme_color('dim', style)}]")
        else:
            self.console.rule(style=style)

    def render_key_value(
        self,
        pairs: Dict[str, Any],
        title: str = "",
        indent: int = 0,
    ) -> None:
        """
        渲染键值对列表

        Args:
            pairs: 键值对字典
            title: 表格标题
            indent: 缩进
        """
        if not HAS_RICH:
            for key, value in pairs.items():
                print(f"  {key}: {value}")
            return

        prefix = " " * indent
        table = Table(
            show_header=False,
            box=box.SIMPLE,
            padding=(0, 2),
            show_edge=False,
        )

        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")

        for key, value in pairs.items():
            table.add_row(str(key), str(value))

        if title:
            self.console.print(f"{prefix}[bold]{title}[/bold]")
        self.console.print(Text(prefix) + table if prefix else table)

    # ========================================================================
    # 进度条渲染
    # ========================================================================

    def render_progress_bar(
        self,
        current: int,
        total: int,
        label: str = "",
        width: int = 40,
        show_percent: bool = True,
        show_count: bool = True,
    ) -> None:
        """
        渲染单行进度条

        Args:
            current: 当前进度
            total: 总数
            label: 标签
            width: 进度条宽度 (字符数)
            show_percent: 是否显示百分比
            show_count: 是否显示计数
        """
        if not HAS_RICH:
            self._print_progress_plain(current, total, label, width)
            return

        percent = min(current / max(total, 1), 1.0)
        filled = int(percent * width)
        empty = width - filled

        # 选择颜色
        if percent >= 1.0:
            bar_color = "green"
        elif percent > 0.7:
            bar_color = "yellow"
        elif percent > 0.3:
            bar_color = "cyan"
        else:
            bar_color = "blue"

        # 构建进度条
        bar = Text()
        bar.append("█" * filled, style=bar_color)
        bar.append("░" * empty, style="dim")

        # 构建完整行
        result = Text()

        if label:
            result.append(f"{label} ", style="dim")

        result.append("[", style="dim")
        result.append(bar)
        result.append("]", style="dim")

        if show_percent:
            result.append(f" {percent * 100:.0f}%", style=f"bold {bar_color}")

        if show_count:
            result.append(f" ({current}/{total})", style="dim")

        self.console.print(result)

    def render_multi_progress(
        self,
        items: List[Dict[str, Any]],
        title: str = "",
    ) -> Any:
        """
        渲染多行进度条 (用于并行 agent 执行)

        Args:
            items: [{"label": "agent1", "current": 5, "total": 10, "status": "running"}, ...]
            title: 标题

        Returns:
            Rich renderable 对象 (可用于 Live)
        """
        if not HAS_RICH:
            return self._print_multi_progress_plain(items, title)

        status_style = {
            "pending": "dim",
            "running": "cyan",
            "completed": "green",
            "failed": "red",
            "skipped": "dim italic",
        }

        status_icon = {
            "pending": "○",    # ○
            "running": "●",     # ●
            "completed": "✓",   # ✓
            "failed": "✗",      # ✗
            "skipped": "⊙",     # ⊙
        }

        result = Text()

        if title:
            result.append(f"{title}\n", style="bold")

        for item in items:
            label = item.get("label", "")
            current = item.get("current", 0)
            total = item.get("total", 1)
            status = item.get("status", "pending")
            extra = item.get("extra", "")

            style = status_style.get(status, "dim")
            icon = status_icon.get(status, "?")

            percent = min(current / max(total, 1), 1.0)
            width = 20
            filled = int(percent * width)
            empty = width - filled

            result.append(f"  {icon} ", style=style)
            result.append(f"{label:20s} ", style=style)

            if status == "running":
                progress_bar = "█" * filled + "░" * empty
                result.append(progress_bar, style=style)
                result.append(f" {current}/{total}", style="dim")
            elif status == "completed":
                result.append(f"Completed ({current}/{total})", style=style)
            elif status == "failed":
                result.append(f"Failed", style=style)
            else:
                result.append(f"Pending ({total} steps)", style=style)

            if extra:
                result.append(f"  {extra}", style="dim")

            result.append("\n")

        return result

    # ========================================================================
    # 代码/JSON 渲染
    # ========================================================================

    def render_code(
        self,
        code: str,
        language: str = "python",
        title: str = "",
        line_numbers: bool = True,
        indent: int = 0,
    ) -> None:
        """
        渲染代码块 (带语法高亮)

        Args:
            code: 代码文本
            language: 编程语言 (用于语法高亮)
            title: 标题
            line_numbers: 是否显示行号
            indent: 缩进
        """
        if not HAS_RICH:
            print(f"{' ' * indent}{code}")
            return

        syntax = Syntax(
            code,
            language,
            theme=self._get_code_theme(),
            line_numbers=line_numbers,
            background_color="default",
        )

        if title:
            panel = Panel(
                syntax,
                title=f"[bold]{title}[/bold]",
                border_style="dim",
                box=box.ROUNDED,
                padding=(1, 1),
            )
            self.console.print(Text(" " * indent) + panel if indent else panel)
        else:
            if indent:
                self.console.print(Text(" " * indent) + syntax)
            else:
                self.console.print(syntax)

    def render_json(
        self,
        data: Any,
        title: str = "",
        indent: int = 2,
    ) -> None:
        """
        渲染 JSON 数据 (带语法高亮)

        Args:
            data: 要渲染的数据 (dict/list/str)
            title: 标题
            indent: 缩进
        """
        import json

        if isinstance(data, (dict, list)):
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            json_str = str(data)

        self.render_code(json_str, language="json", title=title, line_numbers=False, indent=indent)

    # ========================================================================
    # 辅助方法
    # ========================================================================

    @staticmethod
    def _format_arg_value(value: Any) -> str:
        """格式化参数值用于显示"""
        if isinstance(value, str):
            if len(value) > 40:
                return f'"{value[:40]}..."'
            return f'"{value}"'
        elif isinstance(value, (list, tuple)) and len(str(value)) > 60:
            return f"[{len(value)} items]"
        elif isinstance(value, dict):
            return f"{{{len(value)} keys}}"
        elif value is None:
            return "null"
        return str(value)

    @staticmethod
    def _format_result(result: Any) -> str:
        """格式化结果用于显示"""
        if isinstance(result, str):
            return result
        elif isinstance(result, (dict, list)):
            import json
            try:
                return json.dumps(result, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(result)
        return str(result)

    def _print_tool_call_plain(self, tool_name: str, arguments: Optional[Dict[str, Any]], indent: int) -> None:
        """纯文本工具调用输出"""
        prefix = " " * indent
        if arguments:
            args_str = ", ".join(f"{k}={self._format_arg_value(v)}" for k, v in arguments.items())
            print(f"{prefix}{tool_name}({args_str})")
        else:
            print(f"{prefix}{tool_name}()")

    def _print_tool_result_plain(self, tool_name: str, result: Any, success: bool, duration_ms: Optional[float]) -> None:
        """纯文本工具结果输出"""
        status = "OK" if success else "FAIL"
        delay = f" ({duration_ms}ms)" if duration_ms else ""
        print(f"    {status} {tool_name}{delay}")
        if result is not None:
            print(f"      {self._format_result(result)[:200]}")

    def _format_tool_call_plain(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """格式化纯文本工具调用字符串"""
        if arguments:
            args_str = ", ".join(f"{k}={self._format_arg_value(v)}" for k, v in arguments.items())
            return f"  {tool_name}({args_str})"
        return f"  {tool_name}()"

    def _print_notification_plain(self, message: str, level, title: str, details: str) -> None:
        """纯文本通知输出"""
        level_str = level.value if isinstance(level, NotificationLevel) else str(level)
        title_part = f"{title}: " if title else ""
        print(f"\n[{level_str.upper()}] {title_part}{message}")
        if details:
            print(f"  {details}")

    def _print_progress_plain(self, current: int, total: int, label: str, width: int) -> None:
        """纯文本进度条"""
        percent = min(current / max(total, 1), 1.0)
        filled = int(percent * width)
        empty = width - filled
        bar = "█" * filled + "░" * empty
        print(f"\r{label} [{bar}] {percent * 100:.0f}% ({current}/{total})", end="", flush=True)

    def _print_multi_progress_plain(self, items: List[Dict[str, Any]], title: str) -> str:
        """纯文本多行进度"""
        lines = []
        if title:
            lines.append(title)
        for item in items:
            label = item.get("label", "")
            status = item.get("status", "pending")
            current = item.get("current", 0)
            total = item.get("total", 1)
            lines.append(f"  {status:10s} {label:20s} {current}/{total}")
        return "\n".join(lines)


class ProgressDisplay:
    """进度展示"""

    def __init__(self, console: Optional[Any] = None):
        """
        初始化进度展示

        Args:
            console: Rich Console 实例
        """
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    def create_progress(self) -> Optional[Any]:
        """
        创建进度条

        Returns:
            Progress 实例，如果 Rich 不可用返回 None
        """
        if not HAS_RICH:
            return None

        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        )

    def execute_with_progress(self, agents: List[str], callback: Any) -> Any:
        """
        带进度条执行

        Args:
            agents: Agent 名称列表
            callback: 回调函数，接收 progress 和 task_id 参数

        Returns:
            回调函数的返回值
        """
        if not HAS_RICH:
            return callback(None, None)

        progress = self.create_progress()

        with progress:
            task_id = progress.add_task("Executing agents...", total=len(agents))
            return callback(progress, task_id)


# 全局展示实例
def create_display(console: Optional[Any] = None, **kwargs) -> Display:
    """创建独立的 Display 实例

    Args:
        console: Rich Console 实例，None 则创建默认 Console
        **kwargs: 传递给 Console() 的额外参数

    Returns:
        新的 Display 实例
    """
    if HAS_RICH and console is None:
        console = Console(**kwargs)
    return Display(console=console)


def _create_default_console() -> Any:
    """创建默认 Console，尝试应用主题"""
    if not HAS_RICH:
        return None
    try:
        from tui.themes import get_active_theme
        from rich.theme import Theme
        theme = get_active_theme()
        rich_theme = Theme(styles=theme.get_rich_style().to_rich_theme())
        return Console(theme=rich_theme)
    except Exception:
        return Console()


def _default_display_factory() -> Display:
    return Display(console=_create_default_console())


_default_display = _default_display_factory()


def get_display() -> Display:
    """获取全局 Display 单例"""
    return _default_display


# 兼容旧代码的模块级名称
display = _default_display
progress_display = ProgressDisplay(console=_create_default_console() if HAS_RICH else None)

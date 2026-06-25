"""
GrassFlow 终端进度展示

使用 Rich 库展示执行进度和状态
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
    from rich.live import Live
    from rich.tree import Tree
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from core.models import ExecutionRecord, AgentExecutionRecord, ExecutionStatus


class Display:
    """终端展示"""

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

        self.console.print(f"[bold green]Executing workflow:[/bold green] {workflow_name}")
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
            duration_str = f" ({duration}ms)" if duration else ""
            print(f"  {agent_name}: {status}{duration_str}")
            return

        status_colors = {
            "pending": "yellow",
            "running": "blue",
            "completed": "green",
            "failed": "red",
            "skipped": "dim",
        }

        color = status_colors.get(status, "white")
        duration_str = f" ({duration}ms)" if duration else ""

        self.console.print(f"  [{color}]{agent_name}: {status}{duration_str}[/{color}]")

    def print_execution_result(self, record: ExecutionRecord) -> None:
        """
        打印执行结果

        Args:
            record: 执行记录
        """
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
                status_color = "green" if agent_record.status == ExecutionStatus.COMPLETED else "red"
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

        self.console.print(f"[bold red]Error:[/bold red] {error}")

    def print_success(self, message: str) -> None:
        """
        打印成功信息

        Args:
            message: 成功信息
        """
        if not HAS_RICH:
            print(message)
            return

        self.console.print(f"[bold green]{message}[/bold green]")

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
display = Display()
progress_display = ProgressDisplay()

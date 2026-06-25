"""
GrassFlow REPL 主循环

参考 opencode TUI 实现，提供交互式命令行界面：
- 输入处理（用户消息、命令、中断）
- 消息渲染（Markdown、代码块）
- 中断处理（Ctrl+C）
- 命令历史
- 内置命令（/help, /run, /list, /exit 等）
"""

import asyncio
import signal
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.theme import Theme
    from rich.live import Live
    from rich.spinner import Spinner
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from tui.display import Display


# ==================== 消息类型 ====================

class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"


class Message:
    """消息"""

    def __init__(
        self,
        role: MessageRole,
        content: str,
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now()
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return f"Message(role={self.role.value}, content={self.content[:50]}...)"


# ==================== 命令处理 ====================

class CommandResult:
    """命令执行结果"""

    def __init__(
        self,
        success: bool = True,
        message: str = "",
        should_exit: bool = False,
        data: Optional[Any] = None,
    ):
        self.success = success
        self.message = message
        self.should_exit = should_exit
        self.data = data


class CommandHandler:
    """
    内置命令处理器

    参考 opencode 的命令系统，支持 slash 命令：
    - /help - 显示帮助
    - /run <file> - 执行工作流
    - /list - 列出工作流
    - /history - 执行历史
    - /clear - 清屏
    - /exit, /quit, /q - 退出
    """

    def __init__(self, console: Optional[Any] = None):
        self.console = console or Console() if HAS_RICH else None
        self.commands: Dict[str, Tuple[Callable, str]] = {}
        self._register_builtin_commands()

    def _register_builtin_commands(self) -> None:
        """注册内置命令"""
        self.register("help", self._cmd_help, "显示帮助信息")
        self.register("h", self._cmd_help, "显示帮助信息（别名）")
        self.register("run", self._cmd_run, "执行工作流文件")
        self.register("list", self._cmd_list, "列出已保存的工作流")
        self.register("ls", self._cmd_list, "列出已保存的工作流（别名）")
        self.register("history", self._cmd_history, "查看执行历史")
        self.register("clear", self._cmd_clear, "清屏")
        self.register("cls", self._cmd_clear, "清屏（别名）")
        self.register("exit", self._cmd_exit, "退出 REPL")
        self.register("quit", self._cmd_exit, "退出 REPL（别名）")
        self.register("q", self._cmd_exit, "退出 REPL（别名）")
        self.register("validate", self._cmd_validate, "验证工作流文件")
        self.register("templates", self._cmd_templates, "列出可用模板")

    def register(self, name: str, handler: Callable, description: str = "") -> None:
        """注册命令"""
        self.commands[name] = (handler, description)

    def parse(self, input_text: str) -> Optional[Tuple[str, List[str]]]:
        """
        解析命令

        Args:
            input_text: 用户输入

        Returns:
            (命令名, 参数列表) 或 None（不是命令）
        """
        trimmed = input_text.strip()
        if not trimmed.startswith("/"):
            return None

        parts = trimmed[1:].split()
        if not parts:
            return None

        return parts[0], parts[1:]

    def execute(self, input_text: str) -> CommandResult:
        """
        执行命令

        Args:
            input_text: 用户输入

        Returns:
            CommandResult
        """
        parsed = self.parse(input_text)
        if not parsed:
            return CommandResult(success=False, message="Not a command")

        cmd_name, args = parsed

        if cmd_name not in self.commands:
            return CommandResult(
                success=False,
                message=f"Unknown command: /{cmd_name}. Type /help for available commands.",
            )

        handler, _ = self.commands[cmd_name]
        try:
            return handler(args)
        except Exception as e:
            return CommandResult(success=False, message=f"Command error: {e}")

    def get_help_text(self) -> str:
        """获取帮助文本"""
        lines = ["Available commands:"]
        for name, (_, desc) in sorted(self.commands.items()):
            lines.append(f"  /{name:<15} {desc}")
        return "\n".join(lines)

    # ========== 内置命令实现 ==========

    def _cmd_help(self, args: List[str]) -> CommandResult:
        """显示帮助"""
        return CommandResult(success=True, message=self.get_help_text())

    def _cmd_run(self, args: List[str]) -> CommandResult:
        """执行工作流"""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /run <workflow_file>",
            )
        return CommandResult(
            success=True,
            message=f"Executing workflow: {args[0]}",
            data={"action": "run", "file": args[0]},
        )

    def _cmd_list(self, args: List[str]) -> CommandResult:
        """列出工作流"""
        try:
            from core.storage import workflow_storage
            workflows = workflow_storage.list()
            if not workflows:
                return CommandResult(success=True, message="No workflows found.")
            lines = ["Saved workflows:"]
            for wf in sorted(workflows):
                lines.append(f"  - {wf}")
            return CommandResult(success=True, message="\n".join(lines))
        except ImportError:
            return CommandResult(success=True, message="Storage module not available.")
        except Exception as e:
            return CommandResult(success=False, message=f"Error: {e}")

    def _cmd_history(self, args: List[str]) -> CommandResult:
        """执行历史"""
        try:
            from core.db import execution_db
            limit = int(args[0]) if args else 10
            executions = execution_db.list_executions(limit=limit)
            if not executions:
                return CommandResult(success=True, message="No execution history found.")
            lines = ["Execution history:"]
            for ex in executions:
                status = ex.get("status", "unknown")
                name = ex.get("workflow_name", "?")
                duration = ex.get("total_duration_ms")
                dur_str = f"{duration}ms" if duration else "N/A"
                lines.append(f"  [{ex.get('id', '?')}] {name} - {status} ({dur_str})")
            return CommandResult(success=True, message="\n".join(lines))
        except ImportError:
            return CommandResult(success=True, message="Database module not available.")
        except Exception as e:
            return CommandResult(success=False, message=f"Error: {e}")

    def _cmd_clear(self, args: List[str]) -> CommandResult:
        """清屏"""
        return CommandResult(success=True, message="", data={"action": "clear"})

    def _cmd_exit(self, args: List[str]) -> CommandResult:
        """退出"""
        return CommandResult(success=True, message="Goodbye!", should_exit=True)

    def _cmd_validate(self, args: List[str]) -> CommandResult:
        """验证工作流"""
        if not args:
            return CommandResult(success=False, message="Usage: /validate <workflow_file>")
        return CommandResult(
            success=True,
            message=f"Validating: {args[0]}",
            data={"action": "validate", "file": args[0]},
        )

    def _cmd_templates(self, args: List[str]) -> CommandResult:
        """列出模板"""
        try:
            from tui.templates import get_templates
            template_list = get_templates()
            if not template_list:
                return CommandResult(success=True, message="No templates available.")
            lines = ["Available templates:"]
            for t in template_list:
                lines.append(f"  - {t['name']}: {t['description']} ({t['agent_count']} agents)")
            return CommandResult(success=True, message="\n".join(lines))
        except ImportError:
            return CommandResult(success=True, message="Templates module not available.")
        except Exception as e:
            return CommandResult(success=False, message=f"Error: {e}")


# ==================== 消息渲染器 ====================

class MessageRenderer:
    """
    消息渲染器

    参考 opencode 的渲染系统，使用 Rich 渲染：
    - Markdown 内容
    - 代码块（语法高亮）
    - 面板和表格
    - 不同角色的消息样式
    """

    def __init__(self, console: Optional[Any] = None):
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    def render_message(self, message: Message) -> None:
        """
        渲染单条消息

        Args:
            message: 消息对象
        """
        if not HAS_RICH:
            self._render_plain(message)
            return

        if message.role == MessageRole.USER:
            self._render_user_message(message)
        elif message.role == MessageRole.ASSISTANT:
            self._render_assistant_message(message)
        elif message.role == MessageRole.SYSTEM:
            self._render_system_message(message)
        elif message.role == MessageRole.ERROR:
            self._render_error_message(message)

    def render_markdown(self, content: str) -> None:
        """
        渲染 Markdown 内容

        Args:
            content: Markdown 文本
        """
        if not HAS_RICH:
            print(content)
            return

        md = Markdown(content)
        self.console.print(md)

    def render_code(self, code: str, language: str = "python") -> None:
        """
        渲染代码块

        Args:
            code: 代码文本
            language: 编程语言
        """
        if not HAS_RICH:
            print(f"```{language}")
            print(code)
            print("```")
            return

        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        self.console.print(syntax)

    def render_table(self, title: str, columns: List[str], rows: List[List[str]]) -> None:
        """
        渲染表格

        Args:
            title: 表格标题
            columns: 列名列表
            rows: 行数据
        """
        if not HAS_RICH:
            print(f"\n{title}")
            print("-" * 40)
            for row in rows:
                print("  ".join(row))
            return

        table = Table(title=title, show_header=True, header_style="bold magenta")
        for col in columns:
            table.add_column(col, style="cyan")
        for row in rows:
            table.add_row(*row)
        self.console.print(table)

    def render_panel(self, content: str, title: str = "", style: str = "blue") -> None:
        """
        渲染面板

        Args:
            content: 面板内容
            title: 面板标题
            style: 边框样式
        """
        if not HAS_RICH:
            print(f"\n=== {title} ===")
            print(content)
            print("=" * (len(title) + 8))
            return

        panel = Panel(content, title=title, border_style=style)
        self.console.print(panel)

    def render_spinner(self, text: str = "Processing...") -> Any:
        """
        创建 spinner

        Args:
            text: 提示文本

        Returns:
            Spinner 对象或 None
        """
        if not HAS_RICH:
            return None
        return Spinner("dots", text=text)

    def _render_user_message(self, message: Message) -> None:
        """渲染用户消息"""
        self.console.print()
        self.console.print(
            Text(f"  You: ", style="bold cyan") + Text(message.content),
        )

    def _render_assistant_message(self, message: Message) -> None:
        """渲染助手消息"""
        self.console.print()
        # 尝试 Markdown 渲染
        content = message.content
        if self._looks_like_markdown(content):
            self.console.print(Text("  GrassFlow: ", style="bold green"), end="")
            self.console.print(Markdown(content))
        else:
            self.console.print(
                Text("  GrassFlow: ", style="bold green") + Text(content),
            )

    def _render_system_message(self, message: Message) -> None:
        """渲染系统消息"""
        self.console.print()
        self.console.print(Text(f"  [system] {message.content}", style="dim"))

    def _render_error_message(self, message: Message) -> None:
        """渲染错误消息"""
        self.console.print()
        self.console.print(Text(f"  Error: {message.content}", style="bold red"))

    def _render_plain(self, message: Message) -> None:
        """无 Rich 时的纯文本渲染"""
        prefix = {
            MessageRole.USER: "You",
            MessageRole.ASSISTANT: "GrassFlow",
            MessageRole.SYSTEM: "system",
            MessageRole.ERROR: "ERROR",
        }.get(message.role, "?")
        print(f"  [{prefix}] {message.content}")

    def _looks_like_markdown(self, text: str) -> bool:
        """简单判断文本是否像 Markdown"""
        indicators = [
            "```",    # 代码块
            "**",     # 粗体
            "#",      # 标题
            "- ",     # 列表
            "1. ",    # 有序列表
            "> ",     # 引用
            "[",      # 链接
            "|",      # 表格
        ]
        return any(indicator in text for indicator in indicators)


# ==================== 输入处理器 ====================

class InputHandler:
    """
    输入处理器

    参考 opencode 的 prompt 系统：
    - 命令历史（上下键浏览）
    - 中断处理（Ctrl+C）
    - 多行输入支持
    """

    def __init__(self, history_max_size: int = 100):
        self.history: List[str] = []
        self.history_index: int = -1
        self.history_max_size = history_max_size
        self._interrupted = False

    def add_to_history(self, text: str) -> None:
        """添加到历史记录"""
        if not text.strip():
            return
        # 避免重复
        if self.history and self.history[-1] == text:
            return
        self.history.append(text)
        # 限制大小
        if len(self.history) > self.history_max_size:
            self.history.pop(0)
        self.history_index = len(self.history)

    def get_previous(self) -> Optional[str]:
        """获取上一条历史"""
        if not self.history:
            return None
        if self.history_index > 0:
            self.history_index -= 1
        return self.history[self.history_index]

    def get_next(self) -> Optional[str]:
        """获取下一条历史"""
        if not self.history:
            return None
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            return self.history[self.history_index]
        else:
            self.history_index = len(self.history)
            return ""

    def reset_history_index(self) -> None:
        """重置历史索引"""
        self.history_index = len(self.history)

    def signal_interrupt(self) -> None:
        """标记中断"""
        self._interrupted = True

    def clear_interrupt(self) -> None:
        """清除中断标记"""
        self._interrupted = False

    @property
    def is_interrupted(self) -> bool:
        return self._interrupted


# ==================== REPL 主循环 ====================

class REPL:
    """
    GrassFlow REPL 主循环

    参考 opencode TUI 的 app.tsx 和 prompt/index.tsx：
    - 主循环处理输入 -> 解析 -> 执行 -> 渲染
    - 支持命令和普通消息
    - 中断处理（Ctrl+C 优雅退出）
    - 消息历史和上下文

    使用方式：
        repl = REPL()
        repl.run()
    """

    def __init__(
        self,
        console: Optional[Any] = None,
        on_message: Optional[Callable[[str], Optional[str]]] = None,
    ):
        """
        初始化 REPL

        Args:
            console: Rich Console 实例
            on_message: 消息回调函数，接收用户输入，返回响应
        """
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

        self.display = Display(self.console)
        self.renderer = MessageRenderer(self.console)
        self.command_handler = CommandHandler(self.console)
        self.input_handler = InputHandler()

        self.messages: List[Message] = []
        self.on_message = on_message
        self._running = False
        self._original_sigint = None

    def _get_prompt_text(self) -> str:
        """获取提示符文本"""
        return ">>> "

    def _print_banner(self) -> None:
        """打印启动横幅"""
        if not HAS_RICH:
            print("=" * 50)
            print("GrassFlow REPL v0.1.0")
            print("Type /help for available commands")
            print("Type /exit or Ctrl+C to exit")
            print("=" * 50)
            return

        banner = """[bold green]
  ____               _     _____ _
 / ___|_ __ __ _  ___| | __|  ___| | _____      __
| |  _| '__/ _` |/ __| |/ /| |_  | |/ _ \\ \\ /\\ / /
| |_| | | | (_| | (__|   < |  _| | | (_) \\ V  V /
 \\____|_|  \\__,_|\\___|_|\\_\\|_|   |_|\\___/ \\_/\\_/
[/bold green]"""
        self.console.print(banner)
        self.console.print()
        self.console.print(
            Text("  GrassFlow REPL ", style="bold blue")
            + Text("v0.1.0", style="dim")
        )
        self.console.print(
            Text("  Type ", style="dim")
            + Text("/help", style="bold cyan")
            + Text(" for available commands", style="dim")
        )
        self.console.print(
            Text("  Type ", style="dim")
            + Text("/exit", style="bold cyan")
            + Text(" or ", style="dim")
            + Text("Ctrl+C", style="bold yellow")
            + Text(" to exit", style="dim")
        )
        self.console.print()

    def _setup_signal_handlers(self) -> None:
        """
        设置信号处理器

        参考 opencode 的 exit 系统：
        - 第一次 Ctrl+C：中断当前操作，显示提示
        - 连续 Ctrl+C：退出 REPL
        """
        if sys.platform == "win32":
            # Windows: 使用 KeyboardInterrupt 异常
            return

        self._original_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _restore_signal_handlers(self) -> None:
        """恢复信号处理器"""
        if sys.platform == "win32":
            return
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        """
        处理 SIGINT 信号

        参考 opencode 的 interrupt 计数机制：
        - 设置中断标记
        - 让主循环处理具体行为
        """
        self.input_handler.signal_interrupt()
        # 打印换行，避免 ^C 显示混乱
        if self.console:
            self.console.print()
        else:
            print()

    def _read_input(self) -> Optional[str]:
        """
        读取用户输入

        Returns:
            用户输入文本，或 None（中断/退出）
        """
        self.input_handler.clear_interrupt()

        try:
            prompt = self._get_prompt_text()
            if HAS_RICH:
                text = self.console.input(
                    Text(prompt, style="bold cyan")
                )
            else:
                text = input(prompt)
            return text

        except KeyboardInterrupt:
            # Windows 环境下的 Ctrl+C
            self.input_handler.signal_interrupt()
            return None
        except EOFError:
            return None

    def _process_input(self, text: str) -> bool:
        """
        处理用户输入

        Args:
            text: 用户输入

        Returns:
            是否应该退出
        """
        trimmed = text.strip()

        # 空输入
        if not trimmed:
            return False

        # 添加到历史
        self.input_handler.add_to_history(trimmed)

        # 检查是否是命令
        if trimmed.startswith("/"):
            return self._handle_command(trimmed)

        # 处理普通消息
        self._handle_message(trimmed)
        return False

    def _handle_command(self, text: str) -> bool:
        """
        处理命令

        Args:
            text: 命令文本

        Returns:
            是否应该退出
        """
        result = self.command_handler.execute(text)

        # 特殊动作处理
        if result.data and isinstance(result.data, dict):
            action = result.data.get("action")

            if action == "clear":
                self._clear_screen()
                return False

            if action == "run":
                self._execute_workflow(result.data.get("file", ""))
                return False

            if action == "validate":
                self._validate_workflow(result.data.get("file", ""))
                return False

        # 显示命令结果
        if result.message:
            if result.success:
                self.renderer.render_panel(result.message, title="Command", style="green")
            else:
                self.renderer.render_message(
                    Message(MessageRole.ERROR, result.message)
                )

        return result.should_exit

    def _handle_message(self, text: str) -> None:
        """
        处理普通消息

        Args:
            text: 用户消息
        """
        # 记录用户消息
        user_msg = Message(MessageRole.USER, text)
        self.messages.append(user_msg)
        self.renderer.render_message(user_msg)

        # 如果有回调函数，调用它
        if self.on_message:
            try:
                response = self.on_message(text)
                if response:
                    assistant_msg = Message(MessageRole.ASSISTANT, response)
                    self.messages.append(assistant_msg)
                    self.renderer.render_message(assistant_msg)
            except Exception as e:
                error_msg = Message(MessageRole.ERROR, str(e))
                self.messages.append(error_msg)
                self.renderer.render_message(error_msg)
        else:
            # 默认回显模式（用于测试）
            system_msg = Message(
                MessageRole.SYSTEM,
                "REPL in echo mode. Set on_message callback for actual processing.",
            )
            self.messages.append(system_msg)
            self.renderer.render_message(system_msg)

    def _execute_workflow(self, filepath: str) -> None:
        """执行工作流"""
        try:
            from tui.dsl_parser import parse_file
            from core.models import Workflow
            from core.scheduler import Scheduler
            from core.context import WorkflowContext
            from core.condition import ConditionAgent
            from core.llm_agent import LLMAgent
            import asyncio

            self.renderer.render_message(
                Message(MessageRole.SYSTEM, f"Loading workflow: {filepath}")
            )

            workflow = parse_file(filepath)

            # 创建 Agent 实例
            agents = {}
            for agent_config in workflow.agents:
                if agent_config.type.value == "condition":
                    rules = getattr(agent_config, "rules", [])
                    agent = ConditionAgent(name=agent_config.name, rules=rules)
                else:
                    agent = LLMAgent(
                        name=agent_config.name,
                        model=agent_config.model,
                        prompt=agent_config.prompt,
                        input_schema=agent_config.input_schema,
                        output_schema=agent_config.output_schema,
                    )
                agents[agent_config.name] = agent

            # 执行
            scheduler = Scheduler(workflow, agents)
            context = WorkflowContext()

            self.renderer.render_message(
                Message(MessageRole.SYSTEM, f"Executing workflow: {workflow.name}")
            )

            result = asyncio.run(scheduler.run(context))

            # 显示结果
            self.display.print_execution_result(result)

            if result.error:
                self.renderer.render_message(
                    Message(MessageRole.ERROR, result.error)
                )
            else:
                self.renderer.render_message(
                    Message(MessageRole.SYSTEM, "Workflow completed successfully!")
                )

        except ImportError as e:
            self.renderer.render_message(
                Message(MessageRole.ERROR, f"Missing module: {e}")
            )
        except Exception as e:
            self.renderer.render_message(
                Message(MessageRole.ERROR, f"Execution failed: {e}")
            )

    def _validate_workflow(self, filepath: str) -> None:
        """验证工作流"""
        try:
            from tui.dsl_parser import parse_file
            from core.dag import DAG, DAGError

            self.renderer.render_message(
                Message(MessageRole.SYSTEM, f"Validating: {filepath}")
            )

            workflow = parse_file(filepath)

            self.renderer.render_message(
                Message(MessageRole.SYSTEM, f"Workflow: {workflow.name}")
            )
            self.renderer.render_message(
                Message(MessageRole.SYSTEM, f"Agents: {len(workflow.agents)}")
            )
            self.renderer.render_message(
                Message(MessageRole.SYSTEM, f"Edges: {len(workflow.edges)}")
            )

            # 验证 DAG
            dag = DAG(workflow)
            order = dag.topological_sort()
            self.renderer.render_message(
                Message(
                    MessageRole.SYSTEM,
                    f"DAG valid. Topological order: {' -> '.join(order)}",
                )
            )

        except Exception as e:
            self.renderer.render_message(
                Message(MessageRole.ERROR, f"Validation failed: {e}")
            )

    def _clear_screen(self) -> None:
        """清屏"""
        if self.console:
            self.console.clear()
        else:
            import os
            os.system("cls" if sys.platform == "win32" else "clear")

    def _handle_interrupt(self) -> bool:
        """
        处理中断

        参考 opencode 的 interrupt 机制：
        - 第一次 Ctrl+C：显示提示
        - 第二次 Ctrl+C：退出

        Returns:
            是否应该退出
        """
        if self.input_handler.is_interrupted:
            self.input_handler.clear_interrupt()
            if HAS_RICH:
                self.console.print(
                    Text("  Press Ctrl+C again to exit, or type /exit", style="dim yellow")
                )
            else:
                print("  Press Ctrl+C again to exit, or type /exit")

            # 等待第二次中断
            try:
                if HAS_RICH:
                    self.console.input(Text("  >>> ", style="yellow"))
                else:
                    input("  >>> ")
                return False
            except KeyboardInterrupt:
                return True
            except (EOFError, Exception):
                return True
        return False

    def run(self) -> None:
        """
        运行 REPL 主循环

        这是参考 opencode app.tsx 的 run 函数实现的主循环：
        1. 初始化
        2. 显示横幅
        3. 进入输入循环
        4. 处理输入 -> 渲染
        5. 清理退出
        """
        self._setup_signal_handlers()

        try:
            self._print_banner()
            self._running = True

            while self._running:
                # 读取输入
                text = self._read_input()

                # 处理中断
                if text is None:
                    if self.input_handler.is_interrupted:
                        should_exit = self._handle_interrupt()
                        if should_exit:
                            break
                        continue
                    else:
                        # EOF
                        break

                # 处理输入
                should_exit = self._process_input(text)
                if should_exit:
                    break

        finally:
            self._running = False
            self._restore_signal_handlers()

            if HAS_RICH:
                self.console.print()
                self.console.print(Text("  Goodbye!", style="dim"))
            else:
                print("\n  Goodbye!")

    async def run_async(self) -> None:
        """
        异步运行 REPL

        用于需要异步处理的场景
        """
        self._setup_signal_handlers()

        try:
            self._print_banner()
            self._running = True

            while self._running:
                # 异步读取输入
                text = await asyncio.get_event_loop().run_in_executor(
                    None, self._read_input
                )

                # 处理中断
                if text is None:
                    if self.input_handler.is_interrupted:
                        should_exit = self._handle_interrupt()
                        if should_exit:
                            break
                        continue
                    else:
                        break

                # 处理输入
                should_exit = self._process_input(text)
                if should_exit:
                    break

        finally:
            self._running = False
            self._restore_signal_handlers()

            if HAS_RICH:
                self.console.print()
                self.console.print(Text("  Goodbye!", style="dim"))
            else:
                print("\n  Goodbye!")

    def stop(self) -> None:
        """停止 REPL"""
        self._running = False


# ==================== 便捷函数 ====================

def create_repl(
    on_message: Optional[Callable[[str], Optional[str]]] = None,
) -> REPL:
    """
    创建 REPL 实例

    Args:
        on_message: 消息处理回调

    Returns:
        REPL 实例
    """
    return REPL(on_message=on_message)


def run_repl(on_message: Optional[Callable[[str], Optional[str]]] = None) -> None:
    """
    运行 REPL

    Args:
        on_message: 消息处理回调
    """
    repl = create_repl(on_message)
    repl.run()


# ==================== 入口 ====================

if __name__ == "__main__":
    run_repl()

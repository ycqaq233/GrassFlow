"""
GrassFlow CLI 命令入口

参考 opencode CLI 命令系统和 hermes 子命令模块化架构，提供：
- grassflow run workflow.af - 执行工作流
- grassflow list - 列出已保存的工作流
- grassflow save workflow.af - 保存工作流
- grassflow history - 查看执行历史
- grassflow template - 工作流模板
- grassflow edit - 交互式编辑工作流
- grassflow init - 初始化项目
- grassflow doctor - 系统健康检查
- grassflow models - 列出可用模型
- grassflow plugin - 插件管理
- grassflow config - 配置管理（增强版）
- grassflow repl - 交互式 REPL
"""

import asyncio
import sys
import os
from pathlib import Path
from typing import Optional

import click

from core.models import Workflow, AgentInstance, Component, ModelConfig
from core.context import WorkflowContext
from core.scheduler import Scheduler
from core.condition import ConditionAgent, make_condition_component
from core.llm_agent import LLMAgent
from core.storage import workflow_storage, _dataclass_to_dict
from core.db import execution_db
from core.monitor import monitor
from core.tool_registry import register_builtin_tools, get_default_registry
from tui.dsl_parser import parse_file, parse_file_result
from tui.display import display, progress_display
from tui.error_handler import handle_cli_error, ErrorContext


def _get_default_model() -> str:
    """从配置中获取默认模型，而非硬编码"""
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        return config.llm.default_model
    except Exception:
        return "deepseek-v4-flash"


def _get_default_provider() -> str:
    """从配置中获取默认 provider"""
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        return config.llm.default_provider
    except Exception:
        return "deepseek"


def _resolve_model_for_provider(model_name: str, provider: str) -> str:
    """解析模型名称，如果当前 provider 中不存在该模型则回退到默认模型。"""
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        provider_config = config.provider.get(provider)
        if provider_config and provider_config.models:
            bare_name = model_name.split("/")[-1] if "/" in model_name else model_name
            if bare_name not in provider_config.models:
                fallback = config.llm.default_model
                display.print_info(
                    f"  Model '{bare_name}' not found in provider '{provider}', "
                    f"falling back to default: {fallback}"
                )
                return fallback
    except Exception:
        pass
    return model_name


def _setup_terminal_encoding():
    """Configure terminal encoding for UTF-8 (fixes Chinese character garbling)."""
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            os.system("chcp 65001 > nul 2>&1")
        except Exception:
            pass


@click.group()
@click.version_option(version="0.1.0")
def main():
    """GrassFlow - 可视化多Agent积木编排平台

    声明式 DSL 语法 + DAG 并行调度引擎
    """
    _setup_terminal_encoding()


# ==================== run 命令 ====================

@main.command()
@click.argument("workflow_file")
@click.option("--model", "-m", default=None, help="使用的模型（格式: provider/model，默认使用配置中的默认模型）")
@click.option("--provider", "-p", default=None, help="LLM 提供商（默认使用配置中的默认值）")
@click.option("--api-key", "-k", help="API key for LLM")
@click.option("--stream/--no-stream", default=True, help="启用/禁用流式输出（默认启用）")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--input", "-i", "workflow_input", multiple=True, help="工作流输入 (key=value)，可多次指定")
@click.option("--task", "-t", default=None, help="任务描述（等价于 --input task=...）")
def run(workflow_file: str, model: Optional[str], provider: Optional[str],
        api_key: Optional[str], stream: bool, verbose: bool, workflow_input: tuple, task: Optional[str]):
    """执行工作流"""
    workflow_path = Path(workflow_file)
    if not workflow_path.exists():
        if not workflow_path.suffix or workflow_path.suffix not in (".af", ".json", ".gf"):
            display.print_error(
                f"'{workflow_file}' is not a workflow file.\n"
                f"\n"
                f"  To run a workflow:  grassflow run workflow.af\n"
                f"  To ask a question:  grassflow ask \"your question here\"\n"
                f"\n"
                f"Use 'grassflow ask --help' for more information."
            )
            sys.exit(1)
        else:
            display.print_error(f"Workflow file not found: {workflow_file}")
            sys.exit(1)

    try:
        default_model = _get_default_model()
        effective_model = model or default_model
        effective_provider = provider or _get_default_provider()

        display.print_info(f"Loading workflow from {workflow_file}...")
        parse_result = parse_file_result(workflow_file)
        workflow = parse_result.workflows[0]
        components_dict = {c.name: c for c in parse_result.components}

        agent_names = [agent.name for agent in workflow.agents]
        display.print_workflow_info(workflow.name, agent_names, len(workflow.connections))

        if verbose:
            display.print_info(f"  Model: {effective_provider}/{effective_model}")
            display.print_info(f"  Streaming: {'on' if stream else 'off'}")

        # 注册内置工具
        tool_registry = get_default_registry()
        tool_count = register_builtin_tools(tool_registry)
        if tool_count > 0:
            display.print_info(f"  Registered {tool_count} builtin tools")

        # 创建 Agent 实例
        import copy
        agents = {}
        for agent_instance in workflow.agents:
            # 解析组件引用
            if agent_instance.component and agent_instance.component in components_dict:
                component = copy.deepcopy(components_dict[agent_instance.component])
                # 应用 overrides
                for k, v in agent_instance.overrides.items():
                    if k == "model" and isinstance(v, dict):
                        for mk, mv in v.items():
                            setattr(component.model, mk, mv)
                    elif k == "model":
                        component.model.default = v
                    elif hasattr(component, k):
                        setattr(component, k, v)
                # 解析模型
                if component.model.default:
                    component.model.default = _resolve_model_for_provider(
                        component.model.default, effective_provider
                    )
            else:
                raw_model = agent_instance.overrides.get("model", effective_model)
                resolved_model = _resolve_model_for_provider(raw_model, effective_provider)
                component = Component(
                    name=agent_instance.name,
                    system_prompt=agent_instance.inline_system_prompt or "",
                    model=ModelConfig(default=resolved_model),
                    ports=list(agent_instance.inline_ports),
                )

            # 判断是否是条件 Agent
            if "route" in agent_instance.name.lower() or "condition" in agent_instance.name.lower():
                rules = agent_instance.overrides.get("rules", [])
                agent = ConditionAgent(component, rules=rules)
            else:
                # 根据 component 权限过滤工具
                from core.tool_registry import create_filtered_registry
                if component.permission and (component.permission.allow or component.permission.deny):
                    agent_registry = create_filtered_registry(tool_registry, component.permission)
                else:
                    agent_registry = tool_registry
                agent = LLMAgent(component=component, tool_registry=agent_registry)

                # 记录 MCP 声明（基础版：仅打印日志，不做实际连接）
                if component.mcp:
                    for mcp in component.mcp:
                        display.print_info(
                            f"  [MCP] {component.name} declares MCP server "
                            f"'{mcp.server_name}' with tools: {mcp.tools}"
                        )

            agents[agent_instance.name] = agent

        # 解析工作流输入
        parsed_input = {}
        for item in workflow_input:
            if "=" in item:
                key, value = item.split("=", 1)
                # 尝试解析 JSON 值
                try:
                    import json
                    parsed_input[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    parsed_input[key] = value

        # --task 选项：作为 task key 注入 workflow_input
        if task:
            parsed_input["task"] = task

        # 创建调度器
        scheduler = Scheduler(workflow, agents, workflow_input=parsed_input)

        # 执行工作流
        display.print_execution_start(workflow.name)
        context = WorkflowContext()
        result = asyncio.run(scheduler.run(context))

        # 保存执行记录
        execution_db.save_execution(result)

        # 显示结果
        display.print_execution_result(result)

        if result.error:
            display.print_error(result.error)
            sys.exit(1)
        else:
            display.print_success("Workflow execution completed successfully!")

    except Exception as e:
        handle_cli_error(e, context=ErrorContext(workflow_id=workflow_file))
        sys.exit(1)


# ==================== save 命令 ====================

@main.command()
@click.argument("workflow_file")
@click.option("--output", "-o", help="Output file path")
def save(workflow_file: str, output: Optional[str]):
    """保存工作流"""
    if not Path(workflow_file).exists():
        display.print_error(f"Workflow file not found: {workflow_file}")
        sys.exit(1)

    try:
        display.print_info(f"Loading workflow from {workflow_file}...")
        workflow = parse_file(workflow_file)

        if output:
            import json
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(_dataclass_to_dict(workflow), f, indent=2, ensure_ascii=False)
            display.print_success(f"Workflow saved to {output_path}")
        else:
            filepath = workflow_storage.save(workflow)
            display.print_success(f"Workflow saved to {filepath}")

    except Exception as e:
        handle_cli_error(e, context=ErrorContext(workflow_id=workflow_file))
        sys.exit(1)


# ==================== list 命令 ====================

@main.command()
def list():
    """列出已保存的工作流"""
    try:
        workflows = workflow_storage.list()

        if not workflows:
            display.print_info("No workflows found.")
            return

        display.print_info("Saved Workflows:")
        for workflow in sorted(workflows):
            display.print_info(f"  {workflow}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


# ==================== validate 命令 ====================

@main.command()
@click.argument("workflow_file")
def validate(workflow_file: str):
    """验证工作流文件"""
    if not Path(workflow_file).exists():
        display.print_error(f"Workflow file not found: {workflow_file}")
        sys.exit(1)

    try:
        display.print_info(f"Validating {workflow_file}...")
        workflow = parse_file(workflow_file)

        display.print_success(f"Workflow: {workflow.name}")
        display.print_info(f"  Agents: {len(workflow.agents)}")
        display.print_info(f"  Connections: {len(workflow.connections)}")

        from core.dag import DAG, DAGError
        try:
            dag = DAG(workflow)
            display.print_success("  DAG: Valid (no cycles)")

            order = dag.topological_sort()
            display.print_info(f"  Topological order: {' -> '.join(order)}")

        except DAGError as e:
            handle_cli_error(e, context=ErrorContext(workflow_id=workflow_file))
            sys.exit(1)

        display.print_success("\nWorkflow is valid!")

    except Exception as e:
        handle_cli_error(e, context=ErrorContext(workflow_id=workflow_file))
        sys.exit(1)


# ==================== history 命令 ====================

@main.command()
@click.option("--workflow", "-w", help="Filter by workflow name")
@click.option("--limit", "-l", default=20, help="Number of records to show")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
def history(workflow: Optional[str], limit: int, verbose: bool):
    """查看执行历史"""
    try:
        executions = execution_db.list_executions(workflow_name=workflow, limit=limit)

        if not executions:
            display.print_info("No execution history found.")
            return

        try:
            from rich.table import Table
            from rich.console import Console

            console = Console()
            table = Table(title="Execution History", show_header=True, header_style="bold magenta")
            table.add_column("ID", style="cyan", justify="right")
            table.add_column("Workflow", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Duration", style="blue")
            table.add_column("Started At", style="dim")

            for exec_record in executions:
                status = exec_record["status"]
                status_color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
                duration = f"{exec_record['total_duration_ms']}ms" if exec_record["total_duration_ms"] else "N/A"
                started = exec_record["started_at"] or "N/A"

                table.add_row(
                    str(exec_record["id"]),
                    exec_record["workflow_name"],
                    f"[{status_color}]{status}[/{status_color}]",
                    duration,
                    started,
                )

            console.print(table)

        except ImportError:
            display.print_info("Execution History:")
            display.print_info("-" * 80)
            for exec_record in executions:
                status = exec_record["status"]
                duration = f"{exec_record['total_duration_ms']}ms" if exec_record["total_duration_ms"] else "N/A"
                display.print_info(f"  [{exec_record['id']}] {exec_record['workflow_name']} - {status} ({duration})")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


# ==================== inspect 命令 ====================

@main.command()
@click.argument("execution_id", type=int)
def inspect(execution_id: int):
    """查看执行详情"""
    try:
        record = execution_db.get_execution(execution_id)

        if not record:
            display.print_error(f"Execution {execution_id} not found.")
            sys.exit(1)

        report = monitor.monitor(record, execution_id=execution_id)
        display.print_execution_result(record)

        if report.issues:
            display.print_info("\nMonitor Issues:")
            for issue in report.issues:
                severity_color = "red" if issue.severity == "error" else "yellow" if issue.severity == "warning" else "blue"
                display.print_info(f"  [{severity_color}]{issue.severity}[/{severity_color}] [{issue.category}] {issue.message}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


# ==================== delete 命令 ====================

@main.command()
@click.argument("execution_id", type=int)
@click.option("--force", "-f", is_flag=True, help="Force delete without confirmation")
def delete(execution_id: int, force: bool):
    """删除执行记录"""
    try:
        record = execution_db.get_execution(execution_id)

        if not record:
            display.print_error(f"Execution {execution_id} not found.")
            sys.exit(1)

        if not force:
            click.confirm(f"Delete execution {execution_id} ({record.workflow_name})?", abort=True)

        execution_db.delete_execution(execution_id)
        display.print_success(f"Execution {execution_id} deleted.")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


# ==================== templates 命令 ====================

@main.command()
def templates():
    """列出可用的工作流模板"""
    try:
        from tui.templates import get_templates

        template_list = get_templates()

        if not template_list:
            display.print_info("No templates available.")
            return

        try:
            from rich.table import Table
            from rich.console import Console

            console = Console()
            table = Table(title="Workflow Templates", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Description", style="green")
            table.add_column("Agents", style="yellow")

            for template in template_list:
                table.add_row(
                    template["name"],
                    template["description"],
                    str(template["agent_count"]),
                )

            console.print(table)

        except ImportError:
            display.print_info("Workflow Templates:")
            for template in template_list:
                display.print_info(f"  {template['name']} - {template['description']} ({template['agent_count']} agents)")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@main.command()
@click.argument("template_name")
@click.option("--output", "-o", help="Output file path")
def create(template_name: str, output: Optional[str]):
    """从模板创建工作流"""
    try:
        from tui.templates import get_template, create_from_template

        template = get_template(template_name)

        if not template:
            display.print_error(f"Template '{template_name}' not found.")
            sys.exit(1)

        workflow = create_from_template(template)

        if output:
            output_path = Path(output)
        else:
            output_path = Path(f"{workflow.name}.af")

        dsl_content = _generate_dsl(workflow)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(dsl_content)

        display.print_success(f"Workflow created from template '{template_name}': {output_path}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


def _generate_dsl(workflow: Workflow) -> str:
    """
    生成 DSL 内容（v2 格式）
    """
    lines = []
    lines.append(f"# {workflow.name}")
    lines.append("")
    lines.append(f"workflow {workflow.name} {{")

    # Agent 声明
    for agent in workflow.agents:
        lines.append(f"  agent {agent.name} {{")
        model = agent.overrides.get("model")
        if model:
            lines.append(f'    model: "{model}"')
        if agent.inline_system_prompt:
            escaped = agent.inline_system_prompt.replace('"', '\\"')
            lines.append(f'    system_prompt: "{escaped}"')
        for port in agent.inline_ports:
            desc = f' "{port.description}"' if port.description else ""
            lines.append(f"    port {port.direction} {port.name}: {port.type}{desc}")
        lines.append("  }")
        lines.append("")

    # 连接
    if workflow.connections:
        lines.append("  # 连接")
        for conn in workflow.connections:
            source = conn.source_agent
            if conn.source_port:
                source = f"{source}.{conn.source_port}"

            if len(conn.target_agents) == 1:
                target = conn.target_agents[0]
                if conn.target_ports:
                    target = f"{target}.{conn.target_ports[0]}"
                lines.append(f"  {source} -> {target}")
            else:
                targets = []
                for i, tgt in enumerate(conn.target_agents):
                    port = conn.target_ports[i] if i < len(conn.target_ports) else None
                    if port:
                        targets.append(f"{tgt}.{port}")
                    else:
                        targets.append(tgt)
                lines.append(f"  {source} -> ({', '.join(targets)})")

    lines.append("}")
    lines.append("")

    return "\n".join(lines)


# ==================== monitor 命令 ====================

@main.command()
@click.argument("workflow_file")
@click.option("--model", "-m", default=None, help="使用的模型")
@click.option("--watch", "-w", is_flag=True, help="Watch execution in real-time")
@click.option("--input", "-i", "workflow_input", multiple=True, help="工作流输入 (key=value)，可多次指定")
@click.option("--task", "-t", default=None, help="任务描述（等价于 --input task=...）")
def monitor_cmd(workflow_file: str, model: Optional[str], watch: bool, workflow_input: tuple, task: Optional[str]):
    """执行工作流并实时监控"""
    if not Path(workflow_file).exists():
        display.print_error(f"Workflow file not found: {workflow_file}")
        sys.exit(1)

    try:
        effective_model = model or _get_default_model()
        effective_provider = _get_default_provider()

        display.print_info(f"Loading workflow from {workflow_file}...")
        parse_result = parse_file_result(workflow_file)
        workflow = parse_result.workflows[0]
        components_dict = {c.name: c for c in parse_result.components}

        agent_names = [agent.name for agent in workflow.agents]
        display.print_workflow_info(workflow.name, agent_names, len(workflow.connections))

        # 注册内置工具
        tool_registry = get_default_registry()
        tool_count = register_builtin_tools(tool_registry)
        if tool_count > 0:
            display.print_info(f"  Registered {tool_count} builtin tools")

        agents = {}
        import copy
        for agent_instance in workflow.agents:
            # 解析组件引用
            if agent_instance.component and agent_instance.component in components_dict:
                component = copy.deepcopy(components_dict[agent_instance.component])
                # 应用 overrides
                for k, v in agent_instance.overrides.items():
                    if k == "model" and isinstance(v, dict):
                        for mk, mv in v.items():
                            setattr(component.model, mk, mv)
                    elif k == "model":
                        component.model.default = v
                    elif hasattr(component, k):
                        setattr(component, k, v)
            else:
                raw_model = agent_instance.overrides.get("model", effective_model)
                resolved_model = _resolve_model_for_provider(raw_model, effective_provider)
                component = Component(
                    name=agent_instance.name,
                    system_prompt=agent_instance.inline_system_prompt or "",
                    model=ModelConfig(default=resolved_model),
                    ports=list(agent_instance.inline_ports),
                )

            if "route" in agent_instance.name.lower() or "condition" in agent_instance.name.lower():
                rules = agent_instance.overrides.get("rules", [])
                agent = ConditionAgent(component, rules=rules)
            else:
                # 根据 component 权限过滤工具
                from core.tool_registry import create_filtered_registry
                if component.permission and (component.permission.allow or component.permission.deny):
                    agent_registry = create_filtered_registry(tool_registry, component.permission)
                else:
                    agent_registry = tool_registry
                agent = LLMAgent(component=component, tool_registry=agent_registry)

                # 记录 MCP 声明（基础版：仅打印日志，不做实际连接）
                if component.mcp:
                    for mcp in component.mcp:
                        display.print_info(
                            f"  [MCP] {component.name} declares MCP server "
                            f"'{mcp.server_name}' with tools: {mcp.tools}"
                        )

            agents[agent_instance.name] = agent

        # 解析工作流输入
        parsed_input = {}
        for item in workflow_input:
            if "=" in item:
                key, value = item.split("=", 1)
                try:
                    import json
                    parsed_input[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    parsed_input[key] = value

        # --task 选项：作为 task key 注入 workflow_input
        if task:
            parsed_input["task"] = task

        scheduler = Scheduler(workflow, agents, workflow_input=parsed_input)

        display.print_execution_start(workflow.name)
        context = WorkflowContext()

        if watch:
            from tui.monitor_panel import execute_with_monitor
            result = execute_with_monitor(scheduler, context, workflow)
        else:
            result = asyncio.run(scheduler.run(context))

        execution_db.save_execution(result)

        report = monitor.monitor(result)
        display.print_execution_result(result)

        if report.issues:
            display.print_info("\nMonitor Report:")
            for issue in report.issues:
                severity_color = "red" if issue.severity == "error" else "yellow" if issue.severity == "warning" else "blue"
                display.print_info(f"  [{severity_color}]{issue.severity}[/{severity_color}] [{issue.category}] {issue.message}")

        if result.error:
            display.print_error(result.error)
            sys.exit(1)
        else:
            display.print_success("Workflow execution completed successfully!")

    except Exception as e:
        handle_cli_error(e, context=ErrorContext(workflow_id=workflow_file))
        sys.exit(1)


# ==================== edit 命令 ====================

@main.command()
@click.argument("workflow_file", required=False)
def edit(workflow_file: Optional[str]):
    """交互式编辑工作流"""
    try:
        from tui.editor import run_editor
        run_editor(workflow_file)
    except ImportError:
        display.print_error("textual is not installed. Run: pip install textual")
        sys.exit(1)
    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


# ==================== init 命令 ====================

@main.command()
@click.option("--output", "-o", default=None, help="生成 AGENTS.md 规则文件（例如 --output AGENTS.md）")
@click.option("--force", "-f", is_flag=True, help="强制覆盖已有文件")
def init(output: Optional[str], force: bool):
    """初始化 GrassFlow 项目"""
    from tui.commands.init_cmd import init_command
    init_command(output=output, force=force)


# ==================== doctor 命令 ====================

@main.command()
def doctor():
    """系统健康检查"""
    from tui.commands.doctor_cmd import doctor_command
    doctor_command()


# ==================== models 命令 ====================

@main.command()
@click.argument("provider", required=False)
def models(provider: Optional[str] = None):
    """列出可用的 AI 模型"""
    from tui.commands.model_cmd import model_command
    model_command(provider=provider)


# ==================== plugin 命令组 ====================

@main.group()
def plugin():
    """管理 GrassFlow 插件"""
    pass


@plugin.command(name="list")
def plugin_list_cmd():
    """列出已安装插件"""
    from tui.commands.plugin_cmd import plugin_list
    plugin_list()


@plugin.command(name="install")
@click.argument("name")
@click.option("--scope", "-s", type=click.Choice(["global", "project"]), default="global",
              help="安装范围（全局或当前项目）")
def plugin_install_cmd(name: str, scope: str):
    """安装插件"""
    from tui.commands.plugin_cmd import plugin_install
    plugin_install(name, scope=scope)


@plugin.command(name="uninstall")
@click.argument("name")
@click.option("--scope", "-s", type=click.Choice(["global", "project", "all"]), default="all",
              help="卸载范围")
@click.option("--force", "-f", is_flag=True, help="强制卸载，不提示确认")
def plugin_uninstall_cmd(name: str, scope: str, force: bool):
    """卸载插件"""
    from tui.commands.plugin_cmd import plugin_uninstall
    plugin_uninstall(name, scope=scope, force=force)


# ==================== config 命令组（增强版）====================

@main.group()
def config():
    """管理 GrassFlow 配置"""
    pass


@config.command(name="get")
@click.argument("key")
@click.option("--scope", "-s", type=click.Choice(["global", "project", "merged"]), default="merged",
              help="配置作用域")
def config_get(key: str, scope: str):
    """获取配置值"""
    try:
        from core.config import config_manager

        if scope == "global":
            config_obj = config_manager.load_global_config()
            value = _get_nested_attr(config_obj.model_dump(), key)
        elif scope == "project":
            project_config = config_manager.load_project_config()
            value = _get_nested_attr(project_config.model_dump(), key) if project_config else None
        else:
            value = config_manager.get(key)

        if value is None:
            display.print_info(f"{key}: (not set)")
        else:
            display.print_info(f"{key}: {value}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.option("--scope", "-s", type=click.Choice(["global", "project"]), default="global",
              help="配置作用域")
def config_set(key: str, value: str, scope: str):
    """设置配置值"""
    try:
        from core.config import config_manager
        import json

        try:
            parsed_value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            parsed_value = value

        config_manager.set(key, parsed_value, scope=scope)
        display.print_success(f"Set {key} = {parsed_value} ({scope})")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="list")
@click.option("--scope", "-s", type=click.Choice(["global", "project", "all"]), default="all",
              help="显示哪个作用域的配置")
@click.option("--json", "-j", "as_json", is_flag=True, help="以 JSON 格式输出")
def config_list_cmd(scope: str, as_json: bool):
    """列出所有配置"""
    try:
        from core.config import config_manager
        import json

        configs = config_manager.list_configs()

        if as_json:
            display.print_info(json.dumps(configs, indent=2, ensure_ascii=False))
            return

        try:
            from rich.table import Table
            from rich.console import Console
            from rich.tree import Tree

            console = Console()

            if scope in ("global", "all"):
                console.print("\n[bold cyan]Global Config[/bold cyan]")
                console.print(f"  Path: {configs['global']['path']}")
                console.print(f"  Exists: {configs['global']['exists']}")
                if configs['global']['config']:
                    tree = Tree("  ")
                    _add_config_tree(tree, configs['global']['config'])
                    console.print(tree)

            if scope in ("project", "all"):
                console.print("\n[bold cyan]Project Config[/bold cyan]")
                console.print(f"  Path: {configs['project']['path']}")
                console.print(f"  Exists: {configs['project']['exists']}")
                if configs['project']['config']:
                    tree = Tree("  ")
                    _add_config_tree(tree, configs['project']['config'])
                    console.print(tree)
                else:
                    console.print("  [dim]No project config[/dim]")

            if scope == "all":
                console.print("\n[bold cyan]Merged Config[/bold cyan]")
                tree = Tree("  ")
                _add_config_tree(tree, configs['merged'])
                console.print(tree)

        except ImportError:
            display.print_info("GrassFlow Configuration:")
            display.print_info("=" * 50)

            if scope in ("global", "all"):
                display.print_info(f"\nGlobal Config: {configs['global']['path']}")
                display.print_info(f"  Exists: {configs['global']['exists']}")
                if configs['global']['config']:
                    for key, value in configs['global']['config'].items():
                        display.print_info(f"  {key}: {value}")

            if scope in ("project", "all"):
                display.print_info(f"\nProject Config: {configs['project']['path']}")
                display.print_info(f"  Exists: {configs['project']['exists']}")
                if configs['project']['config']:
                    for key, value in configs['project']['config'].items():
                        display.print_info(f"  {key}: {value}")

            if scope == "all":
                display.print_info(f"\nMerged Config:")
                for key, value in configs['merged'].items():
                    display.print_info(f"  {key}: {value}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


def _add_config_tree(tree, config: dict, prefix: str = ""):
    """递归添加配置树节点"""
    for key, value in config.items():
        if isinstance(value, dict):
            branch = tree.add(f"[bold]{key}[/bold]")
            _add_config_tree(branch, value)
        else:
            tree.add(f"{key}: [green]{value}[/green]")


def _get_nested_attr(data: dict, key: str):
    """从嵌套字典中获取值"""
    keys = key.split(".")
    current = data
    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return None
    return current


@config.command(name="edit")
@click.option("--scope", "-s", type=click.Choice(["global", "project"]), default="global",
              help="编辑哪个作用域的配置")
def config_edit(scope: str):
    """在默认编辑器中打开配置文件"""
    try:
        from core.config import config_manager

        if scope == "global":
            config_file = config_manager.global_config_file
        else:
            config_file = config_manager.project_config_file

        config_file.parent.mkdir(parents=True, exist_ok=True)
        if not config_file.exists():
            config_manager.load_global_config() if scope == "global" else config_manager.load_project_config()

        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            if sys.platform == "win32":
                editor = "notepad"
            else:
                editor = "vi"

        display.print_info(f"Opening {config_file} with {editor}...")
        os.system(f'{editor} "{config_file}"')
        display.print_success(f"Configuration file edited: {config_file}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="validate")
def config_validate():
    """验证配置文件格式"""
    try:
        from core.config import config_manager
        from core.config import GrassFlowConfig
        import json

        issues = []
        configs_ok = True

        global_file = config_manager.global_config_file
        if global_file.exists():
            try:
                with open(global_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                GrassFlowConfig(**data)
                display.print_success(f"Global config: valid ({global_file})")
            except json.JSONDecodeError as e:
                issues.append(f"Global config: invalid JSON - {e}")
                configs_ok = False
            except Exception as e:
                issues.append(f"Global config: validation error - {e}")
                configs_ok = False
        else:
            display.print_info(f"Global config: not found ({global_file})")

        project_file = config_manager.project_config_file
        if project_file.exists():
            try:
                with open(project_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                GrassFlowConfig(**data)
                display.print_success(f"Project config: valid ({project_file})")
            except json.JSONDecodeError as e:
                issues.append(f"Project config: invalid JSON - {e}")
                configs_ok = False
            except Exception as e:
                issues.append(f"Project config: validation error - {e}")
                configs_ok = False
        else:
            display.print_info(f"Project config: not found ({project_file})")

        if issues:
            display.print_error("\nIssues found:")
            for issue in issues:
                display.print_error(f"  - {issue}")
            sys.exit(1)
        elif configs_ok:
            display.print_success("\nAll configurations are valid!")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="providers")
def config_providers():
    """列出配置的 providers"""
    try:
        from core.config import config_manager

        config = config_manager.load_config()
        providers = config.provider

        if not providers:
            display.print_info("No providers configured.")
            display.print_info("\nConfigure a provider:")
            display.print_info("  grassflow config api-key openai sk-xxx")
            display.print_info("  grassflow config api-key deepseek sk-xxx")
            return

        try:
            from rich.table import Table
            from rich.console import Console

            console = Console()
            table = Table(title="Configured Providers", show_header=True, header_style="bold magenta")
            table.add_column("Provider", style="cyan")
            table.add_column("API Key", style="green")
            table.add_column("Base URL", style="blue")
            table.add_column("Models", style="yellow")

            for name, prov in providers.items():
                has_key = "configured" if prov.options.apiKey else "[red]missing[/red]"
                base_url = prov.options.baseURL or "default"
                model_count = len(prov.models) if prov.models else 0
                models_str = f"{model_count} model(s)" if model_count > 0 else "0 (using defaults)"

                table.add_row(name, has_key, base_url, models_str)

            console.print(table)

            default_provider = config.llm.default_provider
            console.print(f"\n[dim]Default provider: {default_provider}[/dim]")

        except ImportError:
            display.print_info("Configured Providers:")
            display.print_info("-" * 40)
            for name, prov in providers.items():
                has_key = "configured" if prov.options.apiKey else "missing"
                display.print_info(f"  {name}: API Key {has_key}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="path")
def config_path():
    """显示配置文件路径"""
    try:
        from core.config import config_manager

        display.print_info(f"Global config: {config_manager.global_config_file}")
        display.print_info(f"Project config: {config_manager.project_config_file}")
        display.print_info(f"\nConfig directory: {config_manager.global_config_dir}")
        display.print_info(f"Workflows directory: {config_manager.global_config_dir / 'workflows'}")
        display.print_info(f"Plugins directory: {config_manager.global_config_dir / 'plugins'}")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="reset")
@click.option("--scope", "-s", type=click.Choice(["global", "project", "all"]), default="all",
              help="重置哪个作用域的配置")
@click.option("--force", "-f", is_flag=True, help="强制重置，不提示确认")
def config_reset(scope: str, force: bool):
    """重置配置为默认值"""
    try:
        from core.config import config_manager

        if not force:
            click.confirm(f"Reset {scope} config to defaults?", abort=True)

        config_manager.reset(scope=scope)
        display.print_success(f"Reset {scope} config to defaults.")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="api-key")
@click.argument("provider")
@click.argument("key")
@click.option("--scope", "-s", type=click.Choice(["global", "project"]), default="global",
              help="配置作用域")
def config_api_key(provider: str, key: str, scope: str):
    """设置 API Key"""
    try:
        from core.config import config_manager

        config_manager.set_api_key(provider, key, scope=scope)
        display.print_success(f"Set {provider} API key ({scope})")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


@config.command(name="show-key")
@click.argument("provider")
def config_show_key(provider: str):
    """显示 API Key（脱敏）"""
    try:
        from core.config import config_manager

        key = config_manager.get_api_key(provider)
        if key:
            if len(key) > 8:
                masked = key[:4] + "*" * (len(key) - 8) + key[-4:]
            else:
                masked = "***"
            display.print_info(f"{provider}: {masked}")
        else:
            display.print_info(f"{provider}: (not set)")

    except Exception as e:
        handle_cli_error(e)
        sys.exit(1)


# ==================== ask 命令 ====================

@main.command()
@click.argument("prompt")
@click.option("--model", "-m", default=None, help="使用的模型（覆盖配置默认值）")
@click.option("--provider", "-p", default=None, help="LLM 提供商（覆盖配置默认值）")
@click.option("--no-tools", is_flag=True, default=False, help="禁用工具调用")
def ask(prompt: str, model: Optional[str], provider: Optional[str], no_tools: bool):
    """执行单次 prompt 并输出结果"""
    from tui.run_session import run_prompt_sync

    exit_code = run_prompt_sync(
        prompt=prompt,
        model=model,
        provider=provider,
        no_tools=no_tools,
    )
    sys.exit(exit_code)


# ==================== repl 命令 ====================

@main.command()
@click.option("--model", "-m", default=None, help="使用的模型")
@click.option("--provider", "-p", default=None, help="LLM 提供商")
@click.option("--session", "-s", default=None, help="恢复指定会话 ID")
def repl(model: Optional[str], provider: Optional[str], session: Optional[str]):
    """启动交互式 REPL 会话"""
    from tui.repl import run_repl

    if session:
        display.print_info(f"Resuming session: {session}")
    if model:
        display.print_info(f"Using model: {model}")
    if provider:
        display.print_info(f"Using provider: {provider}")

    run_repl()


# ==================== 入口 ====================

if __name__ == "__main__":
    main()

"""
GrassFlow CLI 命令入口

支持命令：
- grassflow run workflow.af - 执行工作流
- grassflow list - 列出已保存的工作流
- grassflow save workflow.af - 保存工作流
- grassflow history - 查看执行历史
- grassflow template - 工作流模板
- grassflow edit - 交互式编辑工作流
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, List

import click

from core.models import Workflow
from core.context import WorkflowContext
from core.scheduler import Scheduler, SchedulerError
from core.condition import ConditionAgent
from core.llm_agent import LLMAgent, llm_agent_factory
from core.storage import workflow_storage
from core.db import execution_db
from core.monitor import monitor
from tui.dsl_parser import DSLParser, DSLError, parse_file
from tui.display import display, progress_display


@click.group()
@click.version_option(version="0.1.0")
def main():
    """GrassFlow - 可视化多Agent积木编排平台"""
    pass


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True))
@click.option("--model", "-m", default="gpt-4", help="Default LLM model")
@click.option("--api-key", "-k", help="API key for LLM")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def run(workflow_file: str, model: str, api_key: Optional[str], verbose: bool):
    """执行工作流"""
    try:
        # 解析工作流文件
        display.print_info(f"Loading workflow from {workflow_file}...")
        workflow = parse_file(workflow_file)

        # 打印工作流信息
        agent_names = [agent.name for agent in workflow.agents]
        display.print_workflow_info(workflow.name, agent_names, len(workflow.edges))

        # 创建 Agent 实例
        agents = {}
        for agent_config in workflow.agents:
            if agent_config.type.value == "condition":
                # 条件 Agent
                rules = getattr(agent_config, 'rules', [])
                agent = ConditionAgent(
                    name=agent_config.name,
                    rules=rules,
                )
            else:
                # LLM Agent
                agent = LLMAgent(
                    name=agent_config.name,
                    model=agent_config.model or model,
                    prompt=agent_config.prompt,
                    input_schema=agent_config.input_schema,
                    output_schema=agent_config.output_schema,
                )
            agents[agent_config.name] = agent

        # 创建调度器
        scheduler = Scheduler(workflow, agents)

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

    except DSLError as e:
        display.print_error(f"DSL Error: {e}")
        sys.exit(1)
    except SchedulerError as e:
        display.print_error(f"Scheduler Error: {e}")
        sys.exit(1)
    except Exception as e:
        display.print_error(f"Error: {e}")
        sys.exit(1)


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output file path")
def save(workflow_file: str, output: Optional[str]):
    """保存工作流"""
    try:
        # 解析工作流文件
        display.print_info(f"Loading workflow from {workflow_file}...")
        workflow = parse_file(workflow_file)

        # 保存工作流
        if output:
            # 如果指定了输出路径，直接保存
            import json
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(workflow.model_dump(), f, indent=2, ensure_ascii=False)
            display.print_success(f"Workflow saved to {output_path}")
        else:
            # 否则保存到默认位置
            filepath = workflow_storage.save(workflow)
            display.print_success(f"Workflow saved to {filepath}")

    except DSLError as e:
        display.print_error(f"DSL Error: {e}")
        sys.exit(1)
    except Exception as e:
        display.print_error(f"Error: {e}")
        sys.exit(1)


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
        display.print_error(f"Error: {e}")
        sys.exit(1)


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True))
def validate(workflow_file: str):
    """验证工作流文件"""
    try:
        click.echo(f"Validating {workflow_file}...")
        workflow = parse_file(workflow_file)

        click.echo(f"✓ Workflow: {workflow.name}")
        click.echo(f"✓ Agents: {len(workflow.agents)}")
        click.echo(f"✓ Edges: {len(workflow.edges)}")

        # 检查 DAG
        from core.dag import DAG, DAGError
        try:
            dag = DAG(workflow)
            click.echo("✓ DAG: Valid (no cycles)")

            # 显示拓扑排序
            order = dag.topological_sort()
            click.echo(f"✓ Topological order: {' -> '.join(order)}")

        except DAGError as e:
            click.echo(f"✗ DAG: {e}", err=True)
            sys.exit(1)

        click.echo("\nWorkflow is valid!")

    except DSLError as e:
        click.echo(f"✗ DSL Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


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

        # 创建表格
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
            # 如果没有 Rich，使用简单输出
            click.echo("Execution History:")
            click.echo("-" * 80)
            for exec_record in executions:
                status = exec_record["status"]
                duration = f"{exec_record['total_duration_ms']}ms" if exec_record["total_duration_ms"] else "N/A"
                click.echo(f"  [{exec_record['id']}] {exec_record['workflow_name']} - {status} ({duration})")

    except Exception as e:
        display.print_error(f"Error: {e}")
        sys.exit(1)


@main.command()
@click.argument("execution_id", type=int)
def inspect(execution_id: int):
    """查看执行详情"""
    try:
        record = execution_db.get_execution(execution_id)

        if not record:
            display.print_error(f"Execution {execution_id} not found.")
            sys.exit(1)

        # 生成监控报告
        report = monitor.monitor(record, execution_id=execution_id)

        # 显示结果
        display.print_execution_result(record)

        # 显示监控报告
        if report.issues:
            click.echo("\nMonitor Issues:")
            for issue in report.issues:
                severity_color = "red" if issue.severity == "error" else "yellow" if issue.severity == "warning" else "blue"
                click.echo(f"  [{severity_color}]{issue.severity}[/{severity_color}] [{issue.category}] {issue.message}")

    except Exception as e:
        display.print_error(f"Error: {e}")
        sys.exit(1)


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
        display.print_error(f"Error: {e}")
        sys.exit(1)


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
            click.echo("Workflow Templates:")
            for template in template_list:
                click.echo(f"  {template['name']} - {template['description']} ({template['agent_count']} agents)")

    except Exception as e:
        display.print_error(f"Error: {e}")
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

        # 创建工作流
        workflow = create_from_template(template)

        # 保存工作流
        if output:
            output_path = Path(output)
        else:
            output_path = Path(f"{workflow.name}.af")

        # 生成 DSL 内容
        dsl_content = generate_dsl(workflow)

        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(dsl_content)

        display.print_success(f"Workflow created from template '{template_name}': {output_path}")

    except Exception as e:
        display.print_error(f"Error: {e}")
        sys.exit(1)


def generate_dsl(workflow: Workflow) -> str:
    """生成 DSL 内容"""
    lines = []
    lines.append(f"# {workflow.name}")
    lines.append(f"# {workflow.description}")
    lines.append("")
    lines.append(f"workflow {workflow.name} {{")

    # Agent 声明
    for agent in workflow.agents:
        lines.append(f"  agent {agent.name} {{")
        if agent.type.value != "llm":
            lines.append(f'    type: "{agent.type.value}"')
        if agent.model:
            lines.append(f'    model: "{agent.model}"')
        if agent.prompt:
            lines.append(f'    prompt: "{agent.prompt}"')
        if agent.input_schema:
            lines.append(f'    input_schema: {agent.input_schema}')
        if agent.output_schema:
            lines.append(f'    output_schema: {agent.output_schema}')
        lines.append("  }")
        lines.append("")

    # 执行流
    lines.append("  # 执行流")

    # 简化：只显示顺序和并行关系
    edges = workflow.edges
    if edges:
        # 按源节点分组
        source_groups = {}
        for edge in edges:
            if edge.source not in source_groups:
                source_groups[edge.source] = []
            source_groups[edge.source].append(edge)

        # 生成执行流
        for source, edge_list in source_groups.items():
            targets = [e.target for e in edge_list]
            if len(targets) > 1:
                # 并行
                lines.append(f"  ({', '.join(targets)})")
            else:
                # 顺序
                lines.append(f"  {source} -> {targets[0]}")

    lines.append("}")

    return "\n".join(lines)


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True))
@click.option("--model", "-m", default="gpt-4", help="Default LLM model")
@click.option("--watch", "-w", is_flag=True, help="Watch execution in real-time")
def monitor_cmd(workflow_file: str, model: str, watch: bool):
    """执行工作流并实时监控"""
    try:
        # 解析工作流文件
        display.print_info(f"Loading workflow from {workflow_file}...")
        workflow = parse_file(workflow_file)

        # 打印工作流信息
        agent_names = [agent.name for agent in workflow.agents]
        display.print_workflow_info(workflow.name, agent_names, len(workflow.edges))

        # 创建 Agent 实例
        agents = {}
        for agent_config in workflow.agents:
            if agent_config.type.value == "condition":
                rules = getattr(agent_config, 'rules', [])
                agent = ConditionAgent(name=agent_config.name, rules=rules)
            else:
                agent = LLMAgent(
                    name=agent_config.name,
                    model=agent_config.model or model,
                    prompt=agent_config.prompt,
                    input_schema=agent_config.input_schema,
                    output_schema=agent_config.output_schema,
                )
            agents[agent_config.name] = agent

        # 创建调度器
        scheduler = Scheduler(workflow, agents)

        # 执行工作流
        display.print_execution_start(workflow.name)
        context = WorkflowContext()

        if watch:
            # 实时监控模式
            from tui.monitor_panel import execute_with_monitor
            result = execute_with_monitor(scheduler, context, workflow)
        else:
            result = asyncio.run(scheduler.run(context))

        # 保存执行记录
        execution_db.save_execution(result)

        # 生成监控报告
        report = monitor.monitor(result)

        # 显示结果
        display.print_execution_result(result)

        # 显示监控报告
        if report.issues:
            click.echo("\nMonitor Report:")
            for issue in report.issues:
                severity_color = "red" if issue.severity == "error" else "yellow" if issue.severity == "warning" else "blue"
                click.echo(f"  [{severity_color}]{issue.severity}[/{severity_color}] [{issue.category}] {issue.message}")

        if result.error:
            display.print_error(result.error)
            sys.exit(1)
        else:
            display.print_success("Workflow execution completed successfully!")

    except DSLError as e:
        display.print_error(f"DSL Error: {e}")
        sys.exit(1)
    except SchedulerError as e:
        display.print_error(f"Scheduler Error: {e}")
        sys.exit(1)
    except Exception as e:
        display.print_error(f"Error: {e}")
        sys.exit(1)


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
        display.print_error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
GrassFlow 工作流执行工具

允许 AI 主动执行 .gf 工作流文件，而非让用户手动 /run。
"""

import asyncio
import logging
from typing import Any, Dict
from .tool import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class RunWorkflowTool(Tool):
    """
    工作流执行工具 — 执行 GrassFlow .gf 工作流文件

    当用户要求编排/执行工作流时，使用此工具直接执行，
    而不是告诉用户手动运行 /run。
    """

    @property
    def id(self) -> str:
        return "run_workflow"

    @property
    def description(self) -> str:
        return (
            "Execute a GrassFlow .gf workflow file. "
            "Use this to run multi-agent workflows instead of doing everything yourself. "
            "Save the workflow DSL to a .gf file first with the write tool, then call this tool."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the .gf workflow file to execute",
                },
                "task": {
                    "type": "string",
                    "description": "Optional task description to pass to the workflow agents",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds (default: 300)",
                    "default": 300,
                },
            },
            "required": ["path"],
        }

    @staticmethod
    def _strip_ansi(text: str) -> str:
        """剥离 ANSI 转义码（含私有模式序列）"""
        import re
        return re.sub(r"\x1b\[\??[0-9;]*[A-Za-z]|\r", "", text)

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行工作流文件"""
        import os

        wf_path = params["path"]
        task = params.get("task")
        timeout = params.get("timeout", 300)

        # 解析路径
        if not os.path.isabs(wf_path):
            wf_path = os.path.join(ctx.cwd, wf_path)
        wf_path = os.path.abspath(wf_path)

        if not os.path.exists(wf_path):
            return ToolResult(
                output=f"Error: Workflow file not found: {wf_path}",
                title="Workflow Not Found",
            )

        try:
            from tui.workflow_runner import WorkflowRunner, REPLOutputHandler
            from core.tool_registry import get_default_registry

            # 创建执行器
            tool_registry = get_default_registry()
            # 使用 no-op output_fn：工具执行结果由 run_workflow 返回值传递，
            # 不需要 REPLOutputHandler 直接打印（避免 ANSI 码污染 REPL 输出）
            output_handler = REPLOutputHandler(output_fn=lambda _text: None)
            runner = WorkflowRunner(
                tool_registry=tool_registry,
                output_handler=output_handler,
            )

            # 执行工作流（带超时）
            result = await asyncio.wait_for(
                runner.run_workflow(
                    wf_path,
                    task=task,
                ),
                timeout=timeout,
            )

            # 格式化输出
            lines = []
            if result.success:
                lines.append(f"Workflow '{result.workflow_name}' completed successfully!")
                if result.execution_record:
                    for agent_name, record in result.execution_record.agent_records.items():
                        status = record.status.value if hasattr(record.status, "value") else str(record.status)
                        dur = f"{record.duration_ms}ms" if record.duration_ms else "N/A"
                        lines.append(f"  [{status}] {agent_name} ({dur})")
                        if record.output_data:
                            summary = self._strip_ansi(str(record.output_data))
                            if len(summary) > 500:
                                summary = summary[:500] + "..."
                            lines.append(f"    -> {summary}")
                total_dur = f"{result.duration_ms}ms" if result.duration_ms else "N/A"
                lines.append(f"Total duration: {total_dur}")
            else:
                lines.append(f"Workflow '{result.workflow_name}' failed: {result.error}")

            return ToolResult(
                output="\n".join(lines),
                title=f"Workflow: {result.workflow_name}",
                metadata={
                    "workflow_name": result.workflow_name,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                },
            )

        except asyncio.TimeoutError:
            return ToolResult(
                output=f"Error: Workflow execution timed out after {timeout}s",
                title="Workflow Timeout",
            )
        except Exception as e:
            logger.error("Workflow execution failed: %s", e, exc_info=True)
            return ToolResult(
                output=f"Error executing workflow: {e}",
                title="Workflow Error",
            )

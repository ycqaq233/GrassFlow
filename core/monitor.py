"""
GrassFlow 监控 Agent

工作流执行完毕后检查结果：
- Schema 校验
- 质量检查
- 耗时统计
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus


@dataclass
class MonitorIssue:
    """监控问题"""
    severity: str  # "warning", "error", "info"
    category: str  # "schema", "quality", "performance", "general"
    agent_name: Optional[str]
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class MonitorReport:
    """监控报告"""
    workflow_name: str
    execution_id: Optional[int]
    timestamp: datetime = field(default_factory=datetime.now)
    issues: List[MonitorIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        """是否有错误"""
        return any(issue.severity == "error" for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """是否有警告"""
        return any(issue.severity == "warning" for issue in self.issues)

    @property
    def error_count(self) -> int:
        """错误数量"""
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        """警告数量"""
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def add_issue(self, severity: str, category: str, agent_name: Optional[str], message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """添加问题"""
        self.issues.append(MonitorIssue(
            severity=severity,
            category=category,
            agent_name=agent_name,
            message=message,
            details=details,
        ))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "workflow_name": self.workflow_name,
            "execution_id": self.execution_id,
            "timestamp": self.timestamp.isoformat(),
            "issues": [
                {
                    "severity": issue.severity,
                    "category": issue.category,
                    "agent_name": issue.agent_name,
                    "message": issue.message,
                    "details": issue.details,
                }
                for issue in self.issues
            ],
            "summary": self.summary,
        }


class Monitor:
    """监控器"""

    def __init__(
        self,
        check_schema: bool = True,
        check_quality: bool = True,
        check_performance: bool = True,
        max_duration_ms: Optional[int] = None,
        min_output_length: int = 10,
    ):
        """
        初始化监控器

        Args:
            check_schema: 是否检查 Schema
            check_quality: 是否检查质量
            check_performance: 是否检查性能
            max_duration_ms: 最大允许耗时（毫秒）
            min_output_length: 最小输出长度
        """
        self.check_schema = check_schema
        self.check_quality = check_quality
        self.check_performance = check_performance
        self.max_duration_ms = max_duration_ms
        self.min_output_length = min_output_length

    def monitor(self, record: ExecutionRecord, execution_id: Optional[int] = None) -> MonitorReport:
        """
        监控执行记录

        Args:
            record: 执行记录
            execution_id: 执行记录 ID

        Returns:
            监控报告
        """
        report = MonitorReport(
            workflow_name=record.workflow_name,
            execution_id=execution_id,
        )

        # 检查整体状态
        self._check_overall_status(record, report)

        # 检查每个 Agent
        for agent_name, agent_record in record.agent_records.items():
            if self.check_schema:
                self._check_schema(agent_name, agent_record, report)
            if self.check_quality:
                self.check_quality_for_agent(agent_name, agent_record, report)
            if self.check_performance:
                self._check_performance(agent_name, agent_record, report)

        # 生成摘要
        self._generate_summary(record, report)

        return report

    def _check_overall_status(self, record: ExecutionRecord, report: MonitorReport) -> None:
        """检查整体状态"""
        if record.status == ExecutionStatus.FAILED:
            report.add_issue(
                severity="error",
                category="general",
                agent_name=None,
                message=f"Workflow execution failed: {record.error}",
            )

    def _check_schema(self, agent_name: str, agent_record: AgentExecutionRecord, report: MonitorReport) -> None:
        """检查 Schema"""
        # 检查输出是否为空
        if not agent_record.output_data:
            report.add_issue(
                severity="warning",
                category="schema",
                agent_name=agent_name,
                message="Agent output is empty",
            )
            return

        # 检查输出是否为字典
        if not isinstance(agent_record.output_data, dict):
            report.add_issue(
                severity="warning",
                category="schema",
                agent_name=agent_name,
                message=f"Agent output is not a dict: {type(agent_record.output_data)}",
            )

    def check_quality_for_agent(self, agent_name: str, agent_record: AgentExecutionRecord, report: MonitorReport) -> None:
        """检查质量"""
        # 检查输出长度
        if agent_record.output_data:
            output_str = str(agent_record.output_data)
            if len(output_str) < self.min_output_length:
                report.add_issue(
                    severity="warning",
                    category="quality",
                    agent_name=agent_name,
                    message=f"Agent output is too short ({len(output_str)} chars)",
                    details={"output_length": len(output_str)},
                )

        # 检查是否有错误
        if agent_record.error:
            report.add_issue(
                severity="error",
                category="quality",
                agent_name=agent_name,
                message=f"Agent execution failed: {agent_record.error}",
            )

    def _check_performance(self, agent_name: str, agent_record: AgentExecutionRecord, report: MonitorReport) -> None:
        """检查性能"""
        if agent_record.duration_ms is None:
            return

        # 检查是否超时
        if self.max_duration_ms and agent_record.duration_ms > self.max_duration_ms:
            report.add_issue(
                severity="warning",
                category="performance",
                agent_name=agent_name,
                message=f"Agent execution took too long ({agent_record.duration_ms}ms)",
                details={"duration_ms": agent_record.duration_ms, "max_duration_ms": self.max_duration_ms},
            )

    def _generate_summary(self, record: ExecutionRecord, report: MonitorReport) -> None:
        """生成摘要"""
        report.summary = {
            "status": record.status.value,
            "total_duration_ms": record.total_duration_ms,
            "agent_count": len(record.agent_records),
            "completed_agents": sum(1 for r in record.agent_records.values() if r.status == ExecutionStatus.COMPLETED),
            "failed_agents": sum(1 for r in record.agent_records.values() if r.status == ExecutionStatus.FAILED),
            "issue_count": len(report.issues),
            "error_count": report.error_count,
            "warning_count": report.warning_count,
        }


# 全局监控器实例
monitor = Monitor()

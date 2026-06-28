"""
监控模块测试

测试内容：
- Schema 检查
- 质量检查
- 性能检查
- 报告生成
"""

import pytest
from datetime import datetime

from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.monitor import Monitor, MonitorReport, MonitorIssue


class TestMonitor:
    """Monitor 测试"""

    @pytest.fixture
    def monitor(self):
        """创建监控器实例"""
        return Monitor(
            check_schema=True,
            check_quality=True,
            check_performance=True,
            max_duration_ms=5000,
            min_output_length=10,
        )

    @pytest.fixture
    def successful_record(self):
        """创建成功的执行记录"""
        record = ExecutionRecord(
            workflow_name="test_workflow",
            status=ExecutionStatus.COMPLETED,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            total_duration_ms=1000,
        )

        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.COMPLETED,
            input_data={"input": "test"},
            output_data={"output": "This is a test result"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_ms=500,
        )

        return record

    @pytest.fixture
    def failed_record(self):
        """创建失败的执行记录"""
        record = ExecutionRecord(
            workflow_name="test_workflow",
            status=ExecutionStatus.FAILED,
            error="Workflow execution failed",
        )

        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.FAILED,
            error="Agent execution failed",
        )

        return record

    def test_monitor_success(self, monitor, successful_record):
        """测试成功的监控"""
        report = monitor.monitor(successful_record)

        assert report.workflow_name == "test_workflow"
        assert not report.has_errors
        assert report.summary["status"] == "completed"
        assert report.summary["completed_agents"] == 1

    def test_monitor_failure(self, monitor, failed_record):
        """测试失败的监控"""
        report = monitor.monitor(failed_record)

        assert report.has_errors
        assert report.error_count > 0

    def test_check_schema_empty_output(self, monitor):
        """测试检查空输出"""
        record = ExecutionRecord(workflow_name="test", status=ExecutionStatus.COMPLETED)
        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.COMPLETED,
            output_data={},
        )

        report = monitor.monitor(record)
        assert any(issue.category == "schema" for issue in report.issues)

    def test_check_quality_short_output(self, monitor):
        """测试检查短输出"""
        record = ExecutionRecord(workflow_name="test", status=ExecutionStatus.COMPLETED)
        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.COMPLETED,
            output_data={},  # 空输出
        )

        report = monitor.monitor(record)
        assert any(issue.category == "quality" or issue.category == "schema" for issue in report.issues)

    def test_check_performance_timeout(self, monitor):
        """测试检查超时"""
        record = ExecutionRecord(workflow_name="test", status=ExecutionStatus.COMPLETED)
        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.COMPLETED,
            output_data={"text": "This is a long enough result"},
            duration_ms=10000,  # 超过 max_duration_ms
        )

        report = monitor.monitor(record)
        assert any(issue.category == "performance" for issue in report.issues)

    def test_monitor_report_to_dict(self, monitor, successful_record):
        """测试报告转字典"""
        report = monitor.monitor(successful_record)
        report_dict = report.to_dict()

        assert "workflow_name" in report_dict
        assert "issues" in report_dict
        assert "summary" in report_dict

    def test_monitor_with_execution_id(self, monitor, successful_record):
        """测试带执行 ID 的监控"""
        report = monitor.monitor(successful_record, execution_id=123)
        assert report.execution_id == 123

    def test_monitor_no_checks(self):
        """测试禁用所有检查"""
        monitor = Monitor(
            check_schema=False,
            check_quality=False,
            check_performance=False,
        )

        record = ExecutionRecord(workflow_name="test", status=ExecutionStatus.COMPLETED)
        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.COMPLETED,
            output_data={},
        )

        report = monitor.monitor(record)
        assert len(report.issues) == 0


class TestMonitorReport:
    """MonitorReport 测试"""

    def test_report_creation(self):
        """测试报告创建"""
        report = MonitorReport(workflow_name="test", execution_id=1)
        assert report.workflow_name == "test"
        assert report.execution_id == 1
        assert len(report.issues) == 0

    def test_add_issue(self):
        """测试添加问题"""
        report = MonitorReport(workflow_name="test", execution_id=1)
        report.add_issue("warning", "schema", "A", "Test issue")

        assert len(report.issues) == 1
        assert report.issues[0].severity == "warning"
        assert report.issues[0].category == "schema"
        assert report.issues[0].agent_name == "A"

    def test_has_errors(self):
        """测试是否有错误"""
        report = MonitorReport(workflow_name="test", execution_id=1)
        assert not report.has_errors

        report.add_issue("error", "general", None, "Test error")
        assert report.has_errors

    def test_has_warnings(self):
        """测试是否有警告"""
        report = MonitorReport(workflow_name="test", execution_id=1)
        assert not report.has_warnings

        report.add_issue("warning", "schema", "A", "Test warning")
        assert report.has_warnings

    def test_error_count(self):
        """测试错误数量"""
        report = MonitorReport(workflow_name="test", execution_id=1)
        assert report.error_count == 0

        report.add_issue("error", "general", None, "Error 1")
        report.add_issue("error", "general", None, "Error 2")
        report.add_issue("warning", "schema", "A", "Warning 1")

        assert report.error_count == 2

    def test_warning_count(self):
        """测试警告数量"""
        report = MonitorReport(workflow_name="test", execution_id=1)
        assert report.warning_count == 0

        report.add_issue("warning", "schema", "A", "Warning 1")
        report.add_issue("warning", "quality", "B", "Warning 2")
        report.add_issue("error", "general", None, "Error 1")

        assert report.warning_count == 2

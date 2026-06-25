"""
数据库模块测试

测试内容：
- 执行记录保存
- 执行记录查询
- 执行记录列表
- 执行记录删除
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from core.models import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.db import ExecutionDatabase, DatabaseError


class TestExecutionDatabase:
    """ExecutionDatabase 测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def db(self, temp_dir):
        """创建数据库实例"""
        return ExecutionDatabase(db_path=temp_dir / "test.db")

    @pytest.fixture
    def sample_record(self):
        """创建示例执行记录"""
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
            output_data={"output": "result"},
            started_at=datetime.now(),
            completed_at=datetime.now(),
            duration_ms=500,
        )

        return record

    def test_save_and_get(self, db, sample_record):
        """测试保存和获取"""
        # 保存
        execution_id = db.save_execution(sample_record)
        assert execution_id is not None

        # 获取
        loaded = db.get_execution(execution_id)
        assert loaded is not None
        assert loaded.workflow_name == "test_workflow"
        assert loaded.status == ExecutionStatus.COMPLETED

    def test_save_preserves_agents(self, db, sample_record):
        """测试保存保留 Agent 记录"""
        execution_id = db.save_execution(sample_record)
        loaded = db.get_execution(execution_id)

        assert "A" in loaded.agent_records
        agent_record = loaded.agent_records["A"]
        assert agent_record.status == ExecutionStatus.COMPLETED
        assert agent_record.input_data == {"input": "test"}
        assert agent_record.output_data == {"output": "result"}

    def test_list_executions(self, db, sample_record):
        """测试列出执行记录"""
        # 初始为空
        assert db.list_executions() == []

        # 保存一个记录
        db.save_execution(sample_record)

        # 列出记录
        executions = db.list_executions()
        assert len(executions) == 1
        assert executions[0]["workflow_name"] == "test_workflow"

    def test_list_executions_by_workflow(self, db):
        """测试按工作流名称列出执行记录"""
        # 创建多个记录
        record1 = ExecutionRecord(workflow_name="workflow1", status=ExecutionStatus.COMPLETED)
        record2 = ExecutionRecord(workflow_name="workflow2", status=ExecutionStatus.COMPLETED)
        record3 = ExecutionRecord(workflow_name="workflow1", status=ExecutionStatus.FAILED)

        db.save_execution(record1)
        db.save_execution(record2)
        db.save_execution(record3)

        # 按工作流名称过滤
        workflow1_executions = db.list_executions(workflow_name="workflow1")
        assert len(workflow1_executions) == 2

        workflow2_executions = db.list_executions(workflow_name="workflow2")
        assert len(workflow2_executions) == 1

    def test_delete_execution(self, db, sample_record):
        """测试删除执行记录"""
        # 保存
        execution_id = db.save_execution(sample_record)
        assert db.get_execution(execution_id) is not None

        # 删除
        db.delete_execution(execution_id)
        assert db.get_execution(execution_id) is None

    def test_get_nonexistent(self, db):
        """测试获取不存在的记录"""
        assert db.get_execution(999) is None

    def test_save_failed_execution(self, db):
        """测试保存失败的执行记录"""
        record = ExecutionRecord(
            workflow_name="test_workflow",
            status=ExecutionStatus.FAILED,
            error="Test error",
        )

        execution_id = db.save_execution(record)
        loaded = db.get_execution(execution_id)

        assert loaded.status == ExecutionStatus.FAILED
        assert loaded.error == "Test error"

    def test_multiple_agent_records(self, db):
        """测试多个 Agent 记录"""
        record = ExecutionRecord(workflow_name="test_workflow", status=ExecutionStatus.COMPLETED)

        record.agent_records["A"] = AgentExecutionRecord(
            agent_name="A",
            status=ExecutionStatus.COMPLETED,
            duration_ms=100,
        )

        record.agent_records["B"] = AgentExecutionRecord(
            agent_name="B",
            status=ExecutionStatus.COMPLETED,
            duration_ms=200,
        )

        execution_id = db.save_execution(record)
        loaded = db.get_execution(execution_id)

        assert len(loaded.agent_records) == 2
        assert "A" in loaded.agent_records
        assert "B" in loaded.agent_records

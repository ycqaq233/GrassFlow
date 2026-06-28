"""
GrassFlow 运行时执行记录类型

从 core/models.py 分离出来的运行时状态类型。
DSL 定义类型在 core/models.py（或 core/dsl_v2_ast.py）中。
"""

from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentExecutionRecord(BaseModel):
    """单个 Agent 的执行记录"""
    agent_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionRecord(BaseModel):
    """工作流执行记录"""
    workflow_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    total_duration_ms: Optional[int] = None
    agent_records: Dict[str, AgentExecutionRecord] = Field(default_factory=dict)
    error: Optional[str] = None

    def start(self):
        """标记开始执行"""
        self.status = ExecutionStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self):
        """标记执行完成"""
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = datetime.now()
        if self.started_at:
            ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
            self.duration_ms = ms
            self.total_duration_ms = ms

    def fail(self, error: str):
        """标记执行失败"""
        self.status = ExecutionStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()
        if self.started_at:
            ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
            self.duration_ms = ms
            self.total_duration_ms = ms

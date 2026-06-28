"""
GrassFlow 执行记录模块

定义运行时执行状态和记录类型。
从 core.models 中分离出来，专注于运行时状态管理。
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
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class ExecutionRecord(BaseModel):
    """工作流执行记录"""
    workflow_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    agent_records: Dict[str, AgentExecutionRecord] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_duration_ms: Optional[int] = None
    error: Optional[str] = None

    def start(self) -> None:
        """标记开始执行"""
        self.status = ExecutionStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self) -> None:
        """标记执行完成"""
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = datetime.now()
        if self.started_at:
            self.total_duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )

    def fail(self, error: str) -> None:
        """标记执行失败"""
        self.status = ExecutionStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()
        if self.started_at:
            self.total_duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )

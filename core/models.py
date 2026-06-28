"""
GrassFlow 数据模型

定义：
- Workflow: 工作流定义
- AgentConfig: Agent 配置
- ExecutionRecord: 执行记录
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class AgentType(str, Enum):
    """Agent 类型"""
    LLM = "llm"
    CONDITION = "condition"
    MANUAL = "manual"
    INPUT = "input"
    OUTPUT = "output"


class InteractionType(str, Enum):
    """交互类型"""
    SEQUENCE = "sequence"      # 顺序执行
    PARALLEL = "parallel"      # 并行执行
    IMMEDIATE = "immediate"    # 立即执行（先启动，遇依赖等待）
    CONDITION = "condition"    # 条件分支
    BROADCAST = "broadcast"    # 广播分发
    AGGREGATE = "aggregate"    # 聚合等待


class AgentConfig(BaseModel):
    """Agent 配置"""
    name: str
    type: AgentType = AgentType.LLM
    model: str = "gpt-4"
    prompt: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    on_fail: str = "stop"
    retry_count: int = 3
    timeout: Optional[int] = None
    api_key: Optional[str] = None  # 可选，不填用全局


class Edge(BaseModel):
    """边（连接）"""
    source: str  # 源 Agent 名称
    target: str  # 目标 Agent 名称
    interaction_type: InteractionType = InteractionType.SEQUENCE
    condition: Optional[str] = None  # 条件分支的条件


class Workflow(BaseModel):
    """工作流定义"""
    name: str
    description: str = ""
    agents: List[AgentConfig] = Field(default_factory=list)
    edges: List[Edge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def get_agent(self, name: str) -> Optional[AgentConfig]:
        """根据名称获取 Agent 配置"""
        for agent in self.agents:
            if agent.name == name:
                return agent
        return None

    def add_agent(self, config: AgentConfig) -> None:
        """添加 Agent"""
        if self.get_agent(config.name):
            raise ValueError(f"Agent '{config.name}' already exists")
        self.agents.append(config)
        self.updated_at = datetime.now()

    def add_edge(self, edge: Edge) -> None:
        """添加边"""
        # 验证源和目标 Agent 存在
        if not self.get_agent(edge.source):
            raise ValueError(f"Source agent '{edge.source}' not found")
        if not self.get_agent(edge.target):
            raise ValueError(f"Target agent '{edge.target}' not found")
        self.edges.append(edge)
        self.updated_at = datetime.now()


# 运行时执行类型已提取到 core.execution，此处保留向后兼容导入
from core.execution import ExecutionStatus, AgentExecutionRecord, ExecutionRecord  # noqa: F401

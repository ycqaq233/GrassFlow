"""
GrassFlow 数据模型

定义：
- Component: v2 组件定义
- Workflow: v2 工作流定义
- AgentInstance: v2 Agent 实例
- Connection: v2 连接定义
- ExecutionRecord: 执行记录
- AgentConfig (legacy): v1 Agent 配置
- Edge (legacy): v1 边定义
"""

from dataclasses import dataclass, field
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


class WorkflowV1(BaseModel):
    """工作流定义 (v1 legacy)"""
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


# Backward compatibility alias
Workflow = WorkflowV1


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
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
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


# ============================================================================
# v2 DSL types (dataclasses)
# ============================================================================


@dataclass
class Port:
    """端口定义"""
    name: str
    direction: str  # "input" | "output"
    type: str       # "string" | "number" | "boolean" | "object" | "array"
    description: Optional[str] = None
    sync: bool = True  # True = sync, False = async


@dataclass
class MCPConfig:
    """MCP 服务器配置"""
    server_name: str
    tools: List[str] = field(default_factory=list)


@dataclass
class PermissionConfig:
    """权限配置"""
    allow: List[str] = field(default_factory=list)
    deny: List[str] = field(default_factory=list)
    ask: List[str] = field(default_factory=list)


@dataclass
class ModelConfig:
    """模型配置"""
    default: Optional[str] = None
    fallback: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@dataclass
class Component:
    """组件定义"""
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    system_prompt: Optional[str] = None
    ports: List[Port] = field(default_factory=list)
    mcp: List[MCPConfig] = field(default_factory=list)
    model: ModelConfig = field(default_factory=ModelConfig)
    permission: PermissionConfig = field(default_factory=PermissionConfig)
    mode: str = "batch"      # "batch" | "stream"
    context: str = "shared"  # "shared" | "independent"
    on_fail: str = "stop"    # "stop" | "skip" | "retry"
    retry_count: int = 3


@dataclass
class AgentInstance:
    """Agent 实例（在 workflow 中使用）"""
    name: str
    component: Optional[str] = None  # use 关键字引用的组件名
    overrides: Dict[str, Any] = field(default_factory=dict)
    inline_ports: List[Port] = field(default_factory=list)
    inline_system_prompt: Optional[str] = None


@dataclass
class Connection:
    """连接定义"""
    source_agent: str
    source_port: Optional[str] = None  # None = 默认端口
    target_agents: List[str] = field(default_factory=list)
    target_ports: List[str] = field(default_factory=list)


@dataclass
class Workflow:
    """工作流定义 (v2)"""
    name: str
    ports: List[Port] = field(default_factory=list)
    agents: List[AgentInstance] = field(default_factory=list)
    connections: List[Connection] = field(default_factory=list)
    output_mappings: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParseResult:
    """解析结果"""
    components: List[Component] = field(default_factory=list)
    workflows: List[Workflow] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

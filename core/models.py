"""
GrassFlow 数据模型

v2 类型系统（唯一类型源）：
- Port / MCPConfig / PermissionConfig / ModelConfig
- Component / AgentInstance / Connection / Workflow / ParseResult
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Port(BaseModel):
    """端口定义"""
    name: str
    direction: str  # "input" | "output"
    type: str       # "string" | "number" | "boolean" | "object" | "array"
    description: Optional[str] = None
    sync: bool = True  # True = sync, False = async


class MCPConfig(BaseModel):
    """MCP 服务器配置"""
    server_name: str
    tools: List[str] = Field(default_factory=list)


class PermissionConfig(BaseModel):
    """权限配置"""
    allow: List[str] = Field(default_factory=list)
    deny: List[str] = Field(default_factory=list)
    ask: List[str] = Field(default_factory=list)


class ModelConfig(BaseModel):
    """模型配置"""
    default: Optional[str] = None
    fallback: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class Component(BaseModel):
    """组件定义"""
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    system_prompt: Optional[str] = None
    ports: List[Port] = Field(default_factory=list)
    mcp: List[MCPConfig] = Field(default_factory=list)
    model: ModelConfig = Field(default_factory=ModelConfig)
    permission: PermissionConfig = Field(default_factory=PermissionConfig)
    mode: str = "batch"      # "batch" | "stream"
    context: str = "shared"  # "shared" | "independent"
    on_fail: str = "stop"    # "stop" | "skip" | "retry"
    retry_count: int = 3


class AgentInstance(BaseModel):
    """Agent 实例（在 workflow 中使用）"""
    name: str
    component: Optional[str] = None  # use 关键字引用的组件名
    overrides: Dict[str, Any] = Field(default_factory=dict)
    inline_ports: List[Port] = Field(default_factory=list)
    inline_system_prompt: Optional[str] = None


class Connection(BaseModel):
    """连接定义"""
    source_agent: str
    source_port: Optional[str] = None  # None = 默认端口
    target_agents: List[str] = Field(default_factory=list)
    target_ports: List[str] = Field(default_factory=list)


class Workflow(BaseModel):
    """工作流定义"""
    name: str
    ports: List[Port] = Field(default_factory=list)
    agents: List[AgentInstance] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)
    output_mappings: Dict[str, str] = Field(default_factory=dict)


class ParseResult(BaseModel):
    """解析结果"""
    components: List[Component] = Field(default_factory=list)
    workflows: List[Workflow] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

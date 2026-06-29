"""
GrassFlow 数据模型

v2 类型系统 — 唯一数据模型来源。
运行时执行记录类型在 core/execution.py 中。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Port:
    """端口定义"""
    name: str
    direction: str  # "input" | "output"
    type: str = "string"  # "string" | "number" | "boolean" | "object" | "array"
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
    max_tool_iterations: int = 30  # 工具调用循环最大迭代次数


@dataclass
class AgentInstance:
    """Agent 实例（在 workflow 中使用）"""
    name: str
    component: Optional[str] = None  # use 关键字引用的组件名
    overrides: Dict[str, Any] = field(default_factory=dict)
    inline_ports: List[Port] = field(default_factory=list)
    inline_system_prompt: Optional[str] = None
    mode: str = "batch"      # "batch" | "stream"
    context: str = "shared"  # "shared" | "independent"


@dataclass
class Connection:
    """连接定义

    支持条件路由：当 routing_rules 非空时，只有匹配条件的 target 才会被执行。
    routing_rules 格式: {condition_value: [target_agent_name, ...]}
    """
    source_agent: str
    source_port: Optional[str] = None  # None = 默认端口
    target_agents: List[str] = field(default_factory=list)
    target_ports: List[str] = field(default_factory=list)
    routing_rules: Dict[str, List[str]] = field(default_factory=dict)


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

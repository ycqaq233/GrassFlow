"""
GrassFlow Agent 组件运行时

将 DSL v2 AST 的 Component 定义转换为可执行的 Agent 实例。

核心职责：
1. 组件实例化：从 Component AST 创建可执行的 ComponentAgent
2. 端口映射：将端口连接转换为数据流路由
3. use 关键字解析：通过 ComponentRegistry 查找和引用组件
4. 运行时参数覆盖：允许实例化时覆盖 model/on_fail/retry_count 等参数
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .agent import Agent, AgentConfig
from .dsl_v2_ast import (
    AgentInstance,
    Component,
    Connection,
    MCPConfig,
    ModelConfig,
    PermissionConfig,
    Port,
    Workflow,
)

# ---------------------------------------------------------------------------
# 端口类型到 JSON Schema 的映射
# ---------------------------------------------------------------------------

PORT_TYPE_TO_JSON_SCHEMA: Dict[str, Dict[str, str]] = {
    "string": {"type": "string"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "object": {"type": "object"},
    "array": {"type": "array"},
}


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class ComponentError(Exception):
    """组件运行时基础异常"""


class ComponentNotFoundError(ComponentError):
    """组件未找到"""


class PortConflictError(ComponentError):
    """端口冲突"""


class OverrideError(ComponentError):
    """不允许的参数覆盖"""


class PortMappingError(ComponentError):
    """端口映射错误"""


# ---------------------------------------------------------------------------
# 端口映射器
# ---------------------------------------------------------------------------


@dataclass
class PortMapping:
    """单条端口映射关系

    描述 source_agent.source_port -> target_agent.target_port 的数据流。
    """

    source_agent: str
    source_port: str
    target_agent: str
    target_port: str


class PortMapper:
    """将 DSL v2 Connection 列表转换为具体的端口映射列表。

    处理默认端口（None -> "in" / "out"）、广播和聚合场景。
    """

    DEFAULT_INPUT_PORT = "in"
    DEFAULT_OUTPUT_PORT = "out"

    def __init__(self, agents: Dict[str, "ComponentAgent"]):
        """
        Args:
            agents: agent_name -> ComponentAgent 映射
        """
        self._agents = agents

    def _resolve_source_port(self, agent_name: str, port: Optional[str]) -> str:
        if port is not None:
            return port
        # 自动选择第一个 output 端口，否则使用默认名 "out"
        agent = self._agents.get(agent_name)
        if agent is not None:
            output_ports = agent.get_output_ports()
            if output_ports:
                return output_ports[0].name
        return self.DEFAULT_OUTPUT_PORT

    def _resolve_target_port(self, agent_name: str, port: Optional[str]) -> str:
        if port is not None:
            return port
        # 自动选择第一个 input 端口，否则使用默认名 "in"
        agent = self._agents.get(agent_name)
        if agent is not None:
            input_ports = agent.get_input_ports()
            if input_ports:
                return input_ports[0].name
        return self.DEFAULT_INPUT_PORT

    def map_connections(
        self, connections: List[Connection]
    ) -> List[PortMapping]:
        """将 Connection 列表展开为 PortMapping 列表。

        处理规则：
        - source_agent == "__aggregate__" 时，聚合源来自 target_agents 之前
          的 Connection（由调用方负责组合）；此处先按普通连接展开。
        - 一对多（广播）：一个 source 对多个 target。
        - target_ports 可能比 target_agents 短，缺失时使用默认端口。
        """
        mappings: List[PortMapping] = []

        for conn in connections:
            src_port = self._resolve_source_port(conn.source_agent, conn.source_port)

            for idx, tgt in enumerate(conn.target_agents):
                tgt_port: Optional[str] = None
                if idx < len(conn.target_ports):
                    tgt_port = conn.target_ports[idx]
                resolved_tgt = self._resolve_target_port(tgt, tgt_port)

                mappings.append(
                    PortMapping(
                        source_agent=conn.source_agent,
                        source_port=src_port,
                        target_agent=tgt,
                        target_port=resolved_tgt,
                    )
                )

        return mappings


# ---------------------------------------------------------------------------
# 组件注册表
# ---------------------------------------------------------------------------


class ComponentRegistry:
    """管理组件定义，支持 use 关键字的查找与解析。

    查找顺序（就近优先）：
    1. 当前 registry 内存中的组件
    2. （未来扩展）文件系统 .grass/components/
    """

    def __init__(self):
        self._components: Dict[str, Component] = {}

    def register(self, component: Component) -> None:
        """注册组件（同名覆盖）"""
        self._components[component.name] = component

    def register_all(self, components: List[Component]) -> None:
        """批量注册"""
        for c in components:
            self.register(c)

    def get(self, name: str) -> Component:
        """查找组件，找不到抛 ComponentNotFoundError"""
        if name not in self._components:
            raise ComponentNotFoundError(
                f"Component '{name}' not found in registry. "
                f"Available: {list(self._components.keys())}"
            )
        return self._components[name]

    def has(self, name: str) -> bool:
        return name in self._components

    def list_names(self) -> List[str]:
        return list(self._components.keys())

    def resolve_use_chain(
        self,
        component: Component,
        seen: Optional[Set[str]] = None,
    ) -> Component:
        """递归解析 use 链，返回合并后的最终 Component。

        use 引入的属性合并规则（参见 DSL v2 规范 6.2）：
        - 端口：合并，同名不同类型报错
        - system_prompt / model / mode / context / on_fail / retry_count：
          后者覆盖前者
        - MCP：同名 server 的 tools 取并集
        - 权限：合并取并集
        - description / version：后者覆盖前者

        Args:
            component: 待解析的组件（可能包含 use 引用但尚未展开）
            seen: 已访问的组件名集合（防止循环引用）

        Returns:
            合并后的 Component
        """
        if seen is None:
            seen = set()
        if component.name in seen:
            raise ComponentError(
                f"Circular use reference detected: {' -> '.join(seen)} -> {component.name}"
            )
        seen.add(component.name)

        # 注意：当前 AST 的 Component 没有 use_list 字段；
        # use 引用在 workflow 层面通过 AgentInstance.component 字段解析，
        # 在组件层面通过 ComponentRegistry.get() 获取完整定义。
        # 此方法主要用于合并多层引用的组件。

        # 深拷贝避免修改原始定义
        return copy.deepcopy(component)

    def clear(self) -> None:
        self._components.clear()


# ---------------------------------------------------------------------------
# 组件 Agent
# ---------------------------------------------------------------------------


class ComponentAgent(Agent):
    """从 DSL v2 Component 定义创建的可执行 Agent。

    职责：
    - 将 Component 的 ports 转换为 input_schema / output_schema
    - 渲染 system_prompt 模板变量
    - 作为 LLM Agent 执行（可被子类覆盖以接入真实 LLM）
    """

    def __init__(
        self,
        component: Component,
        agent_name: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            component: 组件定义（已解析 use 链）
            agent_name: 实例名称（workflow 中的 agent 名），默认使用组件名
            overrides: 运行时覆盖参数
        """
        overrides = overrides or {}
        self._component = component
        self._agent_name = agent_name or component.name
        self._overrides = overrides

        # 构建 AgentConfig
        config = self._build_config(component, self._agent_name, overrides)
        super().__init__(config)

        # 保留端口定义，便于运行时映射
        self._ports: Dict[str, Port] = {}
        for p in component.ports:
            self._ports[p.name] = p

        # MCP 配置
        self._mcp_configs: List[MCPConfig] = list(component.mcp)

        # 权限配置
        self._permission = component.permission

        # 执行模式
        self._mode = component.mode
        self._context_strategy = component.context

    # ---- 构建 ----

    @staticmethod
    def _build_config(
        component: Component,
        agent_name: str,
        overrides: Dict[str, Any],
    ) -> AgentConfig:
        """从 Component + overrides 构建 AgentConfig"""
        # 模型
        model = overrides.get("model") or component.model.default or "gpt-4"

        # system_prompt
        system_prompt = component.system_prompt or ""

        # 端口 -> JSON Schema
        input_schema = ComponentAgent._ports_to_schema(
            component.ports, direction="input"
        )
        output_schema = ComponentAgent._ports_to_schema(
            component.ports, direction="output"
        )

        # 失败策略
        on_fail = overrides.get("on_fail", component.on_fail)
        retry_count = overrides.get("retry_count", component.retry_count)

        return AgentConfig(
            name=agent_name,
            model=model,
            prompt=system_prompt,
            input_schema=input_schema,
            output_schema=output_schema,
            on_fail=on_fail,
            retry_count=retry_count,
        )

    @staticmethod
    def _ports_to_schema(
        ports: List[Port], direction: str
    ) -> Dict[str, Any]:
        """将端口列表转换为 JSON Schema properties"""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for p in ports:
            if p.direction != direction:
                continue
            properties[p.name] = PORT_TYPE_TO_JSON_SCHEMA.get(
                p.type, {"type": "object"}
            )
            required.append(p.name)

        if not properties:
            return {}
        return {"type": "object", "properties": properties, "required": required}

    # ---- 端口访问 ----

    def get_input_ports(self) -> List[Port]:
        return [p for p in self._ports.values() if p.direction == "input"]

    def get_output_ports(self) -> List[Port]:
        return [p for p in self._ports.values() if p.direction == "output"]

    def get_port(self, name: str) -> Optional[Port]:
        return self._ports.get(name)

    @property
    def component(self) -> Component:
        return self._component

    @property
    def agent_name(self) -> str:
        return self._agent_name

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def context_strategy(self) -> str:
        return self._context_strategy

    @property
    def mcp_configs(self) -> List[MCPConfig]:
        return list(self._mcp_configs)

    @property
    def permission(self) -> PermissionConfig:
        return self._permission

    # ---- 模板渲染 ----

    def _render_system_prompt(self, input_data: Dict[str, Any]) -> str:
        """将 system_prompt 中的 {port_name} 替换为实际输入值。

        例如: "审查代码: {code}" -> "审查代码: <actual code>"
        """
        template = self.config.prompt or ""
        if not template:
            return ""

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            value = input_data.get(var_name)
            if value is None:
                return match.group(0)  # 保留原样
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return re.sub(r"\{(\w+)\}", replacer, template)

    def _build_llm_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """将端口输入数据转换为 LLM prompt 所需的格式。

        返回包含渲染后 system_prompt 和各端口值的字典。
        """
        rendered = self._render_system_prompt(input_data)
        # 构造 LLM messages 格式（供上层调度器或 LLM 客户端使用）
        messages: List[Dict[str, str]] = []
        if rendered:
            messages.append({"role": "system", "content": rendered})

        # 将所有输入端口数据拼接为用户消息
        user_parts: List[str] = []
        for port in self.get_input_ports():
            value = input_data.get(port.name)
            if value is not None:
                if isinstance(value, (dict, list)):
                    user_parts.append(
                        f"[{port.name}]\n{json.dumps(value, ensure_ascii=False, indent=2)}"
                    )
                else:
                    user_parts.append(f"[{port.name}]\n{value}")

        if user_parts:
            messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        return {
            "messages": messages,
            "model": self.config.model,
            "temperature": self._overrides.get("temperature"),
            "max_tokens": self._overrides.get("max_tokens"),
            "fallback": self._overrides.get(
                "fallback", self._component.model.fallback
            ),
        }

    # ---- 执行 ----

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行组件 Agent。

        默认实现：将输入数据透传并附带 LLM 调用元信息。
        子类应覆盖此方法以接入真实 LLM。

        Args:
            input_data: 端口名 -> 值 的字典

        Returns:
            输出端口名 -> 值 的字典
        """
        llm_request = self._build_llm_input(input_data)

        # 默认行为：如果没有 LLM 客户端，返回模拟输出
        # 真实的 LLM 调用由 LLMAgentComponent 子类实现
        output: Dict[str, Any] = {}
        for port in self.get_output_ports():
            # 如果输入中有同名端口，透传
            if port.name in input_data:
                output[port.name] = input_data[port.name]
            else:
                output[port.name] = None

        # 附加元信息
        output["_component"] = {
            "name": self._component.name,
            "version": self._component.version,
            "mode": self._mode,
            "context": self._context_strategy,
            "llm_request": llm_request,
        }
        return output


# ---------------------------------------------------------------------------
# 组件工厂
# ---------------------------------------------------------------------------


class ComponentFactory:
    """从 AgentInstance AST 创建可执行的 ComponentAgent。

    职责：
    - 通过 ComponentRegistry 解析 use 引用
    - 验证覆盖参数的合法性
    - 合并组件定义和实例化覆盖
    """

    # 允许实例化时覆盖的参数
    ALLOWED_OVERRIDE_KEYS: Set[str] = {
        "model",
        "temperature",
        "max_tokens",
        "fallback",
        "on_fail",
        "retry_count",
    }

    # 不允许覆盖的参数（安全策略）
    DISALLOWED_OVERRIDE_KEYS: Set[str] = {
        "port",
        "ports",
        "system_prompt",
        "mcp",
        "permission",
    }

    def __init__(self, registry: ComponentRegistry):
        self._registry = registry

    def validate_overrides(self, overrides: Dict[str, Any]) -> None:
        """验证覆盖参数是否合法。

        Raises:
            OverrideError: 存在不允许覆盖的参数
        """
        for key in overrides:
            if key in self.DISALLOWED_OVERRIDE_KEYS:
                raise OverrideError(
                    f"Parameter '{key}' cannot be overridden at instantiation time. "
                    f"Define a new component instead."
                )

    def create(
        self,
        agent_instance: AgentInstance,
        component: Optional[Component] = None,
    ) -> ComponentAgent:
        """从 AgentInstance 创建 ComponentAgent。

        Args:
            agent_instance: workflow 中的 agent 定义
            component: 预解析的组件定义（可选，否则从 registry 查找）

        Returns:
            可执行的 ComponentAgent

        Raises:
            ComponentNotFoundError: 引用的组件不存在
            OverrideError: 覆盖参数不合法
        """
        # 1. 获取组件定义
        if component is None:
            if agent_instance.component is None:
                raise ComponentError(
                    f"Agent '{agent_instance.name}' has no component reference "
                    f"and no component was provided."
                )
            component = self._registry.get(agent_instance.component)

        # 2. 解析 use 链
        resolved = self._registry.resolve_use_chain(component)

        # 3. 验证覆盖参数
        self.validate_overrides(agent_instance.overrides)

        # 4. 构建覆盖字典
        overrides = self._build_overrides(resolved, agent_instance)

        # 5. 合并内联定义（如果 agent 是内联定义的）
        if agent_instance.inline_ports:
            resolved = self._merge_inline_definition(resolved, agent_instance)

        # 6. 创建 ComponentAgent
        return ComponentAgent(
            component=resolved,
            agent_name=agent_instance.name,
            overrides=overrides,
        )

    def _build_overrides(
        self, component: Component, agent_instance: AgentInstance
    ) -> Dict[str, Any]:
        """从 AgentInstance.overrides 构建标准化的覆盖字典"""
        overrides: Dict[str, Any] = {}
        raw = agent_instance.overrides

        # model
        if "model" in raw:
            overrides["model"] = raw["model"]

        # model temperature / max_tokens / fallback
        if "temperature" in raw:
            overrides["temperature"] = raw["temperature"]
        if "max_tokens" in raw:
            overrides["max_tokens"] = raw["max_tokens"]
        if "fallback" in raw:
            overrides["fallback"] = raw["fallback"]

        # on_fail
        if "on_fail" in raw:
            overrides["on_fail"] = raw["on_fail"]

        # retry_count
        if "retry_count" in raw:
            overrides["retry_count"] = raw["retry_count"]

        return overrides

    def _merge_inline_definition(
        self, component: Component, agent_instance: AgentInstance
    ) -> Component:
        """将内联定义合并到组件中。

        用于 workflow 中内联定义的 agent（没有 use，直接在 agent {} 块中定义）。
        """
        merged = copy.deepcopy(component)

        # 合并内联端口
        if agent_instance.inline_ports:
            existing_names = {p.name for p in merged.ports}
            for port in agent_instance.inline_ports:
                if port.name in existing_names:
                    # 同名端口：检查类型是否一致
                    for existing in merged.ports:
                        if existing.name == port.name:
                            if existing.type != port.type:
                                raise PortConflictError(
                                    f"Port '{port.name}' type conflict: "
                                    f"{existing.type} vs {port.type}"
                                )
                else:
                    merged.ports.append(port)

        # 合并内联 system_prompt
        if agent_instance.inline_system_prompt:
            merged.system_prompt = agent_instance.inline_system_prompt

        # 合并内联 model 配置
        raw = agent_instance.overrides
        if "model" in raw:
            merged.model.default = raw["model"]
        if "temperature" in raw:
            merged.model.temperature = raw["temperature"]
        if "max_tokens" in raw:
            merged.model.max_tokens = raw["max_tokens"]
        if "fallback" in raw:
            merged.model.fallback = raw["fallback"]

        return merged

    def create_inline(
        self,
        agent_instance: AgentInstance,
        model: str = "gpt-4",
        system_prompt: Optional[str] = None,
    ) -> ComponentAgent:
        """为内联定义的 agent 创建 ComponentAgent。

        当 workflow 中直接定义 agent（不使用 use）时，将内联属性
        转换为 Component 后创建 ComponentAgent。

        Args:
            agent_instance: workflow 中的 agent 定义
            model: 默认模型
            system_prompt: 默认 system_prompt
        """
        # 从内联定义构建临时 Component
        component = Component(
            name=agent_instance.name,
            system_prompt=agent_instance.inline_system_prompt or system_prompt or "",
            ports=list(agent_instance.inline_ports),
            model=ModelConfig(default=model),
        )

        # 合并 overrides 中的 model 配置
        raw = agent_instance.overrides
        if "model" in raw:
            component.model.default = raw["model"]
        if "temperature" in raw:
            component.model.temperature = raw["temperature"]
        if "max_tokens" in raw:
            component.model.max_tokens = raw["max_tokens"]

        return self.create(agent_instance, component=component)


# ---------------------------------------------------------------------------
# 工作流实例化器
# ---------------------------------------------------------------------------


@dataclass
class InstantiatedWorkflow:
    """实例化后的工作流

    包含所有可执行的 ComponentAgent 和端口映射关系。
    """

    name: str
    agents: Dict[str, ComponentAgent] = field(default_factory=dict)
    port_mappings: List[PortMapping] = field(default_factory=list)
    output_mappings: Dict[str, str] = field(default_factory=dict)
    workflow_ports: List[Port] = field(default_factory=list)


class WorkflowInstantiator:
    """将 DSL v2 Workflow AST 实例化为 InstantiatedWorkflow。

    处理流程：
    1. 解析所有 AgentInstance（use 引用或内联定义）
    2. 创建 ComponentAgent 实例
    3. 将 Connection 转换为 PortMapping
    4. 处理工作流端口和输出映射
    """

    def __init__(self, registry: ComponentRegistry):
        self._registry = registry
        self._factory = ComponentFactory(registry)

    def instantiate(self, workflow: Workflow) -> InstantiatedWorkflow:
        """实例化工作流

        Args:
            workflow: DSL v2 Workflow AST

        Returns:
            实例化后的工作流
        """
        agents: Dict[str, ComponentAgent] = {}

        # 1. 实例化所有 Agent
        for agent_def in workflow.agents:
            if agent_def.component is not None:
                # use 关键字：从 registry 查找组件
                agent = self._factory.create(agent_def)
            else:
                # 内联定义
                agent = self._factory.create_inline(agent_def)
            agents[agent_def.name] = agent

        # 2. 转换连接为端口映射
        mapper = PortMapper(agents)
        port_mappings = mapper.map_connections(workflow.connections)

        # 3. 验证端口映射
        self._validate_mappings(port_mappings, agents)

        return InstantiatedWorkflow(
            name=workflow.name,
            agents=agents,
            port_mappings=port_mappings,
            output_mappings=dict(workflow.output_mappings),
            workflow_ports=list(workflow.ports),
        )

    def _validate_mappings(
        self,
        mappings: List[PortMapping],
        agents: Dict[str, ComponentAgent],
    ) -> None:
        """验证端口映射的合法性

        - 源 agent 和目标 agent 必须存在
        - 源端口必须是 output 端口
        - 目标端口必须是 input 端口
        """
        for mapping in mappings:
            # 跳过聚合源
            if mapping.source_agent == "__aggregate__":
                continue

            source = agents.get(mapping.source_agent)
            if source is None:
                raise PortMappingError(
                    f"Source agent '{mapping.source_agent}' not found"
                )

            target = agents.get(mapping.target_agent)
            if target is None:
                raise PortMappingError(
                    f"Target agent '{mapping.target_agent}' not found"
                )

            # 验证源端口
            src_port = source.get_port(mapping.source_port)
            if src_port is not None and src_port.direction != "output":
                raise PortMappingError(
                    f"Port '{mapping.source_port}' on agent '{mapping.source_agent}' "
                    f"is not an output port"
                )

            # 验证目标端口
            tgt_port = target.get_port(mapping.target_port)
            if tgt_port is not None and tgt_port.direction != "input":
                raise PortMappingError(
                    f"Port '{mapping.target_port}' on agent '{mapping.target_agent}' "
                    f"is not an input port"
                )


# ---------------------------------------------------------------------------
# 数据流路由器
# ---------------------------------------------------------------------------


class DataFlowRouter:
    """运行时数据流路由器。

    根据 PortMapping 在 Agent 之间传递数据。
    """

    def __init__(self, workflow: InstantiatedWorkflow):
        self._workflow = workflow
        self._agent_outputs: Dict[str, Dict[str, Any]] = {}

    def set_agent_output(
        self, agent_name: str, output: Dict[str, Any]
    ) -> None:
        """记录 Agent 的输出数据"""
        self._agent_outputs[agent_name] = output

    def get_agent_input(self, agent_name: str) -> Dict[str, Any]:
        """根据端口映射，收集指定 Agent 的输入数据。

        遍历所有 port_mapping，将 source_agent 的输出中
        source_port 的值，映射到 target_port。

        如果多个源连接到同一端口，数据自动聚合为字典：
            {"source_agent_name": value, ...}

        Returns:
            端口名 -> 值 的字典
        """
        input_data: Dict[str, Any] = {}
        port_sources: Dict[str, List[str]] = {}  # port -> [source_agents]

        for mapping in self._workflow.port_mappings:
            if mapping.target_agent != agent_name:
                continue

            source_output = self._agent_outputs.get(mapping.source_agent, {})
            value = source_output.get(mapping.source_port)

            if mapping.target_port in input_data:
                # 聚合：多个源连接到同一端口
                if mapping.target_port not in port_sources:
                    # 第一次冲突，将已有值包装为字典
                    existing_source = self._find_first_source(
                        agent_name, mapping.target_port
                    )
                    input_data[mapping.target_port] = {
                        existing_source: input_data[mapping.target_port],
                    }
                    port_sources[mapping.target_port] = [existing_source]

                input_data[mapping.target_port][mapping.source_agent] = value
                port_sources[mapping.target_port].append(mapping.source_agent)
            else:
                input_data[mapping.target_port] = value
                port_sources[mapping.target_port] = [mapping.source_agent]

        return input_data

    def _find_first_source(
        self, target_agent: str, target_port: str
    ) -> str:
        """找到第一个映射到指定端口的源 agent"""
        for mapping in self._workflow.port_mappings:
            if (
                mapping.target_agent == target_agent
                and mapping.target_port == target_port
            ):
                return mapping.source_agent
        return "unknown"

    def get_workflow_output(self) -> Dict[str, Any]:
        """收集工作流的输出数据

        根据 output_mappings 从各 Agent 的输出中提取数据。
        """
        result: Dict[str, Any] = {}
        for wf_port, agent_port_spec in self._workflow.output_mappings.items():
            # agent_port_spec 格式: "agent_name.port_name" 或 "agent_name"
            parts = agent_port_spec.split(".", 1)
            agent_name = parts[0]
            port_name = parts[1] if len(parts) > 1 else "out"

            agent_output = self._agent_outputs.get(agent_name, {})
            result[wf_port] = agent_output.get(port_name)

        return result

    def clear(self) -> None:
        self._agent_outputs.clear()

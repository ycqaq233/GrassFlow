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
from typing import Any, Dict, List, Optional, Set

from .agent import Agent

try:
    from core.models import Component, Workflow
except ImportError:
    from .models import Component, Workflow

from .models import (
    AgentInstance,
    Connection,
    MCPConfig,
    ModelConfig,
    PermissionConfig,
    Port,
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
    """单条端口映射关系"""

    source_agent: str
    source_port: str
    target_agent: str
    target_port: str


class PortMapper:
    """将 DSL v2 Connection 列表转换为具体的端口映射列表。"""

    DEFAULT_INPUT_PORT = "in"
    DEFAULT_OUTPUT_PORT = "out"

    def __init__(self, agents: Dict[str, "ComponentAgent"]):
        self._agents = agents

    def _resolve_source_port(self, agent_name: str, port: Optional[str]) -> str:
        if port is not None:
            return port
        agent = self._agents.get(agent_name)
        if agent is not None:
            output_ports = agent.get_output_ports()
            if output_ports:
                return output_ports[0].name
        return self.DEFAULT_OUTPUT_PORT

    def _resolve_target_port(self, agent_name: str, port: Optional[str]) -> str:
        if port is not None:
            return port
        agent = self._agents.get(agent_name)
        if agent is not None:
            input_ports = agent.get_input_ports()
            if input_ports:
                return input_ports[0].name
        return self.DEFAULT_INPUT_PORT

    def map_connections(
        self, connections: List[Connection]
    ) -> List[PortMapping]:
        """将 Connection 列表展开为 PortMapping 列表。"""
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
    """管理组件定义，支持 use 关键字的查找与解析。"""

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
        """递归解析 use 链，返回合并后的最终 Component。"""
        if seen is None:
            seen = set()
        if component.name in seen:
            raise ComponentError(
                f"Circular use reference detected: {' -> '.join(seen)} -> {component.name}"
            )
        seen.add(component.name)

        return copy.deepcopy(component)

    def clear(self) -> None:
        self._components.clear()


# ---------------------------------------------------------------------------
# 组件 Agent
# ---------------------------------------------------------------------------


class ComponentAgent(Agent):
    """从 DSL v2 Component 定义创建的可执行 Agent。"""

    def __init__(
        self,
        component: Component,
        agent_name: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ):
        overrides = overrides or {}

        # 应用覆盖参数到 Component 的副本
        effective = self._apply_overrides(copy.deepcopy(component), overrides)

        super().__init__(effective)

        self._original_component = component
        self._agent_name = agent_name or component.name
        self._overrides = overrides

        # 保留端口定义
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

    @staticmethod
    def _apply_overrides(component: Component, overrides: Dict[str, Any]) -> Component:
        """将覆盖参数应用到 Component"""
        if "model" in overrides:
            component.model.default = overrides["model"]
        if "temperature" in overrides:
            component.model.temperature = overrides["temperature"]
        if "max_tokens" in overrides:
            component.model.max_tokens = overrides["max_tokens"]
        if "fallback" in overrides:
            component.model.fallback = overrides["fallback"]
        if "on_fail" in overrides:
            component.on_fail = overrides["on_fail"]
        if "retry_count" in overrides:
            component.retry_count = overrides["retry_count"]
        return component

    # ---- 端口访问 ----

    def get_input_ports(self) -> List[Port]:
        return [p for p in self._ports.values() if p.direction == "input"]

    def get_output_ports(self) -> List[Port]:
        return [p for p in self._ports.values() if p.direction == "output"]

    def get_port(self, name: str) -> Optional[Port]:
        return self._ports.get(name)

    @property
    def component(self) -> Component:
        return self._original_component

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
        """将 system_prompt 中的 {port_name} 替换为实际输入值。"""
        template = self._component.system_prompt or ""
        if not template:
            return ""

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            value = input_data.get(var_name)
            if value is None:
                return match.group(0)
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return re.sub(r"\{(\w+)\}", replacer, template)

    def _build_llm_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """将端口输入数据转换为 LLM prompt 所需的格式。"""
        rendered = self._render_system_prompt(input_data)
        messages: List[Dict[str, str]] = []
        if rendered:
            messages.append({"role": "system", "content": rendered})

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
            "model": self._component.model.default,
            "temperature": self._overrides.get("temperature"),
            "max_tokens": self._overrides.get("max_tokens"),
            "fallback": self._overrides.get(
                "fallback", self._component.model.fallback
            ),
        }

    # ---- 执行 ----

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行组件 Agent。"""
        llm_request = self._build_llm_input(input_data)

        output: Dict[str, Any] = {}
        for port in self.get_output_ports():
            if port.name in input_data:
                output[port.name] = input_data[port.name]
            else:
                output[port.name] = None

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
    """从 AgentInstance AST 创建可执行的 ComponentAgent。"""

    ALLOWED_OVERRIDE_KEYS: Set[str] = {
        "model", "temperature", "max_tokens", "fallback",
        "on_fail", "retry_count",
    }

    DISALLOWED_OVERRIDE_KEYS: Set[str] = {
        "port", "ports", "system_prompt", "mcp", "permission",
    }

    def __init__(self, registry: ComponentRegistry):
        self._registry = registry

    def validate_overrides(self, overrides: Dict[str, Any]) -> None:
        """验证覆盖参数是否合法。"""
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
        """从 AgentInstance 创建 ComponentAgent。"""
        if component is None:
            if agent_instance.component is None:
                raise ComponentError(
                    f"Agent '{agent_instance.name}' has no component reference "
                    f"and no component was provided."
                )
            component = self._registry.get(agent_instance.component)

        resolved = self._registry.resolve_use_chain(component)
        self.validate_overrides(agent_instance.overrides)

        overrides = self._build_overrides(resolved, agent_instance)

        if agent_instance.inline_ports:
            resolved = self._merge_inline_definition(resolved, agent_instance)

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

        for key in ("model", "temperature", "max_tokens", "fallback", "on_fail", "retry_count"):
            if key in raw:
                overrides[key] = raw[key]

        return overrides

    def _merge_inline_definition(
        self, component: Component, agent_instance: AgentInstance
    ) -> Component:
        """将内联定义合并到组件中。"""
        merged = copy.deepcopy(component)

        if agent_instance.inline_ports:
            existing_names = {p.name for p in merged.ports}
            for port in agent_instance.inline_ports:
                if port.name in existing_names:
                    for existing in merged.ports:
                        if existing.name == port.name:
                            if existing.type != port.type:
                                raise PortConflictError(
                                    f"Port '{port.name}' type conflict: "
                                    f"{existing.type} vs {port.type}"
                                )
                else:
                    merged.ports.append(port)

        if agent_instance.inline_system_prompt:
            merged.system_prompt = agent_instance.inline_system_prompt

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
        """为内联定义的 agent 创建 ComponentAgent。"""
        component = Component(
            name=agent_instance.name,
            system_prompt=agent_instance.inline_system_prompt or system_prompt or "",
            ports=list(agent_instance.inline_ports),
            model=ModelConfig(default=model),
        )

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
    """实例化后的工作流"""

    name: str
    agents: Dict[str, ComponentAgent] = field(default_factory=dict)
    port_mappings: List[PortMapping] = field(default_factory=list)
    output_mappings: Dict[str, str] = field(default_factory=dict)
    workflow_ports: List[Port] = field(default_factory=list)


class WorkflowInstantiator:
    """将 DSL v2 Workflow AST 实例化为 InstantiatedWorkflow。"""

    def __init__(self, registry: ComponentRegistry):
        self._registry = registry
        self._factory = ComponentFactory(registry)

    def instantiate(self, workflow: Workflow) -> InstantiatedWorkflow:
        """实例化工作流"""
        agents: Dict[str, ComponentAgent] = {}

        for agent_def in workflow.agents:
            if agent_def.component is not None:
                agent = self._factory.create(agent_def)
            else:
                agent = self._factory.create_inline(agent_def)
            agents[agent_def.name] = agent

        mapper = PortMapper(agents)
        port_mappings = mapper.map_connections(workflow.connections)

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
        """验证端口映射的合法性"""
        for mapping in mappings:
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

            src_port = source.get_port(mapping.source_port)
            if src_port is not None and src_port.direction != "output":
                raise PortMappingError(
                    f"Port '{mapping.source_port}' on agent '{mapping.source_agent}' "
                    f"is not an output port"
                )

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
    """运行时数据流路由器。"""

    def __init__(self, workflow: InstantiatedWorkflow):
        self._workflow = workflow
        self._agent_outputs: Dict[str, Dict[str, Any]] = {}

    def set_agent_output(
        self, agent_name: str, output: Dict[str, Any]
    ) -> None:
        """记录 Agent 的输出数据"""
        self._agent_outputs[agent_name] = output

    def get_agent_input(self, agent_name: str) -> Dict[str, Any]:
        """根据端口映射，收集指定 Agent 的输入数据。"""
        input_data: Dict[str, Any] = {}
        port_sources: Dict[str, List[str]] = {}

        for mapping in self._workflow.port_mappings:
            if mapping.target_agent != agent_name:
                continue

            source_output = self._agent_outputs.get(mapping.source_agent, {})
            value = source_output.get(mapping.source_port)

            if mapping.target_port in port_sources:
                if len(port_sources[mapping.target_port]) == 1:
                    first_source = port_sources[mapping.target_port][0]
                    input_data[mapping.target_port] = {
                        first_source: input_data[mapping.target_port],
                    }
                input_data[mapping.target_port][mapping.source_agent] = value
                port_sources[mapping.target_port].append(mapping.source_agent)
            else:
                input_data[mapping.target_port] = value
                port_sources[mapping.target_port] = [mapping.source_agent]

        return input_data

    def get_workflow_output(self) -> Dict[str, Any]:
        """收集工作流的输出数据"""
        result: Dict[str, Any] = {}
        for wf_port, agent_port_spec in self._workflow.output_mappings.items():
            parts = agent_port_spec.split(".", 1)
            agent_name = parts[0]
            port_name = parts[1] if len(parts) > 1 else "out"

            agent_output = self._agent_outputs.get(agent_name, {})
            result[wf_port] = agent_output.get(port_name)

        return result

    def clear(self) -> None:
        self._agent_outputs.clear()

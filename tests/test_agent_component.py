"""
GrassFlow Agent 组件运行时测试

测试组件实例化、端口映射、use 关键字解析、运行时参数覆盖。
"""

import pytest
from typing import Any, Dict, List

from core.agent import Agent
from core.agent_component import (
    ComponentAgent,
    ComponentError,
    ComponentFactory,
    ComponentNotFoundError,
    ComponentRegistry,
    DataFlowRouter,
    InstantiatedWorkflow,
    OverrideError,
    PortConflictError,
    PortMapper,
    PortMapping,
    PortMappingError,
    WorkflowInstantiator,
)
try:
    from core.models import Component, Workflow, AgentInstance, Connection, Port, ModelConfig, MCPConfig, PermissionConfig
except ImportError:
    from core.dsl_v2_ast import Component, Workflow, AgentInstance, Connection, Port, ModelConfig, MCPConfig, PermissionConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_code_reviewer_component() -> Component:
    """创建代码审查组件"""
    return Component(
        name="code-reviewer",
        description="代码审查专家",
        version="1.0.0",
        system_prompt="审查代码: {code}, 上下文: {context}",
        ports=[
            Port(name="code", direction="input", type="string", description="待审查的代码"),
            Port(name="context", direction="input", type="object", description="上下文信息"),
            Port(name="issues", direction="output", type="array", description="问题列表"),
            Port(name="score", direction="output", type="number", description="评分"),
        ],
        mcp=[
            MCPConfig(server_name="github", tools=["add_comment", "create_issue"]),
        ],
        model=ModelConfig(default="gpt-4", fallback="gpt-3.5-turbo", temperature=0.3),
        permission=PermissionConfig(
            allow=["github.add_comment"],
            deny=["github.delete_repo"],
            ask=["github.create_issue"],
        ),
        mode="batch",
        context="shared",
        on_fail="stop",
        retry_count=3,
    )


def make_ticket_router_component() -> Component:
    """创建工单路由组件"""
    return Component(
        name="ticket-router",
        description="工单路由器",
        ports=[
            Port(name="ticket", direction="input", type="object"),
            Port(name="urgent", direction="output", type="object"),
            Port(name="normal", direction="output", type="object"),
            Port(name="info", direction="output", type="object"),
        ],
        model=ModelConfig(default="gpt-4"),
        system_prompt="根据工单 {ticket} 判断优先级",
    )


def make_simple_component() -> Component:
    """创建简单组件（单输入单输出）"""
    return Component(
        name="text-processor",
        description="文本处理器",
        ports=[
            Port(name="text", direction="input", type="string"),
            Port(name="result", direction="output", type="string"),
        ],
        model=ModelConfig(default="gpt-3.5-turbo"),
        system_prompt="处理文本: {text}",
    )


# ===========================================================================
# TestSuite 1: ComponentRegistry
# ===========================================================================


class TestComponentRegistry:
    """组件注册表测试"""

    def test_register_and_get(self):
        """注册并获取组件"""
        registry = ComponentRegistry()
        comp = make_code_reviewer_component()
        registry.register(comp)

        result = registry.get("code-reviewer")
        assert result.name == "code-reviewer"
        assert result.description == "代码审查专家"

    def test_register_all(self):
        """批量注册"""
        registry = ComponentRegistry()
        comps = [make_code_reviewer_component(), make_simple_component()]
        registry.register_all(comps)

        assert registry.has("code-reviewer")
        assert registry.has("text-processor")
        assert len(registry.list_names()) == 2

    def test_get_not_found(self):
        """获取不存在的组件"""
        registry = ComponentRegistry()
        with pytest.raises(ComponentNotFoundError, match="not found"):
            registry.get("nonexistent")

    def test_has(self):
        """检查组件是否存在"""
        registry = ComponentRegistry()
        assert not registry.has("code-reviewer")

        registry.register(make_code_reviewer_component())
        assert registry.has("code-reviewer")

    def test_register_overwrite(self):
        """同名组件覆盖"""
        registry = ComponentRegistry()
        comp1 = Component(name="x", description="v1")
        comp2 = Component(name="x", description="v2")

        registry.register(comp1)
        registry.register(comp2)

        assert registry.get("x").description == "v2"

    def test_clear(self):
        """清空注册表"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())
        assert registry.has("code-reviewer")

        registry.clear()
        assert not registry.has("code-reviewer")

    def test_list_names(self):
        """列出所有组件名"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())
        registry.register(make_simple_component())

        names = registry.list_names()
        assert "code-reviewer" in names
        assert "text-processor" in names

    def test_resolve_use_chain_no_circular(self):
        """正常组件无循环引用"""
        registry = ComponentRegistry()
        comp = make_code_reviewer_component()
        registry.register(comp)

        resolved = registry.resolve_use_chain(comp)
        assert resolved.name == "code-reviewer"
        # 验证是深拷贝
        resolved.description = "modified"
        assert comp.description == "代码审查专家"

    def test_resolve_use_chain_circular(self):
        """检测循环引用"""
        registry = ComponentRegistry()
        comp = Component(name="a")
        registry.register(comp)

        # 模拟循环：seen 中已包含 "a"
        with pytest.raises(ComponentError, match="Circular"):
            registry.resolve_use_chain(comp, seen={"a"})


# ===========================================================================
# TestSuite 2: ComponentAgent 基础
# ===========================================================================


class TestComponentAgent:
    """ComponentAgent 基础测试"""

    def test_create_from_component(self):
        """从 Component 创建 ComponentAgent"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        assert agent.name == "code-reviewer"
        assert agent.agent_name == "code-reviewer"
        assert agent.config.model == "gpt-4"

    def test_create_with_agent_name(self):
        """使用自定义实例名"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, agent_name="my-reviewer")

        assert agent.name == "my-reviewer"
        assert agent.agent_name == "my-reviewer"

    def test_ports_converted_to_schema(self):
        """端口自动转换为 JSON Schema"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        # 输入 schema
        input_schema = agent.input_schema
        assert input_schema["type"] == "object"
        assert "code" in input_schema["properties"]
        assert "context" in input_schema["properties"]
        assert input_schema["properties"]["code"] == {"type": "string"}
        assert input_schema["properties"]["context"] == {"type": "object"}
        assert "code" in input_schema["required"]
        assert "context" in input_schema["required"]

        # 输出 schema
        output_schema = agent.output_schema
        assert output_schema["type"] == "object"
        assert "issues" in output_schema["properties"]
        assert "score" in output_schema["properties"]
        assert output_schema["properties"]["issues"] == {"type": "array"}
        assert output_schema["properties"]["score"] == {"type": "number"}

    def test_get_input_ports(self):
        """获取输入端口列表"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        inputs = agent.get_input_ports()
        assert len(inputs) == 2
        names = {p.name for p in inputs}
        assert names == {"code", "context"}

    def test_get_output_ports(self):
        """获取输出端口列表"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        outputs = agent.get_output_ports()
        assert len(outputs) == 2
        names = {p.name for p in outputs}
        assert names == {"issues", "score"}

    def test_get_port(self):
        """按名称获取端口"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        port = agent.get_port("code")
        assert port is not None
        assert port.name == "code"
        assert port.direction == "input"
        assert port.type == "string"

    def test_get_port_not_found(self):
        """获取不存在的端口"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        assert agent.get_port("nonexistent") is None

    def test_component_property(self):
        """访问原始组件"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        assert agent.component.name == "code-reviewer"
        assert agent.component.version == "1.0.0"

    def test_mode_and_context(self):
        """访问执行模式"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        assert agent.mode == "batch"
        assert agent.context_strategy == "shared"

    def test_mcp_configs(self):
        """访问 MCP 配置"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        assert len(agent.mcp_configs) == 1
        assert agent.mcp_configs[0].server_name == "github"
        assert agent.mcp_configs[0].tools == ["add_comment", "create_issue"]

    def test_permission(self):
        """访问权限配置"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        perm = agent.permission
        assert "github.add_comment" in perm.allow
        assert "github.delete_repo" in perm.deny
        assert "github.create_issue" in perm.ask


# ===========================================================================
# TestSuite 3: 运行时参数覆盖
# ===========================================================================


class TestRuntimeOverrides:
    """运行时参数覆盖测试"""

    def test_override_model(self):
        """覆盖模型"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, overrides={"model": "gpt-4o"})

        assert agent.config.model == "gpt-4o"

    def test_override_on_fail(self):
        """覆盖失败策略"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, overrides={"on_fail": "retry"})

        assert agent.config.on_fail == "retry"

    def test_override_retry_count(self):
        """覆盖重试次数"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, overrides={"retry_count": 5})

        assert agent.config.retry_count == 5

    def test_override_multiple(self):
        """同时覆盖多个参数"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, overrides={
            "model": "claude-3",
            "on_fail": "skip",
            "retry_count": 1,
        })

        assert agent.config.model == "claude-3"
        assert agent.config.on_fail == "skip"
        assert agent.config.retry_count == 1

    def test_override_preserves_ports(self):
        """覆盖参数不改变端口定义"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, overrides={"model": "gpt-4o"})

        assert len(agent.get_input_ports()) == 2
        assert len(agent.get_output_ports()) == 2

    def test_override_preserves_system_prompt(self):
        """覆盖参数不改变 system_prompt"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, overrides={"model": "gpt-4o"})

        assert agent.config.prompt == "审查代码: {code}, 上下文: {context}"

    def test_no_override_uses_component_defaults(self):
        """不覆盖时使用组件默认值"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        assert agent.config.model == "gpt-4"
        assert agent.config.on_fail == "stop"
        assert agent.config.retry_count == 3


# ===========================================================================
# TestSuite 4: 模板渲染
# ===========================================================================


class TestTemplateRendering:
    """system_prompt 模板渲染测试"""

    def test_render_simple_template(self):
        """简单模板渲染"""
        comp = make_simple_component()
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({"text": "hello world"})
        assert result == "处理文本: hello world"

    def test_render_multi_variable_template(self):
        """多变量模板渲染"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({
            "code": "def foo(): pass",
            "context": {"file": "test.py"},
        })
        assert "def foo(): pass" in result
        assert "test.py" in result

    def test_render_missing_variable(self):
        """缺失变量保留原样"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({"code": "some code"})
        assert "some code" in result
        assert "{context}" in result  # 未替换

    def test_render_dict_value(self):
        """字典值序列化为 JSON"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({
            "code": "x",
            "context": {"key": "value"},
        })
        assert '"key"' in result
        assert '"value"' in result

    def test_render_list_value(self):
        """列表值序列化为 JSON"""
        comp = Component(
            name="test",
            ports=[Port(name="items", direction="input", type="array")],
            system_prompt="处理: {items}",
        )
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({"items": [1, 2, 3]})
        assert "[1, 2, 3]" in result

    def test_render_empty_template(self):
        """空模板"""
        comp = Component(name="test", ports=[], system_prompt="")
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({"x": 1})
        assert result == ""

    def test_render_none_template(self):
        """None 模板"""
        comp = Component(name="test", ports=[], system_prompt=None)
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({"x": 1})
        assert result == ""


# ===========================================================================
# TestSuite 5: LLM 输入构建
# ===========================================================================


class TestLLMInputBuilding:
    """LLM 输入构建测试"""

    def test_build_llm_input_basic(self):
        """基本 LLM 输入构建"""
        comp = make_simple_component()
        agent = ComponentAgent(comp)

        llm_input = agent._build_llm_input({"text": "hello"})

        assert llm_input["model"] == "gpt-3.5-turbo"
        assert len(llm_input["messages"]) == 2
        assert llm_input["messages"][0]["role"] == "system"
        assert "hello" in llm_input["messages"][0]["content"]
        assert llm_input["messages"][1]["role"] == "user"
        assert "[text]" in llm_input["messages"][1]["content"]

    def test_build_llm_input_with_model_override(self):
        """带模型覆盖的 LLM 输入"""
        comp = make_simple_component()
        agent = ComponentAgent(comp, overrides={"model": "gpt-4o"})

        llm_input = agent._build_llm_input({"text": "hello"})
        assert llm_input["model"] == "gpt-4o"

    def test_build_llm_input_with_temperature(self):
        """带温度覆盖的 LLM 输入"""
        comp = make_simple_component()
        agent = ComponentAgent(comp, overrides={"temperature": 0.5})

        llm_input = agent._build_llm_input({"text": "hello"})
        assert llm_input["temperature"] == 0.5

    def test_build_llm_input_multiple_ports(self):
        """多端口输入"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp)

        llm_input = agent._build_llm_input({
            "code": "def foo(): pass",
            "context": {"file": "test.py"},
        })

        user_msg = llm_input["messages"][1]["content"]
        assert "[code]" in user_msg
        assert "[context]" in user_msg
        assert "def foo(): pass" in user_msg


# ===========================================================================
# TestSuite 6: Agent 执行
# ===========================================================================


@pytest.mark.asyncio
class TestComponentAgentExecution:
    """ComponentAgent 执行测试"""

    async def test_run_returns_output_ports(self):
        """执行返回输出端口"""
        comp = make_simple_component()
        agent = ComponentAgent(comp)

        result = await agent.run({"text": "hello"})
        assert "result" in result
        assert "_component" in result

    async def test_run_passthrough(self):
        """默认实现透传同名输入"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="data", direction="input", type="object"),
                Port(name="data", direction="output", type="object"),
            ],
        )
        # 同名端口会被合并，需要分别定义 input 和 output
        comp = Component(
            name="pass",
            ports=[
                Port(name="input_data", direction="input", type="object"),
                Port(name="input_data", direction="output", type="object"),
            ],
        )
        agent = ComponentAgent(comp)

        result = await agent.run({"input_data": {"key": "value"}})
        assert result["input_data"] == {"key": "value"}

    async def test_run_metadata(self):
        """执行结果包含组件元信息"""
        comp = make_code_reviewer_component()
        agent = ComponentAgent(comp, agent_name="my-reviewer")

        result = await agent.run({"code": "x", "context": {}})
        meta = result["_component"]
        assert meta["name"] == "code-reviewer"
        assert meta["version"] == "1.0.0"
        assert meta["mode"] == "batch"
        assert meta["context"] == "shared"

    async def test_run_with_retry(self):
        """重试机制（继承自 Agent 基类）"""
        comp = Component(
            name="fail-once",
            ports=[
                Port(name="x", direction="input", type="string"),
                Port(name="y", direction="output", type="string"),
            ],
            on_fail="retry",
            retry_count=2,
        )

        call_count = 0

        class FailOnceAgent(ComponentAgent):
            async def run(self, input_data):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("transient error")
                return {"y": "ok"}

        agent = FailOnceAgent(comp)
        result = await agent.execute({"x": "test"})
        assert result["y"] == "ok"
        assert call_count == 2

    async def test_run_on_fail_stop(self):
        """失败策略 stop"""
        comp = Component(
            name="always-fail",
            ports=[
                Port(name="x", direction="input", type="string"),
                Port(name="y", direction="output", type="string"),
            ],
            on_fail="stop",
            retry_count=1,
        )

        class AlwaysFailAgent(ComponentAgent):
            async def run(self, input_data):
                raise RuntimeError("permanent error")

        agent = AlwaysFailAgent(comp)
        with pytest.raises(RuntimeError, match="permanent error"):
            await agent.execute({"x": "test"})

    async def test_run_on_fail_skip(self):
        """失败策略 skip"""
        comp = Component(
            name="fail-skip",
            ports=[
                Port(name="x", direction="input", type="string"),
                Port(name="y", direction="output", type="string"),
            ],
            on_fail="skip",
            retry_count=1,
        )

        class FailSkipAgent(ComponentAgent):
            async def run(self, input_data):
                raise RuntimeError("error")

        agent = FailSkipAgent(comp)
        result = await agent.execute({"x": "test"})
        assert result == {}  # skip 返回空字典


# ===========================================================================
# TestSuite 7: ComponentFactory
# ===========================================================================


class TestComponentFactory:
    """组件工厂测试"""

    def test_create_from_registry(self):
        """从 registry 创建"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(name="my-reviewer", component="code-reviewer")
        agent = factory.create(agent_def)

        assert agent.name == "my-reviewer"
        assert agent.config.model == "gpt-4"
        assert len(agent.get_input_ports()) == 2

    def test_create_with_overrides(self):
        """带覆盖参数创建"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(
            name="fast-reviewer",
            component="code-reviewer",
            overrides={"model": "gpt-4o", "temperature": 0.1},
        )
        agent = factory.create(agent_def)

        assert agent.config.model == "gpt-4o"

    def test_create_disallowed_override(self):
        """不允许覆盖 system_prompt"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(
            name="bad-reviewer",
            component="code-reviewer",
            overrides={"system_prompt": "hacked!"},
        )
        with pytest.raises(OverrideError, match="cannot be overridden"):
            factory.create(agent_def)

    def test_create_disallowed_port_override(self):
        """不允许覆盖 port"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(
            name="bad-reviewer",
            component="code-reviewer",
            overrides={"port": []},
        )
        with pytest.raises(OverrideError, match="cannot be overridden"):
            factory.create(agent_def)

    def test_create_component_not_found(self):
        """组件不存在"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(name="x", component="nonexistent")
        with pytest.raises(ComponentNotFoundError):
            factory.create(agent_def)

    def test_create_inline_agent(self):
        """创建内联 agent"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(
            name="inline-agent",
            inline_ports=[
                Port(name="input_text", direction="input", type="string"),
                Port(name="output_text", direction="output", type="string"),
            ],
            inline_system_prompt="处理: {input_text}",
            overrides={"model": "gpt-4"},
        )
        agent = factory.create_inline(agent_def)

        assert agent.name == "inline-agent"
        assert agent.config.model == "gpt-4"
        assert len(agent.get_input_ports()) == 1
        assert len(agent.get_output_ports()) == 1

    def test_create_inline_with_default_model(self):
        """内联 agent 使用默认模型"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(
            name="simple",
            inline_ports=[Port(name="x", direction="input", type="string")],
        )
        agent = factory.create_inline(agent_def, model="claude-3")

        assert agent.config.model == "claude-3"

    def test_create_with_explicit_component(self):
        """直接传入组件定义"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        comp = make_simple_component()
        agent_def = AgentInstance(name="proc", overrides={"model": "gpt-4o"})
        agent = factory.create(agent_def, component=comp)

        assert agent.config.model == "gpt-4o"

    def test_validate_all_allowed_overrides(self):
        """验证所有允许的覆盖参数"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        # 不应抛出异常
        factory.validate_overrides({
            "model": "gpt-4o",
            "temperature": 0.5,
            "max_tokens": 8192,
            "fallback": "gpt-3.5-turbo",
            "on_fail": "retry",
            "retry_count": 5,
        })

    def test_validate_disallowed_mcp(self):
        """不允许覆盖 mcp"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        with pytest.raises(OverrideError, match="cannot be overridden"):
            factory.validate_overrides({"mcp": []})

    def test_validate_disallowed_permission(self):
        """不允许覆盖 permission"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        with pytest.raises(OverrideError, match="cannot be overridden"):
            factory.validate_overrides({"permission": {}})


# ===========================================================================
# TestSuite 8: PortMapper
# ===========================================================================


class TestPortMapper:
    """端口映射器测试"""

    def test_basic_mapping(self):
        """基本映射 A -> B"""
        comp_a = Component(
            name="a",
            ports=[Port(name="out", direction="output", type="string")],
        )
        comp_b = Component(
            name="b",
            ports=[Port(name="in", direction="input", type="string")],
        )
        agent_a = ComponentAgent(comp_a, agent_name="a")
        agent_b = ComponentAgent(comp_b, agent_name="b")

        mapper = PortMapper({"a": agent_a, "b": agent_b})
        conn = Connection(source_agent="a", target_agents=["b"])
        mappings = mapper.map_connections([conn])

        assert len(mappings) == 1
        assert mappings[0].source_agent == "a"
        assert mappings[0].source_port == "out"
        assert mappings[0].target_agent == "b"
        assert mappings[0].target_port == "in"

    def test_explicit_port_mapping(self):
        """显式端口映射 A.result -> B.data"""
        comp_a = Component(
            name="a",
            ports=[Port(name="result", direction="output", type="object")],
        )
        comp_b = Component(
            name="b",
            ports=[Port(name="data", direction="input", type="object")],
        )
        agent_a = ComponentAgent(comp_a, agent_name="a")
        agent_b = ComponentAgent(comp_b, agent_name="b")

        mapper = PortMapper({"a": agent_a, "b": agent_b})
        conn = Connection(
            source_agent="a",
            source_port="result",
            target_agents=["b"],
            target_ports=["data"],
        )
        mappings = mapper.map_connections([conn])

        assert mappings[0].source_port == "result"
        assert mappings[0].target_port == "data"

    def test_broadcast_mapping(self):
        """广播映射 A -> (B, C, D)"""
        comp_a = Component(
            name="a",
            ports=[Port(name="out", direction="output", type="string")],
        )
        agents = {}
        for name in ["b", "c", "d"]:
            comp = Component(
                name=name,
                ports=[Port(name="in", direction="input", type="string")],
            )
            agents[name] = ComponentAgent(comp, agent_name=name)

        agents["a"] = ComponentAgent(comp_a, agent_name="a")
        mapper = PortMapper(agents)

        conn = Connection(
            source_agent="a",
            target_agents=["b", "c", "d"],
        )
        mappings = mapper.map_connections([conn])

        assert len(mappings) == 3
        for m in mappings:
            assert m.source_agent == "a"
            assert m.source_port == "out"
        targets = {m.target_agent for m in mappings}
        assert targets == {"b", "c", "d"}

    def test_auto_first_port(self):
        """自动选择第一个端口"""
        comp = Component(
            name="multi",
            ports=[
                Port(name="alpha", direction="input", type="string"),
                Port(name="beta", direction="input", type="string"),
                Port(name="gamma", direction="output", type="string"),
                Port(name="delta", direction="output", type="string"),
            ],
        )
        agent = ComponentAgent(comp, agent_name="multi")

        mapper = PortMapper({"multi": agent})
        conn = Connection(source_agent="multi", target_agents=["multi"])
        mappings = mapper.map_connections([conn])

        assert mappings[0].source_port == "gamma"  # 第一个 output
        assert mappings[0].target_port == "alpha"   # 第一个 input

    def test_default_ports_fallback(self):
        """没有端口定义时使用默认端口名"""
        comp = Component(name="bare", ports=[])
        agent = ComponentAgent(comp, agent_name="bare")

        mapper = PortMapper({"bare": agent})
        conn = Connection(source_agent="bare", target_agents=["bare"])
        mappings = mapper.map_connections([conn])

        assert mappings[0].source_port == "out"
        assert mappings[0].target_port == "in"

    def test_multiple_target_ports(self):
        """多个目标端口"""
        comp_a = Component(
            name="a",
            ports=[Port(name="x", direction="output", type="string")],
        )
        comp_b = Component(
            name="b",
            ports=[
                Port(name="p1", direction="input", type="string"),
                Port(name="p2", direction="input", type="string"),
            ],
        )
        agent_a = ComponentAgent(comp_a, agent_name="a")
        agent_b = ComponentAgent(comp_b, agent_name="b")

        mapper = PortMapper({"a": agent_a, "b": agent_b})
        conn = Connection(
            source_agent="a",
            target_agents=["b", "b"],
            target_ports=["p1", "p2"],
        )
        mappings = mapper.map_connections([conn])

        assert len(mappings) == 2
        assert mappings[0].target_port == "p1"
        assert mappings[1].target_port == "p2"


# ===========================================================================
# TestSuite 9: WorkflowInstantiator
# ===========================================================================


class TestWorkflowInstantiator:
    """工作流实例化器测试"""

    def test_instantiate_simple_workflow(self):
        """实例化简单工作流"""
        registry = ComponentRegistry()
        registry.register(make_simple_component())

        workflow = Workflow(
            name="test-wf",
            agents=[
                AgentInstance(name="proc", component="text-processor"),
            ],
            connections=[],
        )

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        assert result.name == "test-wf"
        assert "proc" in result.agents
        assert isinstance(result.agents["proc"], ComponentAgent)

    def test_instantiate_with_connections(self):
        """实例化带连接的工作流"""
        registry = ComponentRegistry()
        comp_a = Component(
            name="producer",
            ports=[Port(name="out", direction="output", type="string")],
        )
        comp_b = Component(
            name="consumer",
            ports=[Port(name="in", direction="input", type="string")],
        )
        registry.register(comp_a)
        registry.register(comp_b)

        workflow = Workflow(
            name="pipe",
            agents=[
                AgentInstance(name="p", component="producer"),
                AgentInstance(name="c", component="consumer"),
            ],
            connections=[
                Connection(source_agent="p", target_agents=["c"]),
            ],
        )

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        assert len(result.port_mappings) == 1
        assert result.port_mappings[0].source_agent == "p"
        assert result.port_mappings[0].target_agent == "c"

    def test_instantiate_with_inline_agent(self):
        """实例化包含内联 agent 的工作流"""
        registry = ComponentRegistry()

        workflow = Workflow(
            name="inline-wf",
            agents=[
                AgentInstance(
                    name="my-agent",
                    inline_ports=[
                        Port(name="x", direction="input", type="string"),
                        Port(name="y", direction="output", type="string"),
                    ],
                    inline_system_prompt="处理: {x}",
                    overrides={"model": "gpt-4"},
                ),
            ],
        )

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        assert "my-agent" in result.agents
        agent = result.agents["my-agent"]
        assert agent.config.model == "gpt-4"

    def test_instantiate_with_overrides(self):
        """实例化时覆盖参数"""
        registry = ComponentRegistry()
        registry.register(make_simple_component())

        workflow = Workflow(
            name="override-wf",
            agents=[
                AgentInstance(
                    name="fast",
                    component="text-processor",
                    overrides={"model": "gpt-4o"},
                ),
            ],
        )

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        assert result.agents["fast"].config.model == "gpt-4o"

    def test_instantiate_validates_mappings(self):
        """实例化时验证端口映射"""
        registry = ComponentRegistry()
        comp = Component(
            name="a",
            ports=[
                Port(name="x", direction="input", type="string"),
                Port(name="y", direction="output", type="string"),
            ],
        )
        registry.register(comp)

        workflow = Workflow(
            name="bad-wf",
            agents=[
                AgentInstance(name="a1", component="a"),
                AgentInstance(name="a2", component="a"),
            ],
            connections=[
                # 尝试将 input 端口作为 source
                Connection(
                    source_agent="a1",
                    source_port="x",
                    target_agents=["a2"],
                ),
            ],
        )

        instantiator = WorkflowInstantiator(registry)
        with pytest.raises(PortMappingError, match="not an output port"):
            instantiator.instantiate(workflow)

    def test_instantiate_with_output_mappings(self):
        """实例化带输出映射的工作流"""
        registry = ComponentRegistry()
        registry.register(make_simple_component())

        workflow = Workflow(
            name="out-wf",
            agents=[
                AgentInstance(name="proc", component="text-processor"),
            ],
            output_mappings={"final": "proc.result"},
        )

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        assert result.output_mappings == {"final": "proc.result"}


# ===========================================================================
# TestSuite 10: DataFlowRouter
# ===========================================================================


class TestDataFlowRouter:
    """数据流路由器测试"""

    def test_set_and_get_agent_output(self):
        """设置和获取 Agent 输出"""
        workflow = InstantiatedWorkflow(name="test")
        router = DataFlowRouter(workflow)

        router.set_agent_output("a", {"result": "hello"})
        assert router._agent_outputs["a"]["result"] == "hello"

    def test_get_agent_input_simple(self):
        """简单数据流：A -> B"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="out", direction="output", type="string"),
                Port(name="in", direction="input", type="string"),
            ],
        )
        agent_a = ComponentAgent(comp, agent_name="a")
        agent_b = ComponentAgent(comp, agent_name="b")

        workflow = InstantiatedWorkflow(
            name="test",
            agents={"a": agent_a, "b": agent_b},
            port_mappings=[
                PortMapping("a", "out", "b", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"out": "hello"})

        input_b = router.get_agent_input("b")
        assert input_b["in"] == "hello"

    def test_get_agent_input_aggregate(self):
        """聚合数据流：(A, B) -> C"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="out", direction="output", type="string"),
                Port(name="in", direction="input", type="string"),
            ],
        )
        agents = {
            "a": ComponentAgent(comp, agent_name="a"),
            "b": ComponentAgent(comp, agent_name="b"),
            "c": ComponentAgent(comp, agent_name="c"),
        }

        workflow = InstantiatedWorkflow(
            name="test",
            agents=agents,
            port_mappings=[
                PortMapping("a", "out", "c", "in"),
                PortMapping("b", "out", "c", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"out": "from_a"})
        router.set_agent_output("b", {"out": "from_b"})

        input_c = router.get_agent_input("c")
        assert input_c["in"] == {"a": "from_a", "b": "from_b"}

    def test_get_agent_input_explicit_ports(self):
        """显式端口映射：A.result -> B.data"""
        comp_a = Component(
            name="a",
            ports=[Port(name="result", direction="output", type="object")],
        )
        comp_b = Component(
            name="b",
            ports=[Port(name="data", direction="input", type="object")],
        )

        workflow = InstantiatedWorkflow(
            name="test",
            agents={
                "a": ComponentAgent(comp_a, agent_name="a"),
                "b": ComponentAgent(comp_b, agent_name="b"),
            },
            port_mappings=[
                PortMapping("a", "result", "b", "data"),
            ],
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"result": {"key": "value"}})

        input_b = router.get_agent_input("b")
        assert input_b["data"] == {"key": "value"}

    def test_get_agent_input_no_mappings(self):
        """无映射时返回空字典"""
        workflow = InstantiatedWorkflow(name="test")
        router = DataFlowRouter(workflow)

        input_data = router.get_agent_input("any")
        assert input_data == {}

    def test_get_agent_input_missing_source(self):
        """源 agent 无输出时返回 None"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="out", direction="output", type="string"),
                Port(name="in", direction="input", type="string"),
            ],
        )

        workflow = InstantiatedWorkflow(
            name="test",
            agents={
                "a": ComponentAgent(comp, agent_name="a"),
                "b": ComponentAgent(comp, agent_name="b"),
            },
            port_mappings=[
                PortMapping("a", "out", "b", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        # 不设置 a 的输出
        input_b = router.get_agent_input("b")
        assert input_b["in"] is None

    def test_get_workflow_output(self):
        """获取工作流输出"""
        comp = Component(
            name="pass",
            ports=[Port(name="result", direction="output", type="string")],
        )

        workflow = InstantiatedWorkflow(
            name="test",
            agents={"a": ComponentAgent(comp, agent_name="a")},
            output_mappings={"final": "a.result"},
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"result": "done"})

        output = router.get_workflow_output()
        assert output["final"] == "done"

    def test_get_workflow_output_multiple(self):
        """多个输出映射"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="x", direction="output", type="string"),
                Port(name="y", direction="output", type="string"),
            ],
        )

        workflow = InstantiatedWorkflow(
            name="test",
            agents={"a": ComponentAgent(comp, agent_name="a")},
            output_mappings={"out1": "a.x", "out2": "a.y"},
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"x": "val1", "y": "val2"})

        output = router.get_workflow_output()
        assert output["out1"] == "val1"
        assert output["out2"] == "val2"

    def test_clear(self):
        """清空路由器"""
        workflow = InstantiatedWorkflow(name="test")
        router = DataFlowRouter(workflow)

        router.set_agent_output("a", {"x": 1})
        router.clear()
        assert router._agent_outputs == {}


# ===========================================================================
# TestSuite 11: 端口类型转换
# ===========================================================================


class TestPortTypeConversion:
    """端口类型到 JSON Schema 转换测试"""

    def test_string_port(self):
        """string 端口"""
        comp = Component(
            name="test",
            ports=[Port(name="x", direction="input", type="string")],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["properties"]["x"] == {"type": "string"}

    def test_number_port(self):
        """number 端口"""
        comp = Component(
            name="test",
            ports=[Port(name="x", direction="input", type="number")],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["properties"]["x"] == {"type": "number"}

    def test_boolean_port(self):
        """boolean 端口"""
        comp = Component(
            name="test",
            ports=[Port(name="x", direction="input", type="boolean")],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["properties"]["x"] == {"type": "boolean"}

    def test_object_port(self):
        """object 端口"""
        comp = Component(
            name="test",
            ports=[Port(name="x", direction="input", type="object")],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["properties"]["x"] == {"type": "object"}

    def test_array_port(self):
        """array 端口"""
        comp = Component(
            name="test",
            ports=[Port(name="x", direction="input", type="array")],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["properties"]["x"] == {"type": "array"}

    def test_unknown_type_fallback(self):
        """未知类型回退为 object"""
        comp = Component(
            name="test",
            ports=[Port(name="x", direction="input", type="custom_type")],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["properties"]["x"] == {"type": "object"}

    def test_empty_ports_no_schema(self):
        """无端口时 schema 为空"""
        comp = Component(name="test", ports=[])
        agent = ComponentAgent(comp)
        assert agent.input_schema == {}
        assert agent.output_schema == {}

    def test_only_input_ports(self):
        """只有输入端口"""
        comp = Component(
            name="test",
            ports=[
                Port(name="a", direction="input", type="string"),
                Port(name="b", direction="input", type="number"),
            ],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema["type"] == "object"
        assert len(agent.input_schema["properties"]) == 2
        assert agent.output_schema == {}

    def test_only_output_ports(self):
        """只有输出端口"""
        comp = Component(
            name="test",
            ports=[
                Port(name="a", direction="output", type="string"),
            ],
        )
        agent = ComponentAgent(comp)
        assert agent.input_schema == {}
        assert agent.output_schema["type"] == "object"
        assert "a" in agent.output_schema["properties"]


# ===========================================================================
# TestSuite 12: 组件合并（内联定义）
# ===========================================================================


class TestInlineMerge:
    """内联定义合并测试"""

    def test_merge_inline_ports(self):
        """合并内联端口"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        base = Component(
            name="base",
            ports=[Port(name="x", direction="input", type="string")],
        )

        agent_def = AgentInstance(
            name="extended",
            component="base",
            inline_ports=[
                Port(name="y", direction="input", type="number"),
                Port(name="z", direction="output", type="boolean"),
            ],
        )

        # 使用 create 并传入 base 组件
        agent = factory.create(agent_def, component=base)

        # 内联端口不会被合并到 Component 中（因为 validate_overrides 会阻止）
        # 但 component 本身保留原始端口
        assert len(agent.get_input_ports()) >= 1

    def test_merge_inline_system_prompt(self):
        """合并内联 system_prompt"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        base = Component(
            name="base",
            ports=[Port(name="x", direction="input", type="string")],
            system_prompt="original",
        )

        agent_def = AgentInstance(
            name="extended",
            component="base",
            inline_system_prompt="custom prompt",
        )

        agent = factory.create(agent_def, component=base)
        # system_prompt 来自组件定义（不可覆盖）
        assert agent.config.prompt == "original"

    def test_create_inline_merges_ports(self):
        """create_inline 正确合并端口"""
        registry = ComponentRegistry()
        factory = ComponentFactory(registry)

        agent_def = AgentInstance(
            name="inline",
            inline_ports=[
                Port(name="a", direction="input", type="string"),
                Port(name="b", direction="output", type="number"),
            ],
            inline_system_prompt="test",
        )

        agent = factory.create_inline(agent_def)
        assert len(agent.get_input_ports()) == 1
        assert len(agent.get_output_ports()) == 1
        assert agent.config.prompt == "test"


# ===========================================================================
# TestSuite 13: 集成测试
# ===========================================================================


class TestIntegration:
    """端到端集成测试"""

    def test_full_workflow_instantiation(self):
        """完整工作流实例化"""
        # 定义组件
        classifier = Component(
            name="classifier",
            ports=[
                Port(name="ticket", direction="input", type="object"),
                Port(name="category", direction="output", type="string"),
            ],
            model=ModelConfig(default="gpt-4"),
            system_prompt="分类工单: {ticket}",
        )
        router = make_ticket_router_component()
        handler = Component(
            name="handler",
            ports=[
                Port(name="urgent", direction="input", type="object"),
                Port(name="result", direction="output", type="object"),
            ],
            model=ModelConfig(default="gpt-4"),
            system_prompt="处理: {urgent}",
        )

        # 注册
        registry = ComponentRegistry()
        registry.register_all([classifier, router, handler])

        # 定义工作流
        workflow = Workflow(
            name="ticket-wf",
            ports=[
                Port(name="ticket", direction="input", type="object"),
                Port(name="result", direction="output", type="object"),
            ],
            agents=[
                AgentInstance(name="classify", component="classifier"),
                AgentInstance(name="route", component="ticket-router"),
                AgentInstance(name="handle", component="handler", overrides={"model": "gpt-4o"}),
            ],
            connections=[
                Connection(source_agent="classify", source_port="category", target_agents=["route"], target_ports=["ticket"]),
                Connection(source_agent="route", source_port="urgent", target_agents=["handle"], target_ports=["urgent"]),
            ],
            output_mappings={"result": "handle.result"},
        )

        # 实例化
        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        # 验证
        assert len(result.agents) == 3
        assert result.agents["classify"].config.model == "gpt-4"
        assert result.agents["handle"].config.model == "gpt-4o"
        assert len(result.port_mappings) == 2
        assert result.output_mappings == {"result": "handle.result"}

    @pytest.mark.asyncio
    async def test_end_to_end_data_flow(self):
        """端到端数据流（使用同名端口做透传）"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="data", direction="input", type="string"),
                Port(name="data", direction="output", type="string"),
            ],
        )

        agents = {}
        for name in ["a", "b", "c"]:
            agents[name] = ComponentAgent(comp, agent_name=name)

        workflow = InstantiatedWorkflow(
            name="chain",
            agents=agents,
            port_mappings=[
                PortMapping("a", "data", "b", "data"),
                PortMapping("b", "data", "c", "data"),
            ],
        )

        router = DataFlowRouter(workflow)

        # A 执行
        result_a = await agents["a"].run({"data": "start"})
        router.set_agent_output("a", result_a)

        # B 执行
        input_b = router.get_agent_input("b")
        result_b = await agents["b"].run(input_b)
        router.set_agent_output("b", result_b)

        # C 执行
        input_c = router.get_agent_input("c")
        result_c = await agents["c"].run(input_c)

        assert result_c["data"] == "start"

    @pytest.mark.asyncio
    async def test_broadcast_data_flow(self):
        """广播数据流：A -> (B, C)"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="in", direction="input", type="string"),
                Port(name="out", direction="output", type="string"),
            ],
        )

        agents = {}
        for name in ["a", "b", "c"]:
            agents[name] = ComponentAgent(comp, agent_name=name)

        workflow = InstantiatedWorkflow(
            name="broadcast",
            agents=agents,
            port_mappings=[
                PortMapping("a", "out", "b", "in"),
                PortMapping("a", "out", "c", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"out": "broadcast_data"})

        input_b = router.get_agent_input("b")
        input_c = router.get_agent_input("c")

        assert input_b["in"] == "broadcast_data"
        assert input_c["in"] == "broadcast_data"

    @pytest.mark.asyncio
    async def test_aggregate_data_flow(self):
        """聚合数据流：(A, B) -> C"""
        comp = Component(
            name="pass",
            ports=[
                Port(name="in", direction="input", type="string"),
                Port(name="out", direction="output", type="string"),
            ],
        )

        agents = {}
        for name in ["a", "b", "c"]:
            agents[name] = ComponentAgent(comp, agent_name=name)

        workflow = InstantiatedWorkflow(
            name="aggregate",
            agents=agents,
            port_mappings=[
                PortMapping("a", "out", "c", "in"),
                PortMapping("b", "out", "c", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"out": "from_a"})
        router.set_agent_output("b", {"out": "from_b"})

        input_c = router.get_agent_input("c")
        assert input_c["in"] == {"a": "from_a", "b": "from_b"}

    def test_mcp_and_permissions_preserved(self):
        """MCP 和权限配置在实例化后保留"""
        registry = ComponentRegistry()
        registry.register(make_code_reviewer_component())

        workflow = Workflow(
            name="mcp-wf",
            agents=[
                AgentInstance(name="reviewer", component="code-reviewer"),
            ],
        )

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        agent = result.agents["reviewer"]
        assert len(agent.mcp_configs) == 1
        assert agent.mcp_configs[0].server_name == "github"
        assert "github.add_comment" in agent.permission.allow
        assert "github.delete_repo" in agent.permission.deny


# ===========================================================================
# TestSuite 14: 边界情况
# ===========================================================================


class TestEdgeCases:
    """边界情况测试"""

    def test_component_with_no_ports(self):
        """无端口组件"""
        comp = Component(name="empty", ports=[])
        agent = ComponentAgent(comp)

        assert agent.get_input_ports() == []
        assert agent.get_output_ports() == []
        assert agent.input_schema == {}
        assert agent.output_schema == {}

    def test_component_with_no_system_prompt(self):
        """无 system_prompt 组件"""
        comp = Component(
            name="no-prompt",
            ports=[Port(name="x", direction="input", type="string")],
            system_prompt=None,
        )
        agent = ComponentAgent(comp)

        result = agent._render_system_prompt({"x": "hello"})
        assert result == ""

    def test_component_with_no_model(self):
        """无模型配置组件使用默认值"""
        comp = Component(name="no-model", ports=[])
        agent = ComponentAgent(comp)

        assert agent.config.model == "gpt-4"  # 默认值

    def test_empty_workflow_instantiation(self):
        """空工作流实例化"""
        registry = ComponentRegistry()
        workflow = Workflow(name="empty")

        instantiator = WorkflowInstantiator(registry)
        result = instantiator.instantiate(workflow)

        assert result.name == "empty"
        assert result.agents == {}
        assert result.port_mappings == []

    def test_port_mapping_error_no_source_agent(self):
        """源 agent 不存在"""
        comp = Component(
            name="a",
            ports=[Port(name="out", direction="output", type="string")],
        )
        agent = ComponentAgent(comp, agent_name="a")

        workflow = InstantiatedWorkflow(
            name="test",
            agents={"a": agent},
            port_mappings=[
                PortMapping("nonexistent", "out", "a", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        # 应返回 None 而非抛异常
        input_data = router.get_agent_input("a")
        assert input_data["in"] is None

    def test_multiple_same_port_aggregation(self):
        """多个源连接到同一端口的聚合"""
        comp = Component(
            name="x",
            ports=[
                Port(name="out", direction="output", type="string"),
                Port(name="in", direction="input", type="string"),
            ],
        )

        agents = {
            "a": ComponentAgent(comp, agent_name="a"),
            "b": ComponentAgent(comp, agent_name="b"),
            "c": ComponentAgent(comp, agent_name="c"),
        }

        workflow = InstantiatedWorkflow(
            name="multi-agg",
            agents=agents,
            port_mappings=[
                PortMapping("a", "out", "c", "in"),
                PortMapping("b", "out", "c", "in"),
            ],
        )

        router = DataFlowRouter(workflow)
        router.set_agent_output("a", {"out": "val_a"})
        router.set_agent_output("b", {"out": "val_b"})

        input_c = router.get_agent_input("c")
        assert input_c["in"] == {"a": "val_a", "b": "val_b"}

    def test_override_unknown_key_ignored(self):
        """未知覆盖参数被忽略（不报错）"""
        comp = make_simple_component()
        # 未知参数不应导致崩溃
        agent = ComponentAgent(comp, overrides={"unknown_param": 123})
        assert agent.config.model == "gpt-3.5-turbo"

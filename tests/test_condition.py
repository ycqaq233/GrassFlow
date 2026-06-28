"""
ConditionAgent 测试

测试内容：
- 条件分支判断
- 路由值验证
- 错误处理

使用 v2 类型: Component
"""

import pytest
import asyncio
from core.models import Component, ModelConfig, Port
from core.condition import ConditionAgent, SimpleConditionAgent, make_condition_component


class TestConditionAgent:
    """ConditionAgent 测试"""

    @pytest.mark.asyncio
    async def test_condition_agent_basic(self):
        """测试基本条件判断"""
        comp = make_condition_component("route", rules=["urgent", "normal", "info"])
        agent = ConditionAgent(comp, rules=["urgent", "normal", "info"])

        result = await agent.run({"route": "urgent"})
        assert result == {"route": "urgent"}

    @pytest.mark.asyncio
    async def test_condition_agent_from_deps(self):
        """测试从依赖数据中获取路由值"""
        comp = make_condition_component("route", rules=["urgent", "normal"])
        agent = ConditionAgent(comp, rules=["urgent", "normal"])

        input_data = {
            "_deps": {
                "classifier": {"route": "urgent"}
            }
        }
        result = await agent.run(input_data)
        assert result == {"route": "urgent"}

    @pytest.mark.asyncio
    async def test_condition_agent_invalid_route(self):
        """测试无效路由值"""
        comp = make_condition_component("route", rules=["urgent", "normal"])
        agent = ConditionAgent(comp, rules=["urgent", "normal"])

        with pytest.raises(ValueError, match="not in rules"):
            await agent.run({"route": "invalid"})

    @pytest.mark.asyncio
    async def test_condition_agent_missing_route(self):
        """测试缺少路由字段"""
        comp = make_condition_component("route", rules=["urgent", "normal"])
        agent = ConditionAgent(comp, rules=["urgent", "normal"])

        with pytest.raises(ValueError, match="not found in input"):
            await agent.run({})

    @pytest.mark.asyncio
    async def test_condition_agent_custom_field(self):
        """测试自定义路由字段"""
        comp = make_condition_component("route", rules=["high", "low"])
        agent = ConditionAgent(comp, rules=["high", "low"], route_field="priority")

        result = await agent.run({"priority": "high"})
        assert result == {"priority": "high"}


class TestSimpleConditionAgent:
    """SimpleConditionAgent 测试"""

    @pytest.mark.asyncio
    async def test_simple_condition_agent_basic(self):
        """测试基本条件映射"""
        comp = make_condition_component("route")
        agent = SimpleConditionAgent(
            comp,
            field="priority",
            mapping={"high": "urgent", "low": "normal"}
        )

        result = await agent.run({"priority": "high"})
        assert result == {"route": "urgent"}

    @pytest.mark.asyncio
    async def test_simple_condition_agent_from_deps(self):
        """测试从依赖数据中获取字段值"""
        comp = make_condition_component("route")
        agent = SimpleConditionAgent(
            comp,
            field="priority",
            mapping={"high": "urgent", "low": "normal"}
        )

        input_data = {
            "_deps": {
                "classifier": {"priority": "low"}
            }
        }
        result = await agent.run(input_data)
        assert result == {"route": "normal"}

    @pytest.mark.asyncio
    async def test_simple_condition_agent_default(self):
        """测试默认路由值"""
        comp = make_condition_component("route")
        agent = SimpleConditionAgent(
            comp,
            field="priority",
            mapping={"high": "urgent"},
            default="normal"
        )

        result = await agent.run({"priority": "low"})
        assert result == {"route": "normal"}

    @pytest.mark.asyncio
    async def test_simple_condition_agent_no_mapping_no_default(self):
        """测试无映射无默认值"""
        comp = make_condition_component("route")
        agent = SimpleConditionAgent(
            comp,
            field="priority",
            mapping={"high": "urgent"}
        )

        with pytest.raises(ValueError, match="not in mapping"):
            await agent.run({"priority": "low"})

    @pytest.mark.asyncio
    async def test_simple_condition_agent_missing_field(self):
        """测试缺少字段"""
        comp = make_condition_component("route")
        agent = SimpleConditionAgent(
            comp,
            field="priority",
            mapping={"high": "urgent"},
            default="normal"
        )

        result = await agent.run({})
        assert result == {"route": "normal"}


class TestConditionFromComponent:
    """从 Component 构造条件 Agent"""

    def test_component_for_condition(self):
        """Component 可以描述条件路由"""
        comp = Component(
            name="ticket-router",
            description="工单路由器",
            ports=[
                Port(name="ticket", direction="input", type="object"),
                Port(name="urgent", direction="output", type="object"),
                Port(name="normal", direction="output", type="object"),
            ],
            model=ModelConfig(default="gpt-4"),
            system_prompt="根据工单 {ticket} 判断优先级",
        )

        assert comp.name == "ticket-router"
        assert len(comp.ports) == 3
        input_ports = [p for p in comp.ports if p.direction == "input"]
        output_ports = [p for p in comp.ports if p.direction == "output"]
        assert len(input_ports) == 1
        assert len(output_ports) == 2

        route_rules = [p.name for p in output_ports]
        assert "urgent" in route_rules
        assert "normal" in route_rules

    @pytest.mark.asyncio
    async def test_condition_agent_with_component_rules(self):
        """从 Component 的输出端口推断条件规则"""
        comp = Component(
            name="router",
            ports=[
                Port(name="input", direction="input", type="object"),
                Port(name="urgent", direction="output", type="object"),
                Port(name="normal", direction="output", type="object"),
                Port(name="info", direction="output", type="object"),
            ],
        )

        rules = [p.name for p in comp.ports if p.direction == "output"]
        agent = ConditionAgent(comp, rules=rules)

        result = await agent.run({"route": "urgent"})
        assert result == {"route": "urgent"}

"""
ConditionAgent 测试

测试内容：
- 条件分支判断
- 路由值验证
- 错误处理
"""

import pytest
import asyncio
from core.condition import ConditionAgent, SimpleConditionAgent


class TestConditionAgent:
    """ConditionAgent 测试"""

    @pytest.mark.asyncio
    async def test_condition_agent_basic(self):
        """测试基本条件判断"""
        agent = ConditionAgent(name="route", rules=["urgent", "normal", "info"])

        # 输入包含 route 字段
        result = await agent.run({"route": "urgent"})
        assert result == {"route": "urgent"}

    @pytest.mark.asyncio
    async def test_condition_agent_from_deps(self):
        """测试从依赖数据中获取路由值"""
        agent = ConditionAgent(name="route", rules=["urgent", "normal"])

        # 输入数据在 _deps 中
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
        agent = ConditionAgent(name="route", rules=["urgent", "normal"])

        with pytest.raises(ValueError, match="not in rules"):
            await agent.run({"route": "invalid"})

    @pytest.mark.asyncio
    async def test_condition_agent_missing_route(self):
        """测试缺少路由字段"""
        agent = ConditionAgent(name="route", rules=["urgent", "normal"])

        with pytest.raises(ValueError, match="not found in input"):
            await agent.run({})

    @pytest.mark.asyncio
    async def test_condition_agent_custom_field(self):
        """测试自定义路由字段"""
        agent = ConditionAgent(
            name="route",
            rules=["high", "low"],
            route_field="priority"
        )

        result = await agent.run({"priority": "high"})
        assert result == {"priority": "high"}


class TestSimpleConditionAgent:
    """SimpleConditionAgent 测试"""

    @pytest.mark.asyncio
    async def test_simple_condition_agent_basic(self):
        """测试基本条件映射"""
        agent = SimpleConditionAgent(
            name="route",
            field="priority",
            mapping={"high": "urgent", "low": "normal"}
        )

        result = await agent.run({"priority": "high"})
        assert result == {"route": "urgent"}

    @pytest.mark.asyncio
    async def test_simple_condition_agent_from_deps(self):
        """测试从依赖数据中获取字段值"""
        agent = SimpleConditionAgent(
            name="route",
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
        agent = SimpleConditionAgent(
            name="route",
            field="priority",
            mapping={"high": "urgent"},
            default="normal"
        )

        result = await agent.run({"priority": "low"})
        assert result == {"route": "normal"}

    @pytest.mark.asyncio
    async def test_simple_condition_agent_no_mapping_no_default(self):
        """测试无映射无默认值"""
        agent = SimpleConditionAgent(
            name="route",
            field="priority",
            mapping={"high": "urgent"}
        )

        with pytest.raises(ValueError, match="not in mapping"):
            await agent.run({"priority": "low"})

    @pytest.mark.asyncio
    async def test_simple_condition_agent_missing_field(self):
        """测试缺少字段"""
        agent = SimpleConditionAgent(
            name="route",
            field="priority",
            mapping={"high": "urgent"},
            default="normal"
        )

        result = await agent.run({})
        assert result == {"route": "normal"}

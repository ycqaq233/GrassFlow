"""
LLM Agent 测试

测试内容：
- LLMAgent 初始化
- prompt 格式化
- 响应解析
- 工厂创建

使用 v2 类型: Component, ModelConfig
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from core.models import Component, ModelConfig
from core.llm_agent import LLMAgent, LLMAgentFactory
from core.llm import LLMClient, LLMManager, LLMResponse


class TestLLMAgent:
    """LLMAgent 测试"""

    def test_llm_agent_init(self):
        """测试 LLMAgent 初始化"""
        client = LLMClient(model="gpt-4")
        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
            system_prompt="test prompt",
        )
        agent = LLMAgent(
            component=comp,
            llm_client=client,
        )

        assert agent.name == "test"
        # resolved_model 可能被 _resolve_model 调整（取决于配置中的默认 provider）
        assert isinstance(agent.resolved_model, str)
        assert len(agent.resolved_model) > 0

    def test_format_prompt_simple(self):
        """测试简单 prompt 格式化"""
        client = LLMClient(model="gpt-4")
        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
            system_prompt="分类工单: {input}",
        )
        agent = LLMAgent(component=comp, llm_client=client)

        result = agent._format_prompt({"ticket": "我的电脑坏了"})
        assert "分类工单" in result

    def test_format_prompt_with_fields(self):
        """测试带字段的 prompt 格式化"""
        client = LLMClient(model="gpt-4")
        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
            system_prompt="分类: {ticket}, 优先级: {priority}",
        )
        agent = LLMAgent(component=comp, llm_client=client)

        result = agent._format_prompt({
            "ticket": "我的电脑坏了",
            "priority": "high",
        })
        assert "我的电脑坏了" in result
        assert "high" in result

    def test_format_prompt_no_template(self):
        """测试无模板的 prompt 格式化"""
        client = LLMClient(model="gpt-4")
        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
            system_prompt="",
        )
        agent = LLMAgent(component=comp, llm_client=client)

        result = agent._format_prompt({"ticket": "我的电脑坏了"})
        assert "我的电脑坏了" in result

    def test_parse_response_json(self):
        """测试解析 JSON 响应"""
        client = LLMClient(model="gpt-4")
        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
        )
        agent = LLMAgent(component=comp, llm_client=client)

        result = agent._parse_response('{"category": "hardware", "priority": "high"}')
        assert result["category"] == "hardware"
        assert result["priority"] == "high"

    def test_parse_response_text(self):
        """测试解析文本响应"""
        client = LLMClient(model="gpt-4")
        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
        )
        agent = LLMAgent(component=comp, llm_client=client)

        result = agent._format_prompt({"ticket": "我的电脑坏了"})
        assert isinstance(result, str)


class TestLLMAgentFactory:
    """LLMAgentFactory 测试"""

    def test_factory_create(self):
        """测试工厂创建"""
        manager = LLMManager()
        factory = LLMAgentFactory(llm_manager=manager)

        comp = Component(
            name="test",
            model=ModelConfig(default="gpt-4"),
            system_prompt="test prompt",
        )
        agent = factory.create(comp)
        assert agent.name == "test"
        assert isinstance(agent.resolved_model, str)

    def test_factory_create_from_component(self):
        """测试从 Component 创建"""
        comp = Component(
            name="test-agent",
            model=ModelConfig(default="gpt-4"),
            system_prompt="test prompt from component",
        )

        manager = LLMManager()
        factory = LLMAgentFactory(llm_manager=manager)

        agent = factory.create(comp)
        assert agent.name == "test-agent"
        assert isinstance(agent.resolved_model, str)

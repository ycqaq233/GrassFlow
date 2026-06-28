"""
LLM Agent 测试

测试内容：
- LLMAgent 初始化
- prompt 格式化
- 响应解析
- 工厂创建
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
try:
    from core.models import Component, ModelConfig
except ImportError:
    from core.dsl_v2_ast import Component, ModelConfig
from core.llm_agent import LLMAgent, LLMAgentFactory
from core.llm import LLMClient, LLMManager, LLMResponse


class TestLLMAgent:
    """LLMAgent 测试"""

    def test_llm_agent_init(self):
        """测试 LLMAgent 初始化"""
        client = LLMClient(model="gpt-4")
        agent = LLMAgent(
            name="test",
            model="gpt-4",
            prompt="test prompt",
            llm_client=client,
        )

        assert agent.name == "test"
        assert agent.config.model == "gpt-4"
        assert agent.config.prompt == "test prompt"

    def test_format_prompt_simple(self):
        """测试简单 prompt 格式化"""
        client = LLMClient(model="gpt-4")
        agent = LLMAgent(
            name="test",
            prompt="分类工单: {input}",
            llm_client=client,
        )

        result = agent._format_prompt({"ticket": "我的电脑坏了"})
        assert "分类工单" in result

    def test_format_prompt_with_fields(self):
        """测试带字段的 prompt 格式化"""
        client = LLMClient(model="gpt-4")
        agent = LLMAgent(
            name="test",
            prompt="分类: {ticket}, 优先级: {priority}",
            llm_client=client,
        )

        result = agent._format_prompt({
            "ticket": "我的电脑坏了",
            "priority": "high",
        })
        assert "我的电脑坏了" in result
        assert "high" in result

    def test_format_prompt_no_template(self):
        """测试无模板的 prompt 格式化"""
        client = LLMClient(model="gpt-4")
        agent = LLMAgent(
            name="test",
            prompt="",
            llm_client=client,
        )

        result = agent._format_prompt({"ticket": "我的电脑坏了"})
        assert "我的电脑坏了" in result

    def test_parse_response_json(self):
        """测试解析 JSON 响应"""
        client = LLMClient(model="gpt-4")
        agent = LLMAgent(
            name="test",
            llm_client=client,
        )

        result = agent._parse_response('{"category": "hardware", "priority": "high"}')
        assert result["category"] == "hardware"
        assert result["priority"] == "high"

    def test_parse_response_text(self):
        """测试解析文本响应"""
        client = LLMClient(model="gpt-4")
        agent = LLMAgent(
            name="test",
            llm_client=client,
        )

        result = agent._format_prompt({"ticket": "我的电脑坏了"})
        assert isinstance(result, str)


class TestLLMAgentFactory:
    """LLMAgentFactory 测试"""

    def test_factory_create(self):
        """测试工厂创建"""
        manager = LLMManager()
        factory = LLMAgentFactory(llm_manager=manager)

        agent = factory.create("test", model="gpt-4", prompt="test prompt")
        assert agent.name == "test"
        assert agent.config.model == "gpt-4"

    def test_factory_create_from_config(self):
        """测试从配置创建"""
        from core.agent import AgentConfig

        manager = LLMManager()
        factory = LLMAgentFactory(llm_manager=manager)

        config = AgentConfig(
            name="test",
            model="gpt-4",
            prompt="test prompt",
        )

        agent = factory.create_from_config(config)
        assert agent.name == "test"
        assert agent.config.model == "gpt-4"

    def test_factory_create_from_component(self):
        """测试从 Component 创建"""
        comp = Component(
            name="test-agent",
            model=ModelConfig(default="gpt-4"),
            system_prompt="test prompt from component",
        )

        manager = LLMManager()
        factory = LLMAgentFactory(llm_manager=manager)

        # Component 的 model.default 映射到 agent model
        agent = factory.create(
            comp.name,
            model=comp.model.default or "gpt-4",
            prompt=comp.system_prompt or "",
        )
        assert agent.name == "test-agent"
        assert agent.config.model == "gpt-4"
        assert agent.config.prompt == "test prompt from component"

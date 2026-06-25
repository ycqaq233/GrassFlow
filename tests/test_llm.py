"""
LLM 模块测试

测试内容：
- LLMClient 初始化
- LLMManager 管理
- 错误处理
"""

import pytest
from core.llm import LLMClient, LLMManager, LLMError, LLMResponse


class TestLLMClient:
    """LLMClient 测试"""

    def test_llm_client_init(self):
        """测试 LLMClient 初始化"""
        client = LLMClient(model="gpt-4", api_key="test-key")
        assert client.model == "gpt-4"
        assert client.api_key == "test-key"
        assert client.timeout == 60
        assert client.max_retries == 3

    def test_llm_client_default_values(self):
        """测试 LLMClient 默认值"""
        client = LLMClient()
        assert client.model == "gpt-4"
        assert client.api_key is None
        assert client.base_url is None
        assert client.timeout == 60
        assert client.max_retries == 3

    def test_llm_client_custom_values(self):
        """测试 LLMClient 自定义值"""
        client = LLMClient(
            model="claude-3-opus",
            api_key="sk-test",
            base_url="http://localhost:11434",
            timeout=120,
            max_retries=5,
        )
        assert client.model == "claude-3-opus"
        assert client.api_key == "sk-test"
        assert client.base_url == "http://localhost:11434"
        assert client.timeout == 120
        assert client.max_retries == 5


class TestLLMManager:
    """LLMManager 测试"""

    def test_register_and_get(self):
        """测试注册和获取客户端"""
        manager = LLMManager()
        client = LLMClient(model="gpt-4")
        manager.register("openai", client)

        retrieved = manager.get("openai")
        assert retrieved is client

    def test_get_nonexistent(self):
        """测试获取不存在的客户端"""
        manager = LLMManager()

        with pytest.raises(LLMError, match="not registered"):
            manager.get("nonexistent")

    def test_create_client(self):
        """测试创建客户端"""
        manager = LLMManager()
        client = manager.create("openai", model="gpt-4", api_key="test-key")

        assert client.model == "gpt-4"
        assert client.api_key == "test-key"
        assert manager.get("openai") is client

    def test_multiple_clients(self):
        """测试多个客户端"""
        manager = LLMManager()

        manager.create("openai", model="gpt-4")
        manager.create("anthropic", model="claude-3-opus")
        manager.create("local", model="llama2", base_url="http://localhost:11434")

        assert manager.get("openai").model == "gpt-4"
        assert manager.get("anthropic").model == "claude-3-opus"
        assert manager.get("local").model == "llama2"

    def test_overwrite_client(self):
        """测试覆盖客户端"""
        manager = LLMManager()

        manager.create("openai", model="gpt-4")
        manager.create("openai", model="gpt-4-turbo")

        assert manager.get("openai").model == "gpt-4-turbo"


class TestLLMResponse:
    """LLMResponse 测试"""

    def test_llm_response_creation(self):
        """测试 LLMResponse 创建"""
        response = LLMResponse(
            content="Hello, world!",
            model="gpt-4",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            finish_reason="stop",
        )

        assert response.content == "Hello, world!"
        assert response.model == "gpt-4"
        assert response.usage["total_tokens"] == 15
        assert response.finish_reason == "stop"

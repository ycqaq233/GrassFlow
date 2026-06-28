"""
GrassFlow LLM Protocol 抽象层测试

测试四维模型：Protocol + Endpoint + Auth + Framing
"""

import asyncio
import json
import os
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm_protocol import (
    Auth,
    Credential,
    Endpoint,
    GenerationOptions,
    LLMEvent,
    LLMEventType,
    LLMProtocolError,
    LLMRequest,
    LLMErrorCode,
    Message,
    Model,
    OpenAIChatBody,
    OpenAIChatProtocol,
    OpenAIChatState,
    OpenAIChatStream,
    PreparedRequest,
    ProtocolLLMClient,
    ProtocolLLMManager,
    Provider,
    Route,
    SSEFraming,
    ToolCall,
    ToolDefinition,
    Usage,
    _apply_event_to_response,
    _LegacyLLMResponse,
    _status_to_error_code,
    custom_provider,
    deepseek_provider,
    ollama_provider,
    openai_provider,
    protocol_manager,
)


# ============================================================================
# Credential 测试
# ============================================================================


class TestCredential:
    """Credential 惰性凭证测试"""

    @pytest.mark.asyncio
    async def test_of(self):
        """显式值"""
        cred = Credential.of("sk-test-123")
        assert await cred.resolve() == "sk-test-123"

    @pytest.mark.asyncio
    async def test_from_env(self):
        """环境变量"""
        os.environ["TEST_GRASSFLOW_KEY"] = "env-key-456"
        try:
            cred = Credential.from_env("TEST_GRASSFLOW_KEY")
            assert await cred.resolve() == "env-key-456"
        finally:
            del os.environ["TEST_GRASSFLOW_KEY"]

    @pytest.mark.asyncio
    async def test_from_env_missing(self):
        """缺失的环境变量"""
        cred = Credential.from_env("NONEXISTENT_VAR_XYZ")
        assert await cred.resolve() is None

    @pytest.mark.asyncio
    async def test_from_loader(self):
        """异步加载器"""
        async def loader():
            return "loaded-key"

        cred = Credential.from_loader(loader)
        assert await cred.resolve() == "loaded-key"

    @pytest.mark.asyncio
    async def test_from_sync_loader(self):
        """同步加载器"""
        cred = Credential.from_loader(lambda: "sync-key")
        assert await cred.resolve() == "sync-key"

    @pytest.mark.asyncio
    async def test_or_else_primary(self):
        """回退链：主凭证有效"""
        primary = Credential.of("primary")
        fallback = Credential.of("fallback")
        cred = primary.or_else(fallback)
        assert await cred.resolve() == "primary"

    @pytest.mark.asyncio
    async def test_or_else_fallback(self):
        """回退链：主凭证无效，使用回退"""
        primary = Credential.from_env("NONEXISTENT_VAR_XYZ")
        fallback = Credential.of("fallback")
        cred = primary.or_else(fallback)
        assert await cred.resolve() == "fallback"

    @pytest.mark.asyncio
    async def test_or_else_both_fail(self):
        """回退链：两者都失败"""
        primary = Credential.from_env("NONEXISTENT_A")
        fallback = Credential.from_env("NONEXISTENT_B")
        cred = primary.or_else(fallback)
        assert await cred.resolve() is None


# ============================================================================
# Auth 测试
# ============================================================================


class TestAuth:
    """Auth 认证策略测试"""

    @pytest.mark.asyncio
    async def test_none(self):
        """无认证"""
        auth = Auth.none()
        inp = MagicMock()
        inp.headers = {"Content-Type": "application/json"}
        result = await auth.apply(inp)
        assert result.headers == {"Content-Type": "application/json"}

    @pytest.mark.asyncio
    async def test_bearer(self):
        """Bearer Token"""
        auth = Auth.bearer(Credential.of("test-token"))
        inp = MagicMock()
        inp.headers = {}
        result = await auth.apply(inp)
        assert result.headers["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_header(self):
        """自定义 Header"""
        auth = Auth.header("x-api-key", Credential.of("key123"))
        inp = MagicMock()
        inp.headers = {}
        result = await auth.apply(inp)
        assert result.headers["x-api-key"] == "key123"

    @pytest.mark.asyncio
    async def test_header_with_prefix(self):
        """带前缀的自定义 Header"""
        auth = Auth.header("x-api-key", Credential.of("key123"), prefix="Token ")
        inp = MagicMock()
        inp.headers = {}
        result = await auth.apply(inp)
        assert result.headers["x-api-key"] == "Token key123"

    @pytest.mark.asyncio
    async def test_headers_static(self):
        """静态 Headers"""
        auth = Auth.headers({"X-Custom": "value", "X-Other": "other"})
        inp = MagicMock()
        inp.headers = {}
        result = await auth.apply(inp)
        assert result.headers["X-Custom"] == "value"
        assert result.headers["X-Other"] == "other"

    @pytest.mark.asyncio
    async def test_and_then(self):
        """链式组合"""
        auth1 = Auth.bearer(Credential.of("token"))
        auth2 = Auth.headers({"X-Extra": "info"})
        combined = auth1.and_then(auth2)
        inp = MagicMock()
        inp.headers = {}
        result = await combined.apply(inp)
        assert result.headers["Authorization"] == "Bearer token"
        assert result.headers["X-Extra"] == "info"

    @pytest.mark.asyncio
    async def test_from_config_with_key(self):
        """from_config 显式 key"""
        auth = Auth.from_config(api_key="explicit-key")
        inp = MagicMock()
        inp.headers = {}
        result = await auth.apply(inp)
        assert result.headers["Authorization"] == "Bearer explicit-key"

    @pytest.mark.asyncio
    async def test_from_config_with_env(self):
        """from_config 环境变量"""
        os.environ["TEST_GF_AUTH"] = "env-auth-key"
        try:
            auth = Auth.from_config(env_var="TEST_GF_AUTH")
            inp = MagicMock()
            inp.headers = {}
            result = await auth.apply(inp)
            assert result.headers["Authorization"] == "Bearer env-auth-key"
        finally:
            del os.environ["TEST_GF_AUTH"]

    @pytest.mark.asyncio
    async def test_from_config_none(self):
        """from_config 无配置"""
        auth = Auth.from_config()
        inp = MagicMock()
        inp.headers = {}
        result = await auth.apply(inp)
        assert "Authorization" not in result.headers


# ============================================================================
# Endpoint 测试
# ============================================================================


class TestEndpoint:
    """Endpoint URL 构造测试"""

    def test_static_path(self):
        """静态路径"""
        ep = Endpoint(path="/v1/chat/completions", base_url="https://api.openai.com")
        assert ep.render() == "https://api.openai.com/v1/chat/completions"

    def test_dynamic_path(self):
        """动态路径（函数）"""
        ep = Endpoint(
            path=lambda body: f"/v1/models/{body.get('model', 'default')}/chat",
            base_url="https://api.example.com",
        )
        assert ep.render({"model": "gpt-4"}) == "https://api.example.com/v1/models/gpt-4/chat"

    def test_query_params(self):
        """查询参数"""
        ep = Endpoint(
            path="/v1/chat",
            base_url="https://api.example.com",
            query={"api-version": "2024-01"},
        )
        assert ep.render() == "https://api.example.com/v1/chat?api-version=2024-01"

    def test_trailing_slash(self):
        """尾部斜杠处理"""
        ep = Endpoint(path="/v1/chat", base_url="https://api.example.com/")
        assert ep.render() == "https://api.example.com/v1/chat"

    def test_with_base_url(self):
        """覆盖 base URL"""
        ep = Endpoint(path="/v1/chat", base_url="https://api.openai.com")
        ep2 = ep.with_base_url("https://custom.api.com")
        assert ep2.render() == "https://custom.api.com/v1/chat"
        # 原始不变
        assert ep.render() == "https://api.openai.com/v1/chat"


# ============================================================================
# OpenAIChatBody 测试
# ============================================================================


class TestOpenAIChatBody:
    """OpenAI Chat 请求体编码测试"""

    def test_basic_encode(self):
        """基本编码"""
        body_encoder = OpenAIChatBody()
        request = LLMRequest(
            model="gpt-4",
            messages=[Message(role="user", content="Hello")],
        )
        result = body_encoder.encode(request)

        assert result["model"] == "gpt-4"
        assert result["stream"] is True
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hello"

    def test_system_messages(self):
        """系统消息"""
        body_encoder = OpenAIChatBody()
        request = LLMRequest(
            model="gpt-4",
            messages=[Message(role="user", content="Hello")],
            system=[Message(role="system", content="You are helpful")],
        )
        result = body_encoder.encode(request)

        assert len(result["messages"]) == 2
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][0]["content"] == "You are helpful"

    def test_generation_options(self):
        """生成选项"""
        body_encoder = OpenAIChatBody()
        request = LLMRequest(
            model="gpt-4",
            messages=[],
            options=GenerationOptions(
                temperature=0.5,
                max_tokens=1000,
                top_p=0.9,
                stop=["END"],
            ),
        )
        result = body_encoder.encode(request)

        assert result["temperature"] == 0.5
        assert result["max_tokens"] == 1000
        assert result["top_p"] == 0.9
        assert result["stop"] == ["END"]

    def test_tools(self):
        """工具定义"""
        body_encoder = OpenAIChatBody()
        request = LLMRequest(
            model="gpt-4",
            messages=[],
            tools=[
                ToolDefinition(
                    name="get_weather",
                    description="Get weather",
                    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
                )
            ],
        )
        result = body_encoder.encode(request)

        assert len(result["tools"]) == 1
        assert result["tools"][0]["type"] == "function"
        assert result["tools"][0]["function"]["name"] == "get_weather"

    def test_tool_choice(self):
        """工具选择"""
        body_encoder = OpenAIChatBody()
        request = LLMRequest(
            model="gpt-4",
            messages=[],
            tool_choice="auto",
        )
        result = body_encoder.encode(request)
        assert result["tool_choice"] == "auto"

    def test_provider_options(self):
        """Provider 额外选项"""
        body_encoder = OpenAIChatBody()
        request = LLMRequest(
            model="gpt-4",
            messages=[],
            extra={"provider_options": {"response_format": {"type": "json_object"}}},
        )
        result = body_encoder.encode(request)
        assert result["response_format"] == {"type": "json_object"}


# ============================================================================
# OpenAIChatStream 测试
# ============================================================================


class TestOpenAIChatStream:
    """OpenAI Chat 流式状态机测试"""

    def test_initial_state(self):
        """初始状态"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())
        assert state.current_text == ""
        assert state.current_reasoning == ""
        assert state.tool_calls == {}
        assert state.finish_reason == ""

    def test_text_delta(self):
        """文本增量"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())

        event = {
            "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]
        }
        state, events = stream.step(state, event)

        assert state.current_text == "Hello"
        assert len(events) == 2  # TEXT_START + TEXT_DELTA
        assert events[0].type == LLMEventType.TEXT_START
        assert events[1].type == LLMEventType.TEXT_DELTA
        assert events[1].data["text"] == "Hello"

    def test_text_multiple_deltas(self):
        """多个文本增量"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())

        for word in ["Hello", " ", "World"]:
            event = {"choices": [{"delta": {"content": word}, "finish_reason": None}]}
            state, new_events = stream.step(state, event)

        assert state.current_text == "Hello World"

    def test_finish_reason(self):
        """完成原因"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())

        # 先发送文本
        event1 = {"choices": [{"delta": {"content": "Hi"}, "finish_reason": None}]}
        state, _ = stream.step(state, event1)

        # 发送完成
        event2 = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        state, events = stream.step(state, event2)

        assert state.finish_reason == "stop"
        # 应有 TEXT_END, STEP_FINISH, FINISH
        event_types = [e.type for e in events]
        assert LLMEventType.TEXT_END in event_types
        assert LLMEventType.STEP_FINISH in event_types
        assert LLMEventType.FINISH in event_types

    def test_tool_call_deltas(self):
        """工具调用增量"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())

        # 工具调用开始
        event1 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call_123", "function": {"name": "get_weather", "arguments": ""}}
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        state, events1 = stream.step(state, event1)
        assert LLMEventType.TOOL_INPUT_START in [e.type for e in events1]

        # 工具参数增量
        event2 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '{"ci'}}
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        state, events2 = stream.step(state, event2)
        assert LLMEventType.TOOL_INPUT_DELTA in [e.type for e in events2]

        # 工具参数增量（续）
        event3 = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": 'ty":"Beijing"}'}}
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        state, events3 = stream.step(state, event3)

        # 完成
        event4 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
        state, events4 = stream.step(state, event4)

        # 应有 TOOL_CALL 事件
        tool_call_events = [e for e in events4 if e.type == LLMEventType.TOOL_CALL]
        assert len(tool_call_events) == 1
        tc = tool_call_events[0].data["tool_call"]
        assert tc.id == "call_123"
        assert tc.name == "get_weather"
        assert tc.arguments == '{"city":"Beijing"}'

    def test_reasoning_delta(self):
        """推理增量"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())

        event = {
            "choices": [{"delta": {"reasoning_content": "Let me think..."}, "finish_reason": None}]
        }
        state, events = stream.step(state, event)

        assert state.current_reasoning == "Let me think..."
        assert LLMEventType.REASONING_START in [e.type for e in events]
        assert LLMEventType.REASONING_DELTA in [e.type for e in events]

    def test_usage(self):
        """用量信息"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())

        event = {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }
        state, _ = stream.step(state, event)

        assert state.usage is not None
        assert state.usage.prompt_tokens == 10
        assert state.usage.completion_tokens == 20
        assert state.usage.total_tokens == 30

    def test_terminal(self):
        """终止判断"""
        stream = OpenAIChatStream()
        assert stream.terminal({"choices": [{"finish_reason": "stop"}]}) is True
        assert stream.terminal({"choices": [{"finish_reason": None}]}) is False
        assert stream.terminal({"choices": []}) is False

    def test_on_halt(self):
        """流中断清理"""
        stream = OpenAIChatStream()
        state = OpenAIChatState(current_text="partial", finish_reason="")
        events = stream.on_halt(state)
        assert LLMEventType.TEXT_END in [e.type for e in events]

    def test_empty_choices(self):
        """空 choices"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())
        event = {"choices": []}
        state, events = stream.step(state, event)
        assert events == []

    def test_model_info(self):
        """模型信息更新"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())
        event = {"model": "gpt-4-turbo", "choices": []}
        state, _ = stream.step(state, event)
        assert state.model == "gpt-4-turbo"


# ============================================================================
# OpenAIChatProtocol 测试
# ============================================================================


class TestOpenAIChatProtocol:
    """OpenAI Chat 协议集成测试"""

    def test_protocol_id(self):
        protocol = OpenAIChatProtocol()
        assert protocol.id == "openai-chat"

    def test_protocol_body(self):
        protocol = OpenAIChatProtocol()
        assert isinstance(protocol.body, OpenAIChatBody)

    def test_protocol_stream(self):
        protocol = OpenAIChatProtocol()
        assert isinstance(protocol.stream, OpenAIChatStream)


# ============================================================================
# Route 测试
# ============================================================================


class TestRoute:
    """Route 组合测试"""

    def test_with_immutable(self):
        """不可变修补"""
        from core.llm_protocol import OPENAI_CHAT_ROUTE

        route2 = OPENAI_CHAT_ROUTE.with_(route_id="custom")
        assert OPENAI_CHAT_ROUTE.id == "openai-chat"
        assert route2.id == "custom"

    def test_model_factory(self):
        """Model 工厂"""
        from core.llm_protocol import OPENAI_CHAT_ROUTE

        model = OPENAI_CHAT_ROUTE.model("gpt-4")
        assert isinstance(model, Model)
        assert model.model_id == "gpt-4"


# ============================================================================
# Provider 测试
# ============================================================================


class TestProvider:
    """Provider 测试"""

    def test_openai_provider(self):
        """OpenAI Provider"""
        prov = openai_provider(api_key="sk-test", default_model="gpt-4")
        assert prov.id == "openai"
        model = prov.model("gpt-4")
        assert model.model_id == "gpt-4"

    def test_deepseek_provider(self):
        """DeepSeek Provider"""
        prov = deepseek_provider(api_key="dk-test")
        assert prov.id == "deepseek"

    def test_ollama_provider(self):
        """Ollama Provider"""
        prov = ollama_provider()
        assert prov.id == "ollama"

    def test_custom_provider(self):
        """自定义 Provider"""
        prov = custom_provider(
            provider_id="my-api",
            base_url="https://my-api.com",
            api_key="key",
            default_model="my-model",
        )
        assert prov.id == "my-api"
        model = prov.model()
        assert model.model_id == "my-model"

    def test_provider_model_default(self):
        """Provider 默认模型"""
        prov = openai_provider(api_key="sk-test", default_model="gpt-4-turbo")
        model = prov.model()
        assert model.model_id == "gpt-4-turbo"


# ============================================================================
# ProtocolLLMClient 兼容层测试
# ============================================================================


class TestProtocolLLMClient:
    """ProtocolLLMClient 兼容层测试"""

    def test_from_provider_openai(self):
        """从 OpenAI Provider 创建"""
        client = ProtocolLLMClient.from_provider(
            "openai", api_key="sk-test", model="gpt-4"
        )
        assert isinstance(client, ProtocolLLMClient)

    def test_from_provider_deepseek(self):
        """从 DeepSeek Provider 创建"""
        client = ProtocolLLMClient.from_provider(
            "deepseek", api_key="dk-test", model="deepseek-chat"
        )
        assert isinstance(client, ProtocolLLMClient)

    def test_from_provider_ollama(self):
        """从 Ollama Provider 创建"""
        client = ProtocolLLMClient.from_provider("ollama", model="llama3")
        assert isinstance(client, ProtocolLLMClient)

    def test_from_provider_custom(self):
        """自定义 Provider 创建"""
        client = ProtocolLLMClient.from_provider(
            "custom-api",
            base_url="https://custom.api.com",
            api_key="key",
            model="model-1",
        )
        assert isinstance(client, ProtocolLLMClient)


# ============================================================================
# ProtocolLLMManager 测试
# ============================================================================


class TestProtocolLLMManager:
    """ProtocolLLMManager 测试"""

    def test_create_and_get_client(self):
        """创建和获取客户端"""
        manager = ProtocolLLMManager()
        client = manager.create_client(
            "test",
            provider_name="openai",
            model="gpt-4",
            api_key="sk-test",
        )
        assert isinstance(client, ProtocolLLMClient)
        assert manager.get_client("test") is client

    def test_get_nonexistent_client(self):
        """获取不存在的客户端"""
        manager = ProtocolLLMManager()
        with pytest.raises(LLMProtocolError) as exc_info:
            manager.get_client("nonexistent")
        assert "not registered" in str(exc_info.value)

    def test_register_provider(self):
        """注册 Provider"""
        manager = ProtocolLLMManager()
        prov = openai_provider(api_key="sk-test")
        manager.register_provider("openai", prov)
        assert manager.get_provider("openai") is prov

    def test_get_nonexistent_provider(self):
        """获取不存在的 Provider"""
        manager = ProtocolLLMManager()
        with pytest.raises(LLMProtocolError) as exc_info:
            manager.get_provider("nonexistent")
        assert "not registered" in str(exc_info.value)


# ============================================================================
# 工具函数测试
# ============================================================================


class TestUtils:
    """工具函数测试"""

    def test_status_to_error_code(self):
        """状态码映射"""
        assert _status_to_error_code(400) == LLMErrorCode.INVALID_REQUEST
        assert _status_to_error_code(401) == LLMErrorCode.AUTHENTICATION
        assert _status_to_error_code(403) == LLMErrorCode.AUTHENTICATION
        assert _status_to_error_code(429) == LLMErrorCode.RATE_LIMIT
        assert _status_to_error_code(500) == LLMErrorCode.PROVIDER_INTERNAL
        assert _status_to_error_code(502) == LLMErrorCode.PROVIDER_INTERNAL
        assert _status_to_error_code(503) == LLMErrorCode.PROVIDER_INTERNAL
        assert _status_to_error_code(404) == LLMErrorCode.TRANSPORT

    def test_apply_text_event(self):
        """文本事件应用"""
        from core.llm_protocol import ProtocolLLMResponse as ProtoLLMResponse
        resp = ProtoLLMResponse()
        _apply_event_to_response(resp, LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "Hello"}))
        assert resp.text == "Hello"

    def test_apply_reasoning_event(self):
        """推理事件应用"""
        from core.llm_protocol import ProtocolLLMResponse as ProtoLLMResponse
        resp = ProtoLLMResponse()
        _apply_event_to_response(resp, LLMEvent(type=LLMEventType.REASONING_DELTA, data={"text": "thinking..."}))
        assert resp.reasoning == "thinking..."

    def test_apply_tool_call_event(self):
        """工具调用事件应用"""
        from core.llm_protocol import ProtocolLLMResponse as ProtoLLMResponse
        resp = ProtoLLMResponse()
        tc = ToolCall(id="call_1", name="test", arguments="{}")
        _apply_event_to_response(resp, LLMEvent(type=LLMEventType.TOOL_CALL, data={"tool_call": tc}))
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "call_1"

    def test_apply_finish_event(self):
        """完成事件应用"""
        from core.llm_protocol import ProtocolLLMResponse as ProtoLLMResponse
        resp = ProtoLLMResponse()
        _apply_event_to_response(resp, LLMEvent(type=LLMEventType.FINISH, data={"model": "gpt-4", "finish_reason": "stop"}))
        assert resp.model == "gpt-4"
        assert resp.finish_reason == "stop"


# ============================================================================
# LLMEvent 不可变性测试
# ============================================================================


class TestLLMEvent:
    """LLMEvent 测试"""

    def test_frozen(self):
        """不可变性"""
        event = LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "hi"})
        with pytest.raises(AttributeError):
            event.type = LLMEventType.TEXT_END

    def test_data_mutation(self):
        """data dict 可变（设计如此，方便构建）"""
        event = LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "hi"})
        event.data["extra"] = "ok"
        assert event.data["extra"] == "ok"


# ============================================================================
# 集成测试：模拟完整流式管道
# ============================================================================


class TestIntegration:
    """集成测试"""

    def test_full_text_stream_pipeline(self):
        """完整文本流管道模拟"""
        stream = OpenAIChatStream()
        request = LLMRequest(model="gpt-4")
        state = stream.initial_state(request)
        all_events = []

        # 模拟 SSE 帧序列
        frames = [
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": " World"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "model": "gpt-4", "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
        ]

        for frame in frames:
            event = stream.decode_event(frame)
            if event is None:
                continue
            if stream.terminal(event):
                state, evts = stream.step(state, event)
                all_events.extend(evts)
                break
            state, evts = stream.step(state, event)
            all_events.extend(evts)

        # 验证事件序列
        event_types = [e.type for e in all_events]
        assert event_types[0] == LLMEventType.TEXT_START
        assert event_types[1] == LLMEventType.TEXT_DELTA
        assert event_types[2] == LLMEventType.TEXT_DELTA
        assert LLMEventType.TEXT_END in event_types
        assert LLMEventType.FINISH in event_types

        # 验证最终状态
        assert state.current_text == "Hello World"
        assert state.finish_reason == "stop"
        assert state.usage is not None
        assert state.usage.total_tokens == 7

    def test_full_tool_call_pipeline(self):
        """完整工具调用管道模拟"""
        stream = OpenAIChatStream()
        state = stream.initial_state(LLMRequest())
        all_events = []

        arg_part1 = '{"q'
        arg_part2 = '":"test"}'
        frames = [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "search", "arguments": ""}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arg_part1}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": arg_part2}}]}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]

        for frame in frames:
            event = stream.decode_event(frame)
            if event is None:
                continue
            if stream.terminal(event):
                state, evts = stream.step(state, event)
                all_events.extend(evts)
                break
            state, evts = stream.step(state, event)
            all_events.extend(evts)

        # 验证工具调用
        tool_call_events = [e for e in all_events if e.type == LLMEventType.TOOL_CALL]
        assert len(tool_call_events) == 1
        tc = tool_call_events[0].data["tool_call"]
        assert tc.id == "c1"
        assert tc.name == "search"
        assert tc.arguments == '{"q":"test"}'


# ============================================================================
# SSEFraming 测试（模拟）
# ============================================================================


class _MockAsyncIterator:
    """模拟 aiohttp 响应的异步内容迭代器"""

    def __init__(self, chunks: List[bytes]):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


class TestSSEFraming:
    """SSE Framing 测试"""

    @pytest.mark.asyncio
    async def test_decode_sse(self):
        """SSE 解码"""
        framing = SSEFraming()

        sse_data = 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
        mock_response = MagicMock()
        mock_response.content = _MockAsyncIterator([sse_data.encode("utf-8")])

        frames = []
        async for frame in framing.decode(mock_response):
            frames.append(frame)

        assert len(frames) == 1
        assert frames[0]["choices"][0]["delta"]["content"] == "Hi"

    @pytest.mark.asyncio
    async def test_decode_sse_skip_comments(self):
        """SSE 跳过注释"""
        framing = SSEFraming()

        sse_data = ': this is a comment\ndata: {"ok":true}\n\n'
        mock_response = MagicMock()
        mock_response.content = _MockAsyncIterator([sse_data.encode("utf-8")])

        frames = []
        async for frame in framing.decode(mock_response):
            frames.append(frame)

        assert len(frames) == 1
        assert frames[0] == {"ok": True}

    @pytest.mark.asyncio
    async def test_decode_sse_multiple_frames(self):
        """SSE 多帧解码"""
        framing = SSEFraming()

        sse_data = (
            'data: {"id":1}\n\n'
            'data: {"id":2}\n\n'
            'data: [DONE]\n\n'
        )
        mock_response = MagicMock()
        mock_response.content = _MockAsyncIterator([sse_data.encode("utf-8")])

        frames = []
        async for frame in framing.decode(mock_response):
            frames.append(frame)

        assert len(frames) == 2
        assert frames[0] == {"id": 1}
        assert frames[1] == {"id": 2}

    @pytest.mark.asyncio
    async def test_decode_sse_chunked(self):
        """SSE 分块传输"""
        framing = SSEFraming()

        chunk1 = b'data: {"par'
        chunk2 = b'tial":true}\n\ndata: [DONE]\n\n'
        mock_response = MagicMock()
        mock_response.content = _MockAsyncIterator([chunk1, chunk2])

        frames = []
        async for frame in framing.decode(mock_response):
            frames.append(frame)

        assert len(frames) == 1
        assert frames[0] == {"partial": True}

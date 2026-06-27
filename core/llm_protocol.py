"""
GrassFlow LLM Protocol 抽象层

参考 opencode 的四维模型设计，实现可组合的 LLM 协议层：
  Route = Protocol + Endpoint + Auth + Framing

四维模型：
  1. Protocol  — 语义 API 契约（请求体构造 + 流式响应状态机）
  2. Endpoint  — URL 声明式构造（baseURL + path + query）
  3. Auth      — 可组合的惰性认证链
  4. Framing   — 流式传输帧解码（SSE / 二进制等）

设计原则：
  - 每个维度独立、可替换、不可变组合
  - Protocol 不知道 URL、Header、Auth；只关心 Body -> Frame -> Event -> State 管道
  - Provider 是 Route 的薄门面，通过 route.with() 叠加认证和端点
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

import aiohttp

logger = logging.getLogger(__name__)

# ============================================================================
# 泛型参数
# ============================================================================

BodyT = TypeVar("BodyT")      # 协议原生请求体类型
FrameT = TypeVar("FrameT")    # 传输帧类型（SSE 时为 str）
EventT = TypeVar("EventT")    # 协议原生事件类型
StateT = TypeVar("StateT")    # 流式解析器状态类型

# ============================================================================
# 1. 统一事件系统（LLMEvent）
# ============================================================================


class LLMEventType(str, Enum):
    """统一 LLM 事件类型"""
    STEP_START = "step_start"
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"
    TOOL_INPUT_START = "tool_input_start"
    TOOL_INPUT_DELTA = "tool_input_delta"
    TOOL_INPUT_END = "tool_input_end"
    TOOL_CALL = "tool_call"
    STEP_FINISH = "step_finish"
    FINISH = "finish"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class LLMEvent:
    """统一 LLM 事件（所有协议最终转换为此格式）"""
    type: LLMEventType
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    """Token 用量"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # 细分
    reasoning_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True)
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class LLMResponse:
    """LLM 完整响应（非流式或流式聚合后）"""
    text: str = ""
    reasoning: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    finish_reason: str = ""
    raw_events: List[LLMEvent] = field(default_factory=list)


# ============================================================================
# 2. 统一请求（LLMRequest）
# ============================================================================


@dataclass
class Message:
    """消息"""
    role: str  # system / user / assistant / tool
    content: str = ""
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationOptions:
    """生成选项"""
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[List[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    reasoning_effort: Optional[str] = None  # "low" | "medium" | "high" | "xhigh"


@dataclass
class LLMRequest:
    """统一 LLM 请求"""
    model: str = ""
    messages: List[Message] = field(default_factory=list)
    system: List[Message] = field(default_factory=list)
    tools: List[ToolDefinition] = field(default_factory=list)
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    options: GenerationOptions = field(default_factory=GenerationOptions)
    stream: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 3. 错误类型
# ============================================================================


class LLMErrorCode(str, Enum):
    """LLM 错误码"""
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXCEEDED = "quota_exceeded"
    CONTENT_POLICY = "content_policy"
    PROVIDER_INTERNAL = "provider_internal"
    TRANSPORT = "transport"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class LLMProtocolError(Exception):
    """LLM 协议错误"""

    def __init__(
        self,
        message: str,
        code: LLMErrorCode = LLMErrorCode.UNKNOWN,
        module: str = "",
        method: str = "",
        status_code: Optional[int] = None,
        raw: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.module = module
        self.method = method
        self.status_code = status_code
        self.raw = raw


# ============================================================================
# 4. Auth — 可组合的惰性认证
# ============================================================================


@dataclass
class Credential:
    """
    惰性凭证。

    支持三种来源：
      - 显式值：Credential.of("sk-xxx")
      - 环境变量：Credential.from_env("OPENAI_API_KEY")
      - 异步加载：Credential.from_loader(async_fn)
    """

    _value: Optional[str] = field(default=None, repr=False)
    _env_var: Optional[str] = None
    _loader: Optional[Callable] = None

    @staticmethod
    def of(value: str) -> "Credential":
        """显式值"""
        return Credential(_value=value)

    @staticmethod
    def from_env(env_var: str) -> "Credential":
        """从环境变量加载"""
        return Credential(_env_var=env_var)

    @staticmethod
    def from_loader(loader: Callable) -> "Credential":
        """从异步加载函数加载"""
        return Credential(_loader=loader)

    async def resolve(self) -> Optional[str]:
        """解析凭证值"""
        if self._value is not None:
            return self._value
        if self._env_var:
            val = os.environ.get(self._env_var)
            if val:
                return val
        if self._loader:
            result = self._loader()
            if asyncio.iscoroutine(result):
                return await result
            return result
        return None

    def or_else(self, other: "Credential") -> "Credential":
        """回退链：当前解析失败时尝试 other"""
        return _FallbackCredential(self, other)


class _FallbackCredential(Credential):
    """回退凭证组合器"""

    def __init__(self, primary: Credential, fallback: Credential):
        super().__init__()
        self._primary = primary
        self._fallback = fallback

    async def resolve(self) -> Optional[str]:
        val = await self._primary.resolve()
        if val:
            return val
        return await self._fallback.resolve()


@dataclass
class AuthInput:
    """认证输入上下文"""
    method: str = "POST"
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None


class Auth(ABC):
    """
    认证策略基类。

    Auth 将 AuthInput 的 headers 转换为携带认证信息的 headers。
    支持组合：auth1.and_then(auth2), auth1.or_else(auth2)
    """

    @abstractmethod
    async def apply(self, inp: AuthInput) -> AuthInput:
        """将认证信息应用到请求"""
        ...

    def and_then(self, other: "Auth") -> "Auth":
        """链式组合：先 self，再 other"""
        return _ChainAuth(self, other)

    def or_else(self, other: "Auth") -> "Auth":
        """回退组合：self 失败时尝试 other"""
        return _FallbackAuth(self, other)

    # ── 工厂方法 ──

    @staticmethod
    def none() -> "Auth":
        """无认证"""
        return _NoAuth()

    @staticmethod
    def bearer(credential: Credential) -> "Auth":
        """Bearer Token 认证"""
        return _BearerAuth(credential)

    @staticmethod
    def api_key(credential: Credential, header_name: str = "Authorization") -> "Auth":
        """API Key 认证（放在指定 header 中）"""
        return _HeaderAuth(header_name, credential, prefix="Bearer ")

    @staticmethod
    def header(name: str, credential: Credential, prefix: str = "") -> "Auth":
        """自定义 Header 认证"""
        return _HeaderAuth(name, credential, prefix=prefix)

    @staticmethod
    def headers(headers: Dict[str, str]) -> "Auth":
        """静态 Headers"""
        return _StaticHeadersAuth(headers)

    @staticmethod
    def from_config(
        api_key: Optional[str] = None,
        env_var: Optional[str] = None,
        header_name: str = "Authorization",
        prefix: str = "Bearer ",
    ) -> "Auth":
        """
        标准认证模式：显式 key > 环境变量 > 无认证。

        这是大多数 Provider 使用的标准模式。
        """
        if api_key:
            cred = Credential.of(api_key)
        elif env_var:
            cred = Credential.from_env(env_var)
        else:
            return Auth.none()
        return _HeaderAuth(header_name, cred, prefix=prefix)


class _NoAuth(Auth):
    async def apply(self, inp: AuthInput) -> AuthInput:
        return inp


class _BearerAuth(Auth):
    def __init__(self, credential: Credential):
        self._credential = credential

    async def apply(self, inp: AuthInput) -> AuthInput:
        token = await self._credential.resolve()
        if token:
            inp.headers["Authorization"] = f"Bearer {token}"
        return inp


class _HeaderAuth(Auth):
    def __init__(self, name: str, credential: Credential, prefix: str = ""):
        self._name = name
        self._credential = credential
        self._prefix = prefix

    async def apply(self, inp: AuthInput) -> AuthInput:
        value = await self._credential.resolve()
        if value:
            inp.headers[self._name] = f"{self._prefix}{value}"
        return inp


class _StaticHeadersAuth(Auth):
    def __init__(self, headers: Dict[str, str]):
        self._headers = headers

    async def apply(self, inp: AuthInput) -> AuthInput:
        inp.headers.update(self._headers)
        return inp


class _ChainAuth(Auth):
    def __init__(self, first: Auth, second: Auth):
        self._first = first
        self._second = second

    async def apply(self, inp: AuthInput) -> AuthInput:
        inp = await self._first.apply(inp)
        return await self._second.apply(inp)


class _FallbackAuth(Auth):
    def __init__(self, primary: Auth, fallback: Auth):
        self._primary = primary
        self._fallback = fallback

    async def apply(self, inp: AuthInput) -> AuthInput:
        try:
            return await self._primary.apply(inp)
        except Exception:
            return await self._fallback.apply(inp)


# ============================================================================
# 5. Endpoint — 声明式 URL 构造
# ============================================================================


@dataclass
class Endpoint:
    """
    声明式 URL 构造。

    组合 baseURL + path + query 为最终 URL。
    path 可以是字符串，也可以是根据请求动态生成的函数。
    """

    path: Union[str, Callable[[Dict[str, Any]], str]]
    base_url: str = ""
    query: Dict[str, str] = field(default_factory=dict)

    def render(self, body: Optional[Dict[str, Any]] = None) -> str:
        """渲染最终 URL"""
        base = self.base_url.rstrip("/")
        if callable(self.path):
            p = self.path(body or {})
        else:
            p = self.path
        p = p.lstrip("/")
        url = f"{base}/{p}"
        if self.query:
            qs = "&".join(f"{k}={v}" for k, v in self.query.items())
            url = f"{url}?{qs}"
        return url

    def with_base_url(self, base_url: str) -> "Endpoint":
        """覆盖 base URL"""
        return replace(self, base_url=base_url)


# ============================================================================
# 6. Framing — 流式帧解码
# ============================================================================


class Framing(ABC):
    """
    流式帧解码器。

    将 HTTP 响应体的字节流解码为协议帧流。
    - SSE Framing：字节 -> UTF-8 -> SSE 行解析 -> JSON data payload
    - 未来可扩展：AWS Event Stream（二进制长度前缀 + CRC）
    """

    @abstractmethod
    async def decode(
        self, response: aiohttp.ClientResponse
    ) -> AsyncIterator[Any]:
        """从 HTTP 响应解码帧流"""
        ...


class SSEFraming(Framing):
    """
    Server-Sent Events 帧解码。

    解析 SSE 格式：
      data: {...}\\n\\n

    忽略空行和 [DONE] 终止符。
    每个 emitted frame 是 JSON data payload 的解析结果（dict）。
    """

    async def decode(
        self, response: aiohttp.ClientResponse
    ) -> AsyncIterator[Dict[str, Any]]:
        buffer = ""
        async for raw_chunk in response.content:
            chunk = raw_chunk.decode("utf-8", errors="replace")
            buffer += chunk

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                # 跳过空行和注释
                if not line or line.startswith(":"):
                    continue

                # 解析 SSE data 行
                if line.startswith("data: "):
                    data = line[6:].strip()

                    # 终止符
                    if data == "[DONE]":
                        return

                    # 解析 JSON
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning(f"SSE: 无法解析 JSON: {data[:100]}")
                        continue


class RawStringFraming(Framing):
    """
    原始字符串帧解码（每行一个 JSON）。

    用于非 SSE 的 JSON Lines 流式 API。
    """

    async def decode(
        self, response: aiohttp.ClientResponse
    ) -> AsyncIterator[Dict[str, Any]]:
        buffer = ""
        async for raw_chunk in response.content:
            chunk = raw_chunk.decode("utf-8", errors="replace")
            buffer += chunk

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"RawString: 无法解析 JSON: {line[:100]}")
                    continue


# ============================================================================
# 7. Protocol — 语义 API 契约（状态机）
# ============================================================================


class ProtocolStream(ABC, Generic[FrameT, EventT, StateT]):
    """
    流式响应协议。

    定义从传输帧到统一 LLMEvent 的转换管道：
      Frame -> decode -> Event -> step(State, Event) -> [State, LLMEvent[]]

    四个类型参数：
      FrameT  — 传输帧（SSE 时为 dict）
      EventT  — 协议原生事件
      StateT  — 流式解析器累积状态
    """

    @abstractmethod
    def decode_event(self, frame: FrameT) -> Optional[EventT]:
        """将传输帧解码为协议事件"""
        ...

    @abstractmethod
    def initial_state(self, request: LLMRequest) -> StateT:
        """创建初始解析器状态"""
        ...

    @abstractmethod
    def step(
        self, state: StateT, event: EventT
    ) -> Tuple[StateT, List[LLMEvent]]:
        """
        状态转移：消费一个协议事件，产出 0~N 个统一事件。

        返回 (new_state, events)
        """
        ...

    def terminal(self, event: EventT) -> bool:
        """判断事件是否为流终止信号（可选覆盖）"""
        return False

    def on_halt(self, state: StateT) -> List[LLMEvent]:
        """流结束时的最终刷新（可选覆盖）"""
        return []


class ProtocolBody(ABC, Generic[BodyT]):
    """
    请求体协议。

    定义如何将统一 LLMRequest 转换为协议原生请求体。
    """

    @abstractmethod
    def encode(self, request: LLMRequest) -> BodyT:
        """将统一请求编码为协议原生请求体"""
        ...


class Protocol(ABC, Generic[BodyT, FrameT, EventT, StateT]):
    """
    完整协议定义。

    组合请求体编码和流式响应处理。
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """协议标识符"""
        ...

    @property
    @abstractmethod
    def body(self) -> ProtocolBody[BodyT]:
        """请求体编码器"""
        ...

    @property
    @abstractmethod
    def stream(self) -> ProtocolStream[FrameT, EventT, StateT]:
        """流式响应处理器"""
        ...


# ============================================================================
# 8. Route — 四维组合点
# ============================================================================


@dataclass
class PreparedRequest:
    """已准备的 HTTP 请求"""
    url: str
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""


class Route(Generic[BodyT, FrameT, EventT, StateT]):
    """
    Route = Protocol + Endpoint + Auth + Framing

    四维组合的核心抽象。不可变设计——通过 with_() 创建派生 Route。
    """

    def __init__(
        self,
        route_id: str,
        protocol: Protocol[BodyT, FrameT, EventT, StateT],
        endpoint: Endpoint,
        auth: Auth,
        framing: Framing,
        default_model: str = "",
    ):
        self._id = route_id
        self._protocol = protocol
        self._endpoint = endpoint
        self._auth = auth
        self._framing = framing
        self._default_model = default_model

    @property
    def id(self) -> str:
        return self._id

    @property
    def protocol(self) -> Protocol[BodyT, FrameT, EventT, StateT]:
        return self._protocol

    @property
    def endpoint(self) -> Endpoint:
        return self._endpoint

    @property
    def auth(self) -> Auth:
        return self._auth

    @property
    def framing(self) -> Framing:
        return self._framing

    def with_(self, **kwargs) -> "Route":
        """
        不可变修补——创建派生 Route。

        支持覆盖：endpoint, auth, framing, default_model
        """
        return Route(
            route_id=kwargs.get("route_id", self._id),
            protocol=self._protocol,
            endpoint=kwargs.get("endpoint", self._endpoint),
            auth=kwargs.get("auth", self._auth),
            framing=kwargs.get("framing", self._framing),
            default_model=kwargs.get("default_model", self._default_model),
        )

    def model(self, model_id: str) -> "Model":
        """创建绑定到此 Route 的 Model"""
        return Model(model_id=model_id, route=self)

    async def prepare(self, request: LLMRequest) -> PreparedRequest:
        """
        准备 HTTP 请求。

        流程：encode body -> render URL -> apply auth -> build headers
        """
        # 1. 编码请求体
        body_data = self._protocol.body.encode(request)
        body_json = json.dumps(body_data, ensure_ascii=False)

        # 2. 渲染 URL
        url = self._endpoint.render(
            body_data if isinstance(body_data, dict) else {}
        )

        # 3. 应用认证
        auth_input = AuthInput(
            method="POST",
            url=url,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            body=body_json.encode("utf-8"),
        )
        auth_result = await self._auth.apply(auth_input)

        return PreparedRequest(
            url=url,
            method="POST",
            headers=auth_result.headers,
            body=body_json,
        )

    async def stream_events(
        self, request: LLMRequest
    ) -> AsyncIterator[LLMEvent]:
        """
        完整的流式请求管道。

        流程：
          prepare -> HTTP POST -> framing.decode -> protocol.decode_event
          -> protocol.step -> LLMEvent stream
        """
        prepared = await self.prepare(request)
        stream_processor = self._protocol.stream
        state = stream_processor.initial_state(request)

        # 执行 HTTP 请求
        timeout = aiohttp.ClientTimeout(total=request.extra.get("timeout", 120))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                prepared.url,
                headers=prepared.headers,
                data=prepared.body,
            ) as response:
                if response.status != 200:
                    error_body = await response.text()
                    code = _status_to_error_code(response.status)
                    raise LLMProtocolError(
                        f"HTTP {response.status}: {error_body[:500]}",
                        code=code,
                        module=self._id,
                        method="stream_events",
                        status_code=response.status,
                        raw=error_body,
                    )

                # 产出 step_start
                yield LLMEvent(type=LLMEventType.STEP_START)

                # 流式处理
                async for frame in self._framing.decode(response):
                    event = stream_processor.decode_event(frame)
                    if event is None:
                        continue

                    if stream_processor.terminal(event):
                        # 终止事件也过一遍 step
                        state, events = stream_processor.step(state, event)
                        for e in events:
                            yield e
                        break

                    state, events = stream_processor.step(state, event)
                    for e in events:
                        yield e

            # 流结束时的最终刷新
            for e in stream_processor.on_halt(state):
                yield e

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """
        非流式请求——收集所有事件后返回完整响应。
        """
        request = replace(request, stream=False)
        response = LLMResponse()

        async for event in self.stream_events(request):
            response.raw_events.append(event)
            _apply_event_to_response(response, event)

        return response


# ============================================================================
# 9. Model — 绑定到 Route 的模型
# ============================================================================


@dataclass
class Model:
    """绑定到 Route 的模型"""
    model_id: str
    route: Route

    def make_request(
        self,
        messages: List[Message],
        system: Optional[List[Message]] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        options: Optional[GenerationOptions] = None,
        stream: bool = True,
        **extra,
    ) -> LLMRequest:
        """创建 LLMRequest"""
        return LLMRequest(
            model=self.model_id,
            messages=messages,
            system=system or [],
            tools=tools or [],
            tool_choice=tool_choice,
            options=options or GenerationOptions(),
            stream=stream,
            extra=extra,
        )

    async def stream_events(
        self,
        messages: List[Message],
        system: Optional[List[Message]] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        options: Optional[GenerationOptions] = None,
        **extra,
    ) -> AsyncIterator[LLMEvent]:
        """流式请求"""
        request = self.make_request(
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            options=options,
            stream=True,
            **extra,
        )
        async for event in self.route.stream_events(request):
            yield event

    async def complete(
        self,
        messages: List[Message],
        system: Optional[List[Message]] = None,
        tools: Optional[List[ToolDefinition]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        options: Optional[GenerationOptions] = None,
        **extra,
    ) -> LLMResponse:
        """非流式请求"""
        request = self.make_request(
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            options=options,
            stream=False,
            **extra,
        )
        return await self.route.complete(request)


# ============================================================================
# 10. OpenAI Chat Protocol 实现
# ============================================================================


# ── 请求体编码 ──


class OpenAIChatBody(ProtocolBody[Dict[str, Any]]):
    """OpenAI Chat Completions 请求体编码"""

    def encode(self, request: LLMRequest) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": request.model,
            "stream": request.stream,
        }

        # 合并 system + messages
        messages = []
        for sys_msg in request.system:
            messages.append({"role": "system", "content": sys_msg.content})
        for msg in request.messages:
            m: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                m["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(m)
        body["messages"] = messages

        # 工具定义
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]

        # tool_choice
        if request.tool_choice is not None:
            body["tool_choice"] = request.tool_choice

        # 生成选项
        opts = request.options
        if opts.max_tokens is not None:
            body["max_tokens"] = opts.max_tokens
        if opts.temperature is not None:
            body["temperature"] = opts.temperature
        if opts.top_p is not None:
            body["top_p"] = opts.top_p
        if opts.stop is not None:
            body["stop"] = opts.stop
        if opts.presence_penalty is not None:
            body["presence_penalty"] = opts.presence_penalty
        if opts.frequency_penalty is not None:
            body["frequency_penalty"] = opts.frequency_penalty
        if opts.seed is not None:
            body["seed"] = opts.seed
        if opts.reasoning_effort is not None:
            body["reasoning_effort"] = opts.reasoning_effort

        # 额外参数
        body.update(request.extra.get("provider_options", {}))

        return body


# ── 流式解析状态 ──


@dataclass
class _ToolCallAccumulator:
    """工具调用增量累积器"""
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class OpenAIChatState:
    """OpenAI Chat 流式解析器状态"""
    current_text: str = ""
    current_reasoning: str = ""
    tool_calls: Dict[int, _ToolCallAccumulator] = field(default_factory=dict)
    finish_reason: str = ""
    model: str = ""
    usage: Optional[Usage] = None


# ── 流式协议 ──


class OpenAIChatStream(ProtocolStream[Dict[str, Any], Dict[str, Any], OpenAIChatState]):
    """
    OpenAI Chat Completions 流式协议。

    帧管道：SSE JSON dict -> decode_event -> step -> LLMEvent[]
    """

    def decode_event(self, frame: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """SSE 帧已经是 dict，直接返回"""
        return frame

    def initial_state(self, request: LLMRequest) -> OpenAIChatState:
        return OpenAIChatState()

    def step(
        self, state: OpenAIChatState, event: Dict[str, Any]
    ) -> Tuple[OpenAIChatState, List[LLMEvent]]:
        events: List[LLMEvent] = []

        # 更新模型信息
        if "model" in event:
            state.model = event["model"]

        # 更新用量
        if "usage" in event and event["usage"]:
            u = event["usage"]
            state.usage = Usage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
                cached_tokens=u.get("prompt_tokens_details", {}).get(
                    "cached_tokens", 0
                ),
                reasoning_tokens=u.get("completion_tokens_details", {}).get(
                    "reasoning_tokens", 0
                ),
            )

        choices = event.get("choices", [])
        if not choices:
            return state, events

        choice = choices[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        # 文本内容增量
        content = delta.get("content")
        if content:
            if not state.current_text:
                events.append(LLMEvent(type=LLMEventType.TEXT_START))
            state.current_text += content
            events.append(
                LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": content})
            )

        # 推理内容增量（部分模型支持）
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning:
            if not state.current_reasoning:
                events.append(LLMEvent(type=LLMEventType.REASONING_START))
            state.current_reasoning += reasoning
            events.append(
                LLMEvent(
                    type=LLMEventType.REASONING_DELTA,
                    data={"text": reasoning},
                )
            )

        # 工具调用增量
        tool_calls_delta = delta.get("tool_calls", [])
        for tc_delta in tool_calls_delta:
            idx = tc_delta.get("index", 0)
            if idx not in state.tool_calls:
                state.tool_calls[idx] = _ToolCallAccumulator()
                events.append(
                    LLMEvent(
                        type=LLMEventType.TOOL_INPUT_START,
                        data={"index": idx},
                    )
                )

            acc = state.tool_calls[idx]
            if tc_delta.get("id"):
                acc.id = tc_delta["id"]
            func = tc_delta.get("function", {})
            if func.get("name"):
                acc.name = func["name"]
            if func.get("arguments"):
                acc.arguments += func["arguments"]
                events.append(
                    LLMEvent(
                        type=LLMEventType.TOOL_INPUT_DELTA,
                        data={
                            "index": idx,
                            "arguments": func["arguments"],
                        },
                    )
                )

        # finish_reason 处理
        if finish_reason:
            state.finish_reason = finish_reason

            # 结束文本
            if state.current_text:
                events.append(LLMEvent(type=LLMEventType.TEXT_END))

            # 结束推理
            if state.current_reasoning:
                events.append(LLMEvent(type=LLMEventType.REASONING_END))

            # 完成工具调用
            for idx, acc in state.tool_calls.items():
                if acc.id and acc.name:
                    events.append(
                        LLMEvent(
                            type=LLMEventType.TOOL_INPUT_END,
                            data={"index": idx},
                        )
                    )
                    events.append(
                        LLMEvent(
                            type=LLMEventType.TOOL_CALL,
                            data={
                                "tool_call": ToolCall(
                                    id=acc.id,
                                    name=acc.name,
                                    arguments=acc.arguments,
                                ),
                            },
                        )
                    )

            # 步骤完成
            events.append(
                LLMEvent(
                    type=LLMEventType.STEP_FINISH,
                    data={"finish_reason": finish_reason},
                )
            )

            # 流结束
            events.append(
                LLMEvent(
                    type=LLMEventType.FINISH,
                    data={
                        "model": state.model,
                        "finish_reason": finish_reason,
                    },
                )
            )

        return state, events

    def terminal(self, event: Dict[str, Any]) -> bool:
        choices = event.get("choices", [])
        if choices:
            return choices[0].get("finish_reason") is not None
        return False

    def on_halt(self, state: OpenAIChatState) -> List[LLMEvent]:
        """流意外中断时的清理"""
        events = []
        if state.current_text and state.finish_reason != "stop":
            events.append(LLMEvent(type=LLMEventType.TEXT_END))
        if state.current_reasoning and state.finish_reason != "stop":
            events.append(LLMEvent(type=LLMEventType.REASONING_END))
        return events


# ── 完整协议 ──


class OpenAIChatProtocol(Protocol[Dict[str, Any], Dict[str, Any], Dict[str, Any], OpenAIChatState]):
    """OpenAI Chat Completions 协议"""

    @property
    def id(self) -> str:
        return "openai-chat"

    @property
    def body(self) -> ProtocolBody[Dict[str, Any]]:
        return self._body

    @property
    def stream(self) -> ProtocolStream[Dict[str, Any], Dict[str, Any], OpenAIChatState]:
        return self._stream

    def __init__(self):
        self._body = OpenAIChatBody()
        self._stream = OpenAIChatStream()


# ── 预定义 Route ──


_openai_chat_protocol = OpenAIChatProtocol()

OPENAI_CHAT_ROUTE = Route(
    route_id="openai-chat",
    protocol=_openai_chat_protocol,
    endpoint=Endpoint(path="/v1/chat/completions", base_url="https://api.openai.com"),
    auth=Auth.from_config(env_var="OPENAI_API_KEY"),
    framing=SSEFraming(),
    default_model="gpt-4",
)

# DeepSeek 兼容 OpenAI Chat 协议
DEEPSEEK_CHAT_ROUTE = OPENAI_CHAT_ROUTE.with_(
    route_id="deepseek-chat",
    endpoint=Endpoint(path="/chat/completions", base_url="https://api.deepseek.com"),
    auth=Auth.from_config(env_var="DEEPSEEK_API_KEY"),
    default_model="deepseek-chat",
)

# Ollama 兼容 OpenAI Chat 协议
OLLAMA_CHAT_ROUTE = OPENAI_CHAT_ROUTE.with_(
    route_id="ollama-chat",
    endpoint=Endpoint(path="/v1/chat/completions", base_url="http://localhost:11434"),
    auth=Auth.none(),
    default_model="llama3",
)


# ============================================================================
# 11. Provider — Route 的薄门面
# ============================================================================


class Provider:
    """
    Provider 是 Route 的薄门面。

    职责：
      - 持有配置（api_key, base_url 等）
      - 通过 with_() 叠加认证和端点覆盖
      - 提供 model() 工厂方法
    """

    def __init__(
        self,
        provider_id: str,
        route: Route,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = "",
    ):
        self._id = provider_id
        self._route = route
        self._api_key = api_key
        self._base_url = base_url
        self._default_model = default_model or route._default_model
        self._configured_route: Optional[Route] = None

    @property
    def id(self) -> str:
        return self._id

    def _get_configured_route(self) -> Route:
        """获取已配置的 Route（惰性构建）"""
        if self._configured_route is not None:
            return self._configured_route

        patches: Dict[str, Any] = {}
        if self._base_url:
            patches["endpoint"] = self._endpoint.with_base_url(self._base_url)
        if self._api_key:
            patches["auth"] = Auth.bearer(Credential.of(self._api_key))

        self._configured_route = self._route.with_(**patches) if patches else self._route
        return self._configured_route

    @property
    def _endpoint(self) -> Endpoint:
        if self._base_url:
            return self._route.endpoint.with_base_url(self._base_url)
        return self._route.endpoint

    def model(self, model_id: Optional[str] = None) -> Model:
        """创建 Model"""
        route = self._get_configured_route()
        return Model(
            model_id=model_id or self._default_model,
            route=route,
        )


# ── 预定义 Provider 工厂 ──


def openai_provider(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    default_model: str = "gpt-4",
) -> Provider:
    """创建 OpenAI Provider"""
    return Provider(
        provider_id="openai",
        route=OPENAI_CHAT_ROUTE,
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
    )


def deepseek_provider(
    api_key: Optional[str] = None,
    default_model: str = "deepseek-chat",
    **kwargs,
) -> Provider:
    """创建 DeepSeek Provider"""
    return Provider(
        provider_id="deepseek",
        route=DEEPSEEK_CHAT_ROUTE,
        api_key=api_key,
        default_model=default_model,
    )


def ollama_provider(
    base_url: str = "http://localhost:11434",
    default_model: str = "llama3",
    **kwargs,
) -> Provider:
    """创建 Ollama Provider"""
    return Provider(
        provider_id="ollama",
        route=OLLAMA_CHAT_ROUTE,
        base_url=base_url,
        default_model=default_model,
    )


def custom_provider(
    provider_id: str,
    base_url: str,
    api_key: Optional[str] = None,
    path: str = "/v1/chat/completions",
    default_model: str = "gpt-4",
    env_var: Optional[str] = None,
) -> Provider:
    """
    创建自定义 Provider（兼容 OpenAI Chat 协议的任意端点）。

    适用于 Azure、TogetherAI、Cerebras 等兼容端点。
    """
    if api_key:
        auth = Auth.bearer(Credential.of(api_key))
    elif env_var:
        auth = Auth.from_config(env_var=env_var)
    else:
        auth = Auth.none()

    route = OPENAI_CHAT_ROUTE.with_(
        route_id=provider_id,
        endpoint=Endpoint(path=path, base_url=base_url),
        auth=auth,
        default_model=default_model,
    )
    return Provider(
        provider_id=provider_id,
        route=route,
        default_model=default_model,
    )


# ============================================================================
# 12. 兼容层 — 适配现有 LLMClient 接口
# ============================================================================


class ProtocolLLMClient:
    """
    基于协议层的 LLM 客户端，兼容现有 LLMClient 接口。

    可以无缝替换 core.llm.LLMClient 使用。

    用法：
        client = ProtocolLLMClient.from_provider("openai", api_key="sk-xxx", model="gpt-4")
        response = await client.chat(messages=[{"role": "user", "content": "hello"}])
    """

    def __init__(self, model: Model):
        self._model = model

    @staticmethod
    def from_provider(
        provider_name: str = "openai",
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> "ProtocolLLMClient":
        """
        从 Provider 名称创建客户端。

        支持：openai, deepseek, ollama, custom
        """
        provider_map: Dict[str, Callable[..., Provider]] = {
            "openai": openai_provider,
            "deepseek": deepseek_provider,
            "ollama": ollama_provider,
        }

        if provider_name in provider_map:
            factory = provider_map[provider_name]
            prov = factory(api_key=api_key, base_url=base_url, default_model=model, **kwargs)
        else:
            # 自定义 Provider（假设兼容 OpenAI Chat）
            prov = custom_provider(
                provider_id=provider_name,
                base_url=base_url or "https://api.openai.com",
                api_key=api_key,
                default_model=model,
            )

        return ProtocolLLMClient(model=prov.model(model))

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> "LLMResponse":
        """
        发送聊天请求（兼容现有 LLMClient.chat 接口）。

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            temperature: 温度
            max_tokens: 最大 token 数
            stream: 是否流式（默认 False，兼容现有接口）
            reasoning_effort: 推理力度 ("low" | "medium" | "high" | "xhigh")
            **kwargs: 其他参数

        Returns:
            兼容的 LLMResponse
        """
        # 转换消息格式
        proto_messages = []
        system_messages = []
        for m in messages:
            msg = Message(
                role=m["role"],
                content=m.get("content", ""),
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
            )
            if "tool_calls" in m and m["tool_calls"]:
                tcs = []
                for tc_data in m["tool_calls"]:
                    if isinstance(tc_data, ToolCall):
                        tcs.append(tc_data)
                    elif isinstance(tc_data, dict):
                        tcs.append(ToolCall(
                            id=tc_data.get("id", ""),
                            name=tc_data.get("name", tc_data.get("function", {}).get("name", "")),
                            arguments=tc_data.get("arguments", tc_data.get("function", {}).get("arguments", "")),
                        ))
                msg.tool_calls = tcs
            if m["role"] == "system":
                system_messages.append(msg)
            else:
                proto_messages.append(msg)

        options = GenerationOptions(
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

        request = self._model.make_request(
            messages=proto_messages,
            system=system_messages,
            options=options,
            stream=stream,
            **kwargs,
        )

        response = await self._model.route.complete(request)

        # 返回兼容格式
        return _LegacyLLMResponse(
            content=response.text,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            finish_reason=response.finish_reason,
            tool_calls=response.tool_calls or None,
        )

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[LLMEvent]:
        """
        流式聊天请求。

        Yields:
            LLMEvent 事件流
        """
        proto_messages = []
        system_messages = []
        for m in messages:
            msg = Message(
                role=m["role"],
                content=m.get("content", ""),
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
            )
            if "tool_calls" in m and m["tool_calls"]:
                tcs = []
                for tc_data in m["tool_calls"]:
                    if isinstance(tc_data, ToolCall):
                        tcs.append(tc_data)
                    elif isinstance(tc_data, dict):
                        tcs.append(ToolCall(
                            id=tc_data.get("id", ""),
                            name=tc_data.get("name", tc_data.get("function", {}).get("name", "")),
                            arguments=tc_data.get("arguments", tc_data.get("function", {}).get("arguments", "")),
                        ))
                msg.tool_calls = tcs
            if m["role"] == "system":
                system_messages.append(msg)
            else:
                proto_messages.append(msg)

        options = GenerationOptions(
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

        async for event in self._model.stream_events(
            messages=proto_messages,
            system=system_messages,
            options=options,
            **kwargs,
        ):
            yield event

    async def complete(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> "LLMResponse":
        """发送补全请求（兼容现有 LLMClient.complete 接口）"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature, max_tokens, **kwargs)


@dataclass
class _LegacyLLMResponse:
    """兼容现有 LLMResponse 的响应类型"""
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str
    tool_calls: Optional[List[ToolCall]] = None


# ============================================================================
# 13. ProtocolLLMManager — 协议层管理器
# ============================================================================


class ProtocolLLMManager:
    """
    协议层 LLM 管理器。

    管理多个 Provider 和 Model，兼容现有 LLMManager 接口。
    """

    def __init__(self):
        self._providers: Dict[str, Provider] = {}
        self._clients: Dict[str, ProtocolLLMClient] = {}

    def register_provider(self, name: str, provider: Provider) -> None:
        """注册 Provider"""
        self._providers[name] = provider

    def get_provider(self, name: str) -> Provider:
        """获取 Provider"""
        if name not in self._providers:
            raise LLMProtocolError(
                f"Provider '{name}' not registered",
                code=LLMErrorCode.INVALID_REQUEST,
                module="ProtocolLLMManager",
                method="get_provider",
            )
        return self._providers[name]

    def create_client(
        self,
        name: str,
        provider_name: str = "openai",
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> ProtocolLLMClient:
        """创建并注册客户端"""
        client = ProtocolLLMClient.from_provider(
            provider_name=provider_name,
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
        self._clients[name] = client
        return client

    def get_client(self, name: str) -> ProtocolLLMClient:
        """获取客户端"""
        if name not in self._clients:
            raise LLMProtocolError(
                f"Client '{name}' not registered",
                code=LLMErrorCode.INVALID_REQUEST,
                module="ProtocolLLMManager",
                method="get_client",
            )
        return self._clients[name]


# 全局协议层管理器
protocol_manager = ProtocolLLMManager()


# ============================================================================
# 内部工具函数
# ============================================================================


def _status_to_error_code(status: int) -> LLMErrorCode:
    """HTTP 状态码 -> 错误码"""
    if status == 400:
        return LLMErrorCode.INVALID_REQUEST
    elif status in (401, 403):
        return LLMErrorCode.AUTHENTICATION
    elif status == 429:
        return LLMErrorCode.RATE_LIMIT
    elif status in (500, 502, 503):
        return LLMErrorCode.PROVIDER_INTERNAL
    else:
        return LLMErrorCode.TRANSPORT


def _apply_event_to_response(response: LLMResponse, event: LLMEvent) -> None:
    """将事件应用到响应对象（用于 complete 聚合）"""
    if event.type == LLMEventType.TEXT_DELTA:
        response.text += event.data.get("text", "")
    elif event.type == LLMEventType.REASONING_DELTA:
        response.reasoning += event.data.get("text", "")
    elif event.type == LLMEventType.TOOL_CALL:
        tc = event.data.get("tool_call")
        if tc:
            response.tool_calls.append(tc)
    elif event.type == LLMEventType.FINISH:
        response.model = event.data.get("model", "")
        response.finish_reason = event.data.get("finish_reason", "")
    elif event.type == LLMEventType.STEP_FINISH:
        pass  # FINISH 会覆盖

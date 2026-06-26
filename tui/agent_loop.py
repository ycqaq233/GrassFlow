"""
GrassFlow Agent Loop — 核心对话循环

参考 Hermes agent/conversation_loop.py 的循环结构实现。

循环流程：
  1. 用户输入 → 构建 messages
  2. LLM 调用（流式） → 产出文本/工具调用事件
  3. 如果有工具调用 → 通过 ToolRegistry 执行 → 结果反馈 → 回到步骤 2
  4. 如果没有工具调用 → 产出最终文本 → 结束

设计原则：
  - AsyncIterator[LoopEvent] 实时推送事件
  - 支持中断 (interrupt)
  - 支持最大迭代次数限制 (max_iterations)
  - 集成 core/llm_protocol.py 的协议层和 core/tool_registry.py 的工具注册表
  - 集成 Doom Loop 检测防止无限工具调用循环
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from core.llm_protocol import (
    LLMEvent,
    LLMEventType,
    LLMRequest,
    LLMResponse,
    Message,
    ProtocolLLMClient,
    ProtocolLLMManager,
    ToolDefinition,
    ToolCall,
    GenerationOptions,
    Usage,
    openai_provider,
    deepseek_provider,
    ollama_provider,
    custom_provider,
)
from core.tool_registry import (
    ToolRegistry,
    ToolDef,
    ToolResult,
    ToolContext,
    ToolPermission,
    ToolSource,
    get_default_registry,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 事件类型
# ============================================================================


class LoopEventType(str, Enum):
    """Agent Loop 事件类型"""
    # 生命周期
    LOOP_START = "loop_start"
    LOOP_END = "loop_end"
    # 文本
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    # 思考/推理（reasoning 模型）
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    # 工具调用
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_ARGS = "tool_call_args"
    TOOL_CALL_END = "tool_call_end"
    TOOL_RESULT = "tool_result"
    # 错误
    ERROR = "error"
    INTERRUPTED = "interrupted"
    # 使用统计
    USAGE = "usage"


@dataclass
class LoopEvent:
    """Agent Loop 事件"""
    type: str  # LoopEventType 值
    data: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def of(event_type: str, **data: Any) -> "LoopEvent":
        return LoopEvent(type=event_type, data=data)


# ============================================================================
# Agent Loop 状态
# ============================================================================


class LoopStatus(str, Enum):
    """Agent Loop 状态"""
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class LoopState:
    """Agent Loop 运行时状态"""
    status: LoopStatus = LoopStatus.IDLE
    iteration_count: int = 0
    max_iterations: int = 30
    api_call_count: int = 0
    tool_call_count: int = 0
    start_time: float = 0.0
    last_activity_time: float = 0.0
    current_model: str = ""
    current_provider: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error_message: str = ""


# ============================================================================
# 工具执行器
# ============================================================================


@dataclass
class ToolExecutionResult:
    """工具执行结果"""
    tool_id: str
    tool_name: str
    success: bool
    output: str
    elapsed_ms: float = 0.0
    is_error: bool = False


class ToolExecutor:
    """
    工具执行器，封装 ToolRegistry 的调用逻辑。

    负责：
      - 将 LLM 产出的工具调用分发到 ToolRegistry
      - 处理执行错误
      - 记录 Doom Loop 检测所需的信息
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        abort_signal: Optional[asyncio.Event] = None,
        agent_name: str = "",
    ):
        self._registry = registry or get_default_registry()
        self._abort_signal = abort_signal
        self._agent_name = agent_name

    async def execute(
        self,
        tool_call: ToolCall,
        session_id: str = "",
    ) -> ToolExecutionResult:
        """执行单个工具调用"""
        tool_id = tool_call.id
        tool_args: Dict[str, Any] = {}

        # 解析参数
        try:
            tool_args = json.loads(tool_call.arguments) if tool_call.arguments else {}
        except json.JSONDecodeError:
            return ToolExecutionResult(
                tool_id=tool_id,
                tool_name=tool_call.name,
                success=False,
                output=f"Invalid JSON arguments: {tool_call.arguments[:200]}",
                is_error=True,
            )

        ctx = ToolContext(
            session_id=session_id,
            agent_name=self._agent_name,
            message_id=tool_call.id,
            call_id=tool_call.id,
            abort_signal=self._abort_signal,
        )

        start = time.monotonic()
        try:
            result = await self._registry.invoke(tool_call.name, tool_args, ctx)
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolExecutionResult(
                tool_id=tool_id,
                tool_name=tool_call.name,
                success=not result.is_error,
                output=result.output,
                elapsed_ms=elapsed_ms,
                is_error=result.is_error,
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning(f"Tool '{tool_id}' execution failed: {e}")
            return ToolExecutionResult(
                tool_id=tool_id,
                tool_name=tool_call.name,
                success=False,
                output=str(e),
                elapsed_ms=elapsed_ms,
                is_error=True,
            )


# ============================================================================
# Agent Loop — 核心实现
# ============================================================================


class AgentLoop:
    """
    核心对话循环，管理 LLM 和工具调用的迭代。

    使用模式::

        loop = AgentLoop(
            client=ProtocolLLMClient.from_provider("deepseek", model="deepseek-chat"),
            tool_registry=tool_registry,
        )

        async for event in loop.process(
            user_message="帮我读一下 README.md",
            conversation_history=[],
            system_prompt="你是一个有用的助手",
        ):
            if event.type == "text_delta":
                print(event.data["text"], end="", flush=True)
            elif event.type == "tool_call_start":
                print(f"\n[调用工具: {event.data['name']}]")

    设计参考：
      - Hermes agent/conversation_loop.py 的 run_conversation 结构
      - 感知 -> 思考 -> 行动 -> 观察 循环
    """

    def __init__(
        self,
        client: Optional[ProtocolLLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
        max_iterations: int = 30,
        max_retries: int = 3,
        system_prompt: str = "",
        provider_name: str = "deepseek",
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_doom_loop_detection: bool = True,
        tools: Optional[List[ToolDefinition]] = None,
    ):
        """
        初始化 Agent Loop。

        Args:
            client: LLM 客户端（优先使用）
            tool_registry: 工具注册表
            max_iterations: 最大迭代次数
            max_retries: LLM 调用失败最大重试次数
            system_prompt: 默认系统提示词
            provider_name: Provider 名称（client 未提供时使用）
            model: 模型名称（client 未提供时使用）
            api_key: API Key（client 未提供时使用）
            base_url: API Base URL（client 未提供时使用）
            enable_doom_loop_detection: 是否启用 Doom Loop 检测
            tools: 额外的工具定义列表
        """
        # LLM 客户端
        if client:
            self._client = client
        else:
            self._client = ProtocolLLMClient.from_provider(
                provider_name=provider_name,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )

        # 工具注册表
        self._tool_registry = tool_registry or get_default_registry()

        # 工具执行器
        self._abort_signal = asyncio.Event()
        self._tool_executor = ToolExecutor(
            registry=self._tool_registry,
            abort_signal=self._abort_signal,
        )

        # 配置
        self._max_iterations = max_iterations
        self._max_retries = max_retries
        self._default_system_prompt = system_prompt
        self._enable_doom_loop_detection = enable_doom_loop_detection
        self._extra_tools = tools or []

        # 运行时状态
        self._state = LoopState()
        self._state.max_iterations = max_iterations

        # Doom Loop 检测
        self._doom_detector: Optional[Any] = None
        if enable_doom_loop_detection:
            try:
                from core.doom_loop import DoomLoopDetector, DoomLoopConfig, DoomLoopAction
                self._doom_detector = DoomLoopDetector(
                    DoomLoopConfig(
                        max_repeated_calls=5,
                        action=DoomLoopAction.LOG_WARNING,
                    )
                )
            except ImportError:
                logger.debug("DoomLoopDetector not available, skipping doom loop detection")

        # 许可请求回调
        self._permission_callback: Optional[Any] = None

    # ---- 公共属性 ----

    @property
    def status(self) -> LoopStatus:
        return self._state.status

    @property
    def iteration_count(self) -> int:
        return self._state.iteration_count

    @property
    def api_call_count(self) -> int:
        return self._state.api_call_count

    @property
    def tool_call_count(self) -> int:
        return self._state.tool_call_count

    # ---- 配置方法 ----

    def set_permission_callback(self, callback) -> None:
        """设置许可请求回调。

        callback 签名: async def callback(tool_id: str, permission: str) -> bool
        返回 True 表示允许，False 表示拒绝。
        """
        self._permission_callback = callback

    def set_tools(self, tools: List[ToolDefinition]) -> None:
        """设置工具定义列表"""
        self._extra_tools = tools

    # ---- 核心方法 ----

    async def process(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[LoopEvent]:
        """
        处理用户消息，运行完整的对话循环。

        Args:
            user_message: 用户消息文本
            conversation_history: 对话历史 [{"role": "user", "content": "..."}, ...]
            system_prompt: 系统提示词（覆盖默认值）

        Yields:
            LoopEvent 事件流
        """
        # 重置状态
        self._state = LoopState(
            status=LoopStatus.RUNNING,
            max_iterations=self._max_iterations,
            start_time=time.monotonic(),
            last_activity_time=time.monotonic(),
        )
        self._abort_signal.clear()

        # 重置 Doom Loop 检测器
        if self._doom_detector:
            try:
                self._doom_detector.reset()
            except Exception:
                pass

        yield LoopEvent.of(LoopEventType.LOOP_START.value)

        # 构建初始消息
        messages = self._build_initial_messages(
            user_message, conversation_history or [], system_prompt
        )

        try:
            # ── 主循环 ──
            while (
                self._state.iteration_count < self._max_iterations
                and not self._abort_signal.is_set()
            ):
                self._state.iteration_count += 1

                # 1. 检查中断
                if self._abort_signal.is_set():
                    yield LoopEvent.of(LoopEventType.INTERRUPTED.value)
                    break

                # 2. API 调用
                self._state.api_call_count += 1
                response = await self._call_llm_with_retry(messages)

                if response is None:
                    # 所有重试都失败了
                    yield LoopEvent.of(
                        LoopEventType.ERROR.value,
                        message="LLM call failed after all retries",
                    )
                    break

                # 更新使用统计
                if response.usage:
                    self._state.total_input_tokens += response.usage.prompt_tokens or 0
                    self._state.total_output_tokens += response.usage.completion_tokens or 0

                # 3. 处理响应
                if response.tool_calls:
                    # ── 工具调用路径 ──
                    # 添加 assistant 消息（含 tool_calls）
                    assistant_msg = Message(
                        role="assistant",
                        content=response.text or "",
                        tool_calls=response.tool_calls,
                    )
                    messages.append(assistant_msg)

                    # 执行工具调用
                    for tc in response.tool_calls:
                        # 中断检查
                        if self._abort_signal.is_set():
                            yield LoopEvent.of(LoopEventType.INTERRUPTED.value)
                            break

                        # Doom Loop 检测
                        should_continue = await self._check_doom_loop(tc.name, tc.arguments)
                        if not should_continue:
                            yield LoopEvent.of(
                                LoopEventType.ERROR.value,
                                message=f"Doom Loop detected: repeated call to '{tc.name}'",
                            )
                            break

                        # 发送工具调用开始事件
                        yield LoopEvent.of(
                            LoopEventType.TOOL_CALL_START.value,
                            name=tc.name,
                            args=tc.arguments,
                        )

                        # 执行工具
                        self._state.tool_call_count += 1
                        result = await self._tool_executor.execute(tc)
                        self._state.last_activity_time = time.monotonic()

                        # 发送工具结果事件
                        yield LoopEvent.of(
                            LoopEventType.TOOL_RESULT.value,
                            name=tc.name,
                            output=result.output,
                            success=result.success,
                            elapsed_ms=result.elapsed_ms,
                        )

                        # 构建 tool result 消息
                        tool_msg = Message(
                            role="tool",
                            content=result.output,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                        messages.append(tool_msg)

                    # 继续循环（LLM 会看到工具结果后决定下一步）
                    continue

                else:
                    # ── 文本响应路径（最终输出）──
                    final_text = response.text

                    if final_text:
                        yield LoopEvent.of(
                            LoopEventType.TEXT_START.value,
                        )
                        yield LoopEvent.of(
                            LoopEventType.TEXT_DELTA.value,
                            text=final_text,
                        )
                        yield LoopEvent.of(
                            LoopEventType.TEXT_END.value,
                            text=final_text,
                        )

                    # 检查 finish_reason
                    finish_reason = response.finish_reason
                    if finish_reason == "tool_calls":
                        # LLM 的 tool_calls 列表可能未被正确解析
                        # 如果最终没有工具调用但有这个 finish_reason，继续循环
                        logger.warning(
                            "finish_reason=tool_calls but no tool calls parsed, ending loop"
                        )

                    break

            # ── 循环结束 ──
            self._state.status = LoopStatus.COMPLETED
            yield LoopEvent.of(
                LoopEventType.LOOP_END.value,
                iterations=self._state.iteration_count,
                api_calls=self._state.api_call_count,
                tool_calls=self._state.tool_call_count,
            )

        except Exception as e:
            self._state.status = LoopStatus.ERROR
            self._state.error_message = str(e)
            logger.error(f"Agent loop error: {e}", exc_info=True)
            yield LoopEvent.of(
                LoopEventType.ERROR.value,
                message=str(e),
            )

    async def process_streaming(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[LoopEvent]:
        """
        处理用户消息 — 流式版本。

        与 process() 的区别是 LLM 调用使用真正的流式 API，
        文本以 TEXT_DELTA 增量事件逐个发出，体验更流畅。

        Args:
            user_message: 用户消息文本
            conversation_history: 对话历史
            system_prompt: 系统提示词

        Yields:
            LoopEvent 事件流（含流式文本增量）
        """
        # 重置状态
        self._state = LoopState(
            status=LoopStatus.RUNNING,
            max_iterations=self._max_iterations,
            start_time=time.monotonic(),
            last_activity_time=time.monotonic(),
        )
        self._abort_signal.clear()

        if self._doom_detector:
            try:
                self._doom_detector.reset()
            except Exception:
                pass

        yield LoopEvent.of(LoopEventType.LOOP_START.value)

        # 构建初始消息
        messages = self._build_initial_messages(
            user_message, conversation_history or [], system_prompt
        )

        # 收集工具定义
        all_tools = self._gather_tool_definitions()

        try:
            while (
                self._state.iteration_count < self._max_iterations
                and not self._abort_signal.is_set()
            ):
                self._state.iteration_count += 1

                if self._abort_signal.is_set():
                    yield LoopEvent.of(LoopEventType.INTERRUPTED.value)
                    break

                self._state.api_call_count += 1

                # ── 流式 LLM 调用 ──
                collected_text = ""
                collected_reasoning = ""
                collected_tool_calls: Dict[int, ToolCall] = {}
                finish_reason = ""

                try:
                    proto_messages: List[Message] = []
                    for m in messages:
                        msg = Message(
                            role=m.get("role", "user"),
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
                        proto_messages.append(msg)  # 包含 system 消息，由 stream_chat 自动分离

                    # 扁平化消息时保留 tool_call_id 和 name
                    _stream_msgs = []
                    for m in proto_messages:
                        _msg = {"role": m.role, "content": m.content}
                        if hasattr(m, "tool_call_id") and m.tool_call_id:
                            _msg["tool_call_id"] = m.tool_call_id
                        if hasattr(m, "name") and m.name:
                            _msg["name"] = m.name
                        _stream_msgs.append(_msg)

                    async for event in self._client.stream_chat(
                        messages=_stream_msgs,
                        temperature=0.7,
                    ):
                        if self._abort_signal.is_set():
                            break

                        if event.type == LLMEventType.TEXT_DELTA:
                            text_delta = event.data.get("text", "")
                            collected_text += text_delta
                            yield LoopEvent.of(
                                LoopEventType.TEXT_DELTA.value,
                                text=text_delta,
                            )

                        elif event.type == LLMEventType.REASONING_DELTA:
                            reasoning_delta = event.data.get("text", "")
                            collected_reasoning += reasoning_delta
                            yield LoopEvent.of(
                                LoopEventType.THINKING_DELTA.value,
                                text=reasoning_delta,
                            )

                        elif event.type == LLMEventType.TOOL_CALL:
                            tc = event.data.get("tool_call")
                            if tc:
                                collected_tool_calls[len(collected_tool_calls)] = tc
                                yield LoopEvent.of(
                                    LoopEventType.TOOL_CALL_START.value,
                                    name=tc.name,
                                    args=tc.arguments,
                                )

                        elif event.type == LLMEventType.FINISH:
                            finish_reason = event.data.get("finish_reason", "")
                            # 提取 usage 信息并更新统计
                            usage_data = event.data.get("usage")
                            if usage_data:
                                if isinstance(usage_data, dict):
                                    self._state.total_input_tokens += usage_data.get("prompt_tokens", 0)
                                    self._state.total_output_tokens += usage_data.get("completion_tokens", 0)

                except Exception as e:
                    logger.error(f"Streaming LLM call failed: {e}")
                    yield LoopEvent.of(
                        LoopEventType.ERROR.value,
                        message=f"LLM streaming failed: {e}",
                    )
                    break

                # 更新活动时间戳
                self._state.last_activity_time = time.monotonic()

                # 处理响应
                tc_list = [collected_tool_calls[i] for i in sorted(collected_tool_calls.keys())]

                if tc_list:
                    # 工具调用路径
                    # 添加 assistant 消息
                    assistant_msg_data = {
                        "role": "assistant",
                        "content": collected_text,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments},
                            }
                            for tc in tc_list
                        ],
                    }
                    messages.append(assistant_msg_data)

                    for tc in tc_list:
                        if self._abort_signal.is_set():
                            yield LoopEvent.of(LoopEventType.INTERRUPTED.value)
                            break

                        should_continue = await self._check_doom_loop(tc.name, tc.arguments)
                        if not should_continue:
                            yield LoopEvent.of(
                                LoopEventType.ERROR.value,
                                message=f"Doom Loop detected: repeated call to '{tc.name}'",
                            )
                            break

                        self._state.tool_call_count += 1
                        result = await self._tool_executor.execute(tc)
                        self._state.last_activity_time = time.monotonic()

                        yield LoopEvent.of(
                            LoopEventType.TOOL_CALL_END.value,
                            name=tc.name,
                            args=tc.arguments,
                        )

                        yield LoopEvent.of(
                            LoopEventType.TOOL_RESULT.value,
                            name=tc.name,
                            output=result.output,
                            success=result.success,
                            elapsed_ms=result.elapsed_ms,
                        )

                        tool_msg_data = {
                            "role": "tool",
                            "content": result.output,
                            "tool_call_id": tc.id,
                        }
                        messages.append(tool_msg_data)

                    continue

                else:
                    # 文本响应路径
                    if collected_text:
                        yield LoopEvent.of(
                            LoopEventType.TEXT_END.value,
                            text=collected_text,
                        )
                    break

            # ── 循环结束 ──
            self._state.status = LoopStatus.COMPLETED
            yield LoopEvent.of(
                LoopEventType.LOOP_END.value,
                iterations=self._state.iteration_count,
                api_calls=self._state.api_call_count,
                tool_calls=self._state.tool_call_count,
            )

        except Exception as e:
            self._state.status = LoopStatus.ERROR
            self._state.error_message = str(e)
            logger.error(f"Agent loop streaming error: {e}", exc_info=True)
            yield LoopEvent.of(
                LoopEventType.ERROR.value,
                message=str(e),
            )

    def interrupt(self) -> None:
        """中断当前 Agent Loop 执行"""
        self._abort_signal.set()
        if self._state.status == LoopStatus.RUNNING:
            self._state.status = LoopStatus.INTERRUPTED

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态信息"""
        elapsed = 0.0
        if self._state.start_time > 0:
            elapsed = time.monotonic() - self._state.start_time

        return {
            "status": self._state.status.value,
            "iteration_count": self._state.iteration_count,
            "max_iterations": self._state.max_iterations,
            "api_call_count": self._state.api_call_count,
            "tool_call_count": self._state.tool_call_count,
            "elapsed_seconds": round(elapsed, 2),
            "current_model": self._state.current_model,
            "current_provider": self._state.current_provider,
            "total_input_tokens": self._state.total_input_tokens,
            "total_output_tokens": self._state.total_output_tokens,
            "error_message": self._state.error_message,
        }

    def reset(self) -> None:
        """重置 Agent Loop 状态"""
        self._state = LoopState(max_iterations=self._max_iterations)
        self._abort_signal.clear()
        if self._doom_detector:
            try:
                self._doom_detector.reset()
            except Exception:
                pass

    # ---- 内部方法 ----

    def _build_initial_messages(
        self,
        user_message: str,
        conversation_history: List[Dict[str, Any]],
        system_prompt: Optional[str],
    ) -> List[Dict[str, Any]]:
        """构建初始消息列表"""
        messages: List[Dict[str, Any]] = []

        # 系统提示
        sp = system_prompt or self._default_system_prompt
        if sp:
            messages.append({"role": "system", "content": sp})

        # 对话历史
        for entry in conversation_history:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            msg: Dict[str, Any] = {"role": role, "content": content}
            # 保留 tool_calls 和 tool_call_id
            if "tool_calls" in entry:
                msg["tool_calls"] = entry["tool_calls"]
            if "tool_call_id" in entry:
                msg["tool_call_id"] = entry["tool_call_id"]
            if "name" in entry:
                msg["name"] = entry["name"]
            messages.append(msg)

        # 当前用户消息
        if user_message and (not messages or messages[-1].get("role") != "user"):
            messages.append({"role": "user", "content": user_message})

        return messages

    def _gather_tool_definitions(self) -> List[ToolDefinition]:
        """收集所有工具定义"""
        tools: List[ToolDefinition] = list(self._extra_tools)

        # 从 ToolRegistry 获取已注册的工具
        try:
            for tool_def in self._tool_registry.enabled_tools():
                tools.append(ToolDefinition(
                    name=tool_def.id,
                    description=tool_def.description,
                    parameters=tool_def.parameter_schema(),
                ))
        except Exception as e:
            logger.warning(f"Failed to gather tools from registry: {e}")

        return tools

    async def _call_llm_with_retry(
        self,
        messages: List[Dict[str, Any]],
    ) -> Optional[LLMResponse]:
        """LLM 调用（带重试）"""
        last_error = None

        for attempt in range(self._max_retries):
            try:
                # 转换消息格式并调用（保留 tool_call_id 和 name）
                chat_messages: List[Dict[str, str]] = []
                for m in messages:
                    msg: Dict[str, Any] = {
                        "role": m.get("role", "user"),
                        "content": m.get("content", ""),
                    }
                    if m.get("tool_call_id"):
                        msg["tool_call_id"] = m["tool_call_id"]
                    if m.get("name"):
                        msg["name"] = m["name"]
                    chat_messages.append(msg)

                response = await self._client.chat(
                    messages=chat_messages,
                    temperature=0.7,
                )

                # 转换回 LLMResponse（ProtocolLLMClient.chat 返回 _LegacyLLMResponse）
                raw_usage = response.usage if hasattr(response, 'usage') and response.usage else {}
                # 提取 tool_calls（如果有）
                tool_calls = None
                if hasattr(response, 'tool_calls') and response.tool_calls:
                    raw_tcs = response.tool_calls
                    tool_calls = []
                    for tc in raw_tcs:
                        if isinstance(tc, ToolCall):
                            tool_calls.append(tc)
                        elif isinstance(tc, dict):
                            tool_calls.append(ToolCall(
                                id=tc.get("id", ""),
                                name=tc.get("name", tc.get("function", {}).get("name", "")),
                                arguments=tc.get("arguments", tc.get("function", {}).get("arguments", "")),
                            ))
                return LLMResponse(
                    text=response.content,
                    model=response.model,
                    usage=Usage(
                        prompt_tokens=raw_usage.get("prompt_tokens", 0),
                        completion_tokens=raw_usage.get("completion_tokens", 0),
                        total_tokens=raw_usage.get("total_tokens", 0),
                    ),
                    finish_reason=response.finish_reason,
                    tool_calls=tool_calls,
                )

            except Exception as e:
                last_error = e
                logger.warning(
                    f"LLM call attempt {attempt + 1}/{self._max_retries} failed: {e}"
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避

        logger.error(f"LLM call failed after {self._max_retries} retries: {last_error}")
        return None

    async def _check_doom_loop(self, tool_name: str, arguments: str) -> bool:
        """检查是否出现 Doom Loop。

        Returns:
            True 表示可以继续，False 表示检测到循环
        """
        if not self._doom_detector:
            return True

        try:
            args_dict: Dict[str, Any] = {}
            try:
                args_dict = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                args_dict = {"_raw_args": arguments}

            detection = self._doom_detector.check_call(tool_name, args_dict)
            if detection.detected:
                logger.warning(
                    f"Doom Loop detected: tool='{tool_name}' called "
                    f"{detection.call_count} times. Message: {detection.message}"
                )
                return False

            return True
        except Exception as e:
            logger.debug(f"Doom loop check failed (non-fatal): {e}")
            return True


# ============================================================================
# AgentLoop 工厂函数
# ============================================================================


def create_agent_loop(
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None,
    max_iterations: int = 30,
    system_prompt: str = "",
) -> AgentLoop:
    """
    快速创建 AgentLoop 的工厂函数。

    Args:
        provider: Provider 名称 (openai, deepseek, ollama, custom)
        model: 模型名称
        api_key: API Key
        base_url: API Base URL（custom provider 时使用）
        tool_registry: 工具注册表
        max_iterations: 最大迭代次数
        system_prompt: 默认系统提示词

    Returns:
        配置好的 AgentLoop 实例
    """
    client = ProtocolLLMClient.from_provider(
        provider_name=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )

    return AgentLoop(
        client=client,
        tool_registry=tool_registry,
        max_iterations=max_iterations,
        system_prompt=system_prompt,
        provider_name=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


# ============================================================================
# 便捷函数: 从配置创建 AgentLoop
# ============================================================================


def create_agent_loop_from_config(
    tool_registry: Optional[ToolRegistry] = None,
) -> AgentLoop:
    """从 GrassFlow 配置创建 AgentLoop。

    读取 core.config 中的 LLM 配置，自动选择合适的 provider 和 model。

    Args:
        tool_registry: 工具注册表

    Returns:
        配置好的 AgentLoop 实例
    """
    try:
        from core.config import config_manager

        config = config_manager.load_config()
        provider_name = config.llm.default_provider or "deepseek"
        model = config.llm.default_model or "deepseek-chat"

        # 尝试获取 API Key
        api_key = None
        base_url = None

        # 从 provider 配置获取 api_key 和 base_url
        provider_config = config.provider.get(provider_name)
        if provider_config:
            # 兼容 camelCase（opencode 格式）和 snake_case 两种命名
            opts = getattr(provider_config, "options", None)
            if opts:
                api_key = getattr(opts, "apiKey", None) or getattr(opts, "api_key", None)
                base_url = getattr(opts, "baseURL", None) or getattr(opts, "base_url", None)

        # 特殊处理 ollama
        if provider_name == "ollama":
            api_key = None

        return create_agent_loop(
            provider=provider_name,
            model=model,
            api_key=api_key,
            base_url=base_url,
            tool_registry=tool_registry,
            max_iterations=config.workflow.execution_timeout
            if hasattr(config.workflow, "execution_timeout")
            else 30,
        )

    except ImportError:
        logger.warning(
            "Config module not available, using defaults (deepseek/deepseek-chat)"
        )
        return create_agent_loop(tool_registry=tool_registry)
    except Exception as e:
        logger.warning(f"Failed to create AgentLoop from config: {e}, using defaults")
        return create_agent_loop(tool_registry=tool_registry)

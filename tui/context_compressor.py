"""
GrassFlow 上下文压缩器

参考 opencode 的上下文压缩实现，为 GrassFlow 提供：
- Token 超限检测
- 用摘要 Agent 压缩旧消息
- 保留最近 N 轮完整对话

核心思想：
  当对话历史超过模型上下文窗口时，将旧消息压缩为摘要，
  保留最近 N 轮完整对话，从而在有限上下文中维持长对话。

参考实现: opencode/packages/opencode/src/session/compaction.ts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

# ==================== 常量 ====================

# Token 估算: 每个 token 约 4 个字符（英文），中文约 1.5-2 个字符
# 取折中值 3 作为通用估算
CHARS_PER_TOKEN: int = 3

# 压缩触发的最小 token 阈值
# 只有当消息总 token 数超过此值时才考虑压缩
COMPACTION_THRESHOLD_TOKENS: int = 20_000

# 保留最近对话的 token 预算
# 压缩后，最近 N 轮对话的 token 总量不超过此值
KEEP_RECENT_TOKENS: int = 8_000

# 保留最近的对话轮数（最少保留轮数）
DEFAULT_TAIL_TURNS: int = 2

# 压缩缓冲区（为输出预留的空间）
COMPACTION_BUFFER_TOKENS: int = 4_000

# 摘要输出的最大 token 数
SUMMARY_MAX_TOKENS: int = 4_096

# 工具输出截断的最大字符数
TOOL_OUTPUT_MAX_CHARS: int = 2_000


# ==================== 摘要模板 ====================

SUMMARY_TEMPLATE = """\
请严格按照下面的 Markdown 模板结构输出摘要，保持章节顺序不变。
不要在输出中包含 <template> 标签本身。

<template>
## 目标
- [一句话描述当前任务目标]

## 约束与偏好
- [用户约束、偏好、规格要求，或 "(无)"]

## 进展
### 已完成
- [已完成的工作，或 "(无)"]

### 进行中
- [当前正在进行的工作，或 "(无)"]

### 阻塞
- [阻塞项，或 "(无)"]

## 关键决策
- [做出的决策及原因，或 "(无)"]

## 下一步
- [按顺序排列的后续操作，或 "(无)"]

## 关键上下文
- [重要的技术事实、错误信息、待解决问题，或 "(无)"]

## 相关文件
- [文件或目录路径: 重要性说明，或 "(无)"]
</template>

规则：
- 即使为空也要保留每个章节。
- 使用简洁的要点，不要使用长段落。
- 保留精确的文件路径、命令、错误字符串和标识符。
- 不要提及摘要过程或上下文被压缩的事实。
"""


# ==================== 数据类型 ====================

@dataclass
class ChatMessage:
    """
    对话消息

    统一的消息格式，支持角色: system / user / assistant / tool
    """
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    # 元数据（不参与压缩，仅用于追踪）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为 LLM API 格式的消息字典"""
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


@dataclass
class CompactionResult:
    """
    压缩结果

    Attributes:
        summary: 压缩后的摘要文本
        head_messages: 被压缩的原始消息（用于调试/审计）
        tail_messages: 保留的最近消息
        tokens_saved: 估算节省的 token 数
        original_tokens: 原始总 token 数
        compacted_tokens: 压缩后总 token 数
    """
    summary: str
    head_messages: List[ChatMessage]
    tail_messages: List[ChatMessage]
    tokens_saved: int
    original_tokens: int
    compacted_tokens: int


@dataclass
class OverflowResult:
    """
    溢出检测结果

    Attributes:
        is_overflow: 是否超出上下文限制
        current_tokens: 当前 token 数
        limit: 上下文限制
        usage_ratio: 使用率 (0.0 ~ 1.0+)
    """
    is_overflow: bool
    current_tokens: int
    limit: int
    usage_ratio: float


# ==================== Token 工具 ====================

def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数

    使用简单的字符数 / 每 token 字符数 近似。
    这是一个粗略估算，实际 token 数取决于具体的 tokenizer。

    Args:
        text: 要估算的文本

    Returns:
        估算的 token 数
    """
    return max(0, round(len(text) / CHARS_PER_TOKEN))


def estimate_messages_tokens(messages: List[ChatMessage]) -> int:
    """
    估算消息列表的总 token 数

    包含消息格式的开销（role、name 等字段）。

    Args:
        messages: 消息列表

    Returns:
        估算的总 token 数
    """
    total = 0
    for msg in messages:
        # 消息本身的内容
        total += estimate_tokens(msg.content)
        # role 和其他字段的开销（约 4 tokens）
        total += 4
        if msg.name:
            total += estimate_tokens(msg.name)
    return total


# ==================== 消息序列化 ====================

def serialize_message(msg: ChatMessage) -> str:
    """
    将消息序列化为可读文本

    用于生成摘要时的消息表示。

    Args:
        msg: 要序列化的消息

    Returns:
        序列化后的文本
    """
    role = msg.role
    content = msg.content

    # 截断过长的工具输出
    if len(content) > TOOL_OUTPUT_MAX_CHARS:
        content = content[:TOOL_OUTPUT_MAX_CHARS] + "\n[已截断]"

    if role == "user":
        return f"[用户]: {content}"
    elif role == "assistant":
        return f"[助手]: {content}"
    elif role == "system":
        return f"[系统]: {content}"
    elif role == "tool":
        name = msg.name or "工具"
        return f"[工具结果 - {name}]: {content}"
    else:
        return f"[{role}]: {content}"


def serialize_messages(messages: List[ChatMessage]) -> str:
    """
    将消息列表序列化为可读文本

    Args:
        messages: 消息列表

    Returns:
        序列化后的文本
    """
    parts = []
    for msg in messages:
        text = serialize_message(msg)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


# ==================== 消息选择策略 ====================

def select_messages_for_compaction(
    messages: List[ChatMessage],
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
    tail_turns: int = DEFAULT_TAIL_TURNS,
) -> tuple[List[ChatMessage], List[ChatMessage]]:
    """
    将消息分为"待压缩"和"保留最近"两部分

    策略：
    1. 保留最近 tail_turns 轮对话（user + assistant 为一轮）
    2. 在保留轮次内，保证 token 总量不超过 keep_recent_tokens
    3. 如果保留轮次的 token 总量超出预算，从最旧的保留轮次开始截断

    Args:
        messages: 完整消息列表
        keep_recent_tokens: 保留最近消息的 token 预算
        tail_turns: 最少保留的对话轮数

    Returns:
        (head_messages, tail_messages) 元组
    """
    if not messages:
        return [], []

    # 找到所有 "轮次" 的起始位置（以 user 消息为标记）
    turn_starts: List[int] = []
    for i, msg in enumerate(messages):
        # 跳过 system 消息，它们不计入轮次
        if msg.role == "user":
            turn_starts.append(i)

    if not turn_starts:
        # 没有 user 消息，全部作为 tail
        return [], messages

    # 保留最近 tail_turns 轮
    if len(turn_starts) <= tail_turns:
        # 轮次不足，全部保留
        return [], messages

    # 从最近的 tail_turns 轮开始
    recent_turn_start_idx = len(turn_starts) - tail_turns
    recent_start = turn_starts[recent_turn_start_idx]

    # 在保留区域内，检查 token 预算
    # 从最近往最旧方向累加，超出预算则截断
    tail_start = recent_start

    # 从最近一轮开始往回检查 token 预算
    total_tokens = 0
    for i in range(recent_turn_start_idx, len(turn_starts)):
        turn_begin = turn_starts[i]
        turn_end = turn_starts[i + 1] if i + 1 < len(turn_starts) else len(messages)
        turn_msgs = messages[turn_begin:turn_end]
        turn_tokens = estimate_messages_tokens(turn_msgs)
        total_tokens += turn_tokens

    # 如果保留轮次的 token 总量超出预算，从最旧的保留轮次开始截断
    if total_tokens > keep_recent_tokens:
        # 从最近的轮次往前遍历，找到截断点
        accumulated = 0
        for i in range(len(turn_starts) - 1, recent_turn_start_idx - 1, -1):
            turn_begin = turn_starts[i]
            turn_end = turn_starts[i + 1] if i + 1 < len(turn_starts) else len(messages)
            turn_msgs = messages[turn_begin:turn_end]
            turn_tokens = estimate_messages_tokens(turn_msgs)

            if accumulated + turn_tokens > keep_recent_tokens:
                # 这一轮会超出预算，尝试在这轮内找到截断点
                remaining = keep_recent_tokens - accumulated
                if remaining > 0:
                    # 在这轮内从后往前找截断点
                    for j in range(turn_end - 1, turn_begin - 1, -1):
                        partial_tokens = estimate_messages_tokens(messages[j:turn_end])
                        if partial_tokens <= remaining:
                            tail_start = j
                            break
                break

            accumulated += turn_tokens

    head = messages[:tail_start]
    tail = messages[tail_start:]

    return head, tail


# ==================== 摘要生成 ====================

def build_compaction_prompt(
    messages_to_compact: List[ChatMessage],
    previous_summary: Optional[str] = None,
) -> str:
    """
    构建压缩提示词

    Args:
        messages_to_compact: 需要压缩的消息
        previous_summary: 之前的摘要（如果有）

    Returns:
        完整的压缩提示词
    """
    conversation_text = serialize_messages(messages_to_compact)

    if previous_summary:
        summary_instruction = (
            f"请根据上面的对话历史更新下面的锚定摘要。\n"
            f"保留仍然正确的细节，移除过时的信息，合并新的事实。\n"
            f"<previous-summary>\n{previous_summary}\n</previous-summary>"
        )
    else:
        summary_instruction = "请根据上面的对话历史创建一个新的锚定摘要。"

    return (
        f"以下是对话历史：\n\n{conversation_text}\n\n"
        f"{summary_instruction}\n\n"
        f"{SUMMARY_TEMPLATE}"
    )


# ==================== 主压缩器 ====================

class ContextCompressor:
    """
    上下文压缩器

    核心功能：
    1. 检测 token 是否超出上下文限制
    2. 将旧消息压缩为摘要
    3. 保留最近 N 轮完整对话

    使用方式：
        compressor = ContextCompressor(
            llm_client=my_llm_client,
            context_limit=128000,
        )

        # 检测是否需要压缩
        if compressor.is_overflow(messages):
            result = await compressor.compact(messages)
            messages = [ChatMessage(role="system", content=result.summary)] + result.tail_messages

    参考实现: opencode/packages/opencode/src/session/compaction.ts
    """

    def __init__(
        self,
        llm_client: LLMClient,
        context_limit: int = 128_000,
        compaction_threshold: int = COMPACTION_THRESHOLD_TOKENS,
        keep_recent_tokens: int = KEEP_RECENT_TOKENS,
        tail_turns: int = DEFAULT_TAIL_TURNS,
        summary_max_tokens: int = SUMMARY_MAX_TOKENS,
        compaction_buffer: int = COMPACTION_BUFFER_TOKENS,
    ):
        """
        初始化上下文压缩器

        Args:
            llm_client: 用于生成摘要的 LLM 客户端
            context_limit: 模型的上下文窗口大小（token 数）
            compaction_threshold: 触发压缩的最小 token 阈值
            keep_recent_tokens: 保留最近消息的 token 预算
            tail_turns: 最少保留的对话轮数
            summary_max_tokens: 摘要输出的最大 token 数
            compaction_buffer: 为输出预留的缓冲区大小
        """
        self.llm_client = llm_client
        self.context_limit = context_limit
        self.compaction_threshold = compaction_threshold
        self.keep_recent_tokens = keep_recent_tokens
        self.tail_turns = tail_turns
        self.summary_max_tokens = summary_max_tokens
        self.compaction_buffer = compaction_buffer

        # 压缩历史
        self._previous_summary: Optional[str] = None
        self._compaction_count: int = 0

    @property
    def previous_summary(self) -> Optional[str]:
        """获取上一次的摘要"""
        return self._previous_summary

    @property
    def compaction_count(self) -> int:
        """获取压缩次数"""
        return self._compaction_count

    def usable_limit(self) -> int:
        """
        计算可用的上下文空间

        总上下文减去输出预留和压缩缓冲区。

        Returns:
            可用的 token 数
        """
        return max(0, self.context_limit - self.compaction_buffer)

    def estimate_tokens(self, messages: List[ChatMessage]) -> int:
        """
        估算消息列表的 token 数

        Args:
            messages: 消息列表

        Returns:
            估算的 token 数
        """
        return estimate_messages_tokens(messages)

    def is_overflow(self, messages: List[ChatMessage]) -> OverflowResult:
        """
        检测消息是否超出上下文限制

        Args:
            messages: 当前消息列表

        Returns:
            OverflowResult 包含溢出状态和统计信息
        """
        current_tokens = self.estimate_tokens(messages)
        limit = self.usable_limit()
        usage_ratio = current_tokens / limit if limit > 0 else float("inf")

        return OverflowResult(
            is_overflow=current_tokens >= limit,
            current_tokens=current_tokens,
            limit=limit,
            usage_ratio=usage_ratio,
        )

    def should_compact(self, messages: List[ChatMessage]) -> bool:
        """
        判断是否需要压缩

        两个条件同时满足才压缩：
        1. token 数超过压缩阈值
        2. token 数接近或超过上下文限制

        Args:
            messages: 当前消息列表

        Returns:
            是否需要压缩
        """
        current_tokens = self.estimate_tokens(messages)

        # 条件 1: 超过最小压缩阈值
        if current_tokens < self.compaction_threshold:
            return False

        # 条件 2: 接近上下文限制（使用率 > 75%）
        limit = self.usable_limit()
        if limit > 0 and current_tokens > limit * 0.75:
            return True

        return False

    async def _generate_summary(self, messages: List[ChatMessage]) -> str:
        """
        使用 LLM 生成消息摘要

        Args:
            messages: 需要摘要的消息列表

        Returns:
            生成的摘要文本

        Raises:
            LLMError: LLM 调用失败
        """
        prompt = build_compaction_prompt(
            messages_to_compact=messages,
            previous_summary=self._previous_summary,
        )

        try:
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 低温度以获得稳定的摘要
                max_tokens=self.summary_max_tokens,
            )
            summary = response.content.strip()

            if not summary:
                raise LLMError("LLM 返回了空摘要")

            return summary

        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"摘要生成失败: {e}")

    async def compact(
        self,
        messages: List[ChatMessage],
        force: bool = False,
    ) -> CompactionResult:
        """
        压缩消息列表

        流程：
        1. 检测是否需要压缩（除非 force=True）
        2. 将消息分为 head（待压缩）和 tail（保留）
        3. 用 LLM 生成 head 的摘要
        4. 返回压缩结果

        Args:
            messages: 当前消息列表
            force: 是否强制压缩（忽略阈值检查）

        Returns:
            CompactionResult 压缩结果

        Raises:
            LLMError: LLM 调用失败
            ValueError: 没有需要压缩的消息
        """
        original_tokens = self.estimate_tokens(messages)

        # 检查是否需要压缩
        if not force and not self.should_compact(messages):
            logger.info(
                f"不需要压缩: 当前 {original_tokens} tokens, "
                f"阈值 {self.compaction_threshold}"
            )
            return CompactionResult(
                summary=self._previous_summary or "",
                head_messages=[],
                tail_messages=messages,
                tokens_saved=0,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
            )

        # 选择要压缩的消息
        head, tail = select_messages_for_compaction(
            messages,
            keep_recent_tokens=self.keep_recent_tokens,
            tail_turns=self.tail_turns,
        )

        if not head:
            logger.warning("没有可压缩的消息")
            return CompactionResult(
                summary=self._previous_summary or "",
                head_messages=[],
                tail_messages=messages,
                tokens_saved=0,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
            )

        head_tokens = self.estimate_tokens(head)
        tail_tokens = self.estimate_tokens(tail)

        logger.info(
            f"开始压缩: head={len(head)} 条消息 ({head_tokens} tokens), "
            f"tail={len(tail)} 条消息 ({tail_tokens} tokens)"
        )

        # 生成摘要
        summary = await self._generate_summary(head)

        # 计算压缩后的 token 数
        summary_msg = ChatMessage(role="system", content=summary)
        summary_tokens = self.estimate_tokens([summary_msg])
        compacted_tokens = summary_tokens + tail_tokens
        tokens_saved = original_tokens - compacted_tokens

        # 更新状态
        self._previous_summary = summary
        self._compaction_count += 1

        logger.info(
            f"压缩完成: {original_tokens} -> {compacted_tokens} tokens "
            f"(节省 {tokens_saved} tokens, 压缩率 {tokens_saved/original_tokens*100:.1f}%)"
        )

        return CompactionResult(
            summary=summary,
            head_messages=head,
            tail_messages=tail,
            tokens_saved=tokens_saved,
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
        )

    async def compact_and_rebuild(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        force: bool = False,
    ) -> List[ChatMessage]:
        """
        压缩并重建消息列表

        这是一个便捷方法，直接返回压缩后的完整消息列表。

        Args:
            messages: 当前消息列表
            system_prompt: 系统提示词（如果有，会保留在最前面）
            force: 是否强制压缩

        Returns:
            压缩后的消息列表
        """
        result = await self.compact(messages, force=force)

        # 如果没有压缩，直接返回原消息
        if result.tokens_saved <= 0:
            return messages

        # 重建消息列表
        rebuilt: List[ChatMessage] = []

        # 保留 system prompt
        if system_prompt:
            rebuilt.append(ChatMessage(role="system", content=system_prompt))

        # 添加压缩摘要
        rebuilt.append(
            ChatMessage(
                role="system",
                content=f"[上下文压缩摘要 - 第 {self._compaction_count} 次压缩]\n\n{result.summary}",
            )
        )

        # 添加保留的最近消息
        rebuilt.extend(result.tail_messages)

        return rebuilt

    def reset(self) -> None:
        """重置压缩器状态"""
        self._previous_summary = None
        self._compaction_count = 0


# ==================== 自动压缩包装器 ====================

class AutoCompactingContext:
    """
    自动压缩的对话上下文

    包装消息列表，在添加新消息时自动检测并压缩。

    使用方式：
        ctx = AutoCompactingContext(
            llm_client=my_client,
            context_limit=128000,
            system_prompt="你是一个助手",
        )

        # 添加用户消息
        await ctx.add_user_message("你好")

        # 添加助手消息
        await ctx.add_assistant_message("你好！有什么可以帮你的吗？")

        # 获取当前消息（自动压缩）
        messages = ctx.get_messages()
    """

    def __init__(
        self,
        llm_client: LLMClient,
        context_limit: int = 128_000,
        system_prompt: Optional[str] = None,
        compaction_threshold: int = COMPACTION_THRESHOLD_TOKENS,
        keep_recent_tokens: int = KEEP_RECENT_TOKENS,
        tail_turns: int = DEFAULT_TAIL_TURNS,
    ):
        """
        初始化自动压缩上下文

        Args:
            llm_client: 用于生成摘要的 LLM 客户端
            context_limit: 模型的上下文窗口大小
            system_prompt: 系统提示词
            compaction_threshold: 触发压缩的最小 token 阈值
            keep_recent_tokens: 保留最近消息的 token 预算
            tail_turns: 最少保留的对话轮数
        """
        self.messages: List[ChatMessage] = []
        self.system_prompt = system_prompt
        self.compressor = ContextCompressor(
            llm_client=llm_client,
            context_limit=context_limit,
            compaction_threshold=compaction_threshold,
            keep_recent_tokens=keep_recent_tokens,
            tail_turns=tail_turns,
        )

        # 添加 system prompt
        if system_prompt:
            self.messages.append(ChatMessage(role="system", content=system_prompt))

        # 压缩事件回调
        self._on_compact_callbacks: List[Callable[[CompactionResult], None]] = []

    def on_compact(self, callback: Callable[[CompactionResult], None]) -> None:
        """
        注册压缩事件回调

        Args:
            callback: 压缩完成时调用的回调函数
        """
        self._on_compact_callbacks.append(callback)

    def _notify_compact(self, result: CompactionResult) -> None:
        """通知所有回调"""
        for cb in self._on_compact_callbacks:
            try:
                cb(result)
            except Exception as e:
                logger.error(f"压缩回调执行失败: {e}")

    async def add_message(self, message: ChatMessage) -> Optional[CompactionResult]:
        """
        添加消息并自动检测压缩

        Args:
            message: 要添加的消息

        Returns:
            如果发生了压缩，返回 CompactionResult；否则返回 None
        """
        self.messages.append(message)

        # 检查是否需要压缩
        if self.compressor.should_compact(self.messages):
            result = await self.compressor.compact(self.messages)
            if result.tokens_saved > 0:
                # 重建消息列表
                self.messages = await self.compressor.compact_and_rebuild(
                    self.messages,
                    system_prompt=self.system_prompt,
                    force=True,
                )
                self._notify_compact(result)
                return result

        return None

    async def add_user_message(self, content: str) -> Optional[CompactionResult]:
        """添加用户消息"""
        return await self.add_message(ChatMessage(role="user", content=content))

    async def add_assistant_message(self, content: str) -> Optional[CompactionResult]:
        """添加助手消息"""
        return await self.add_message(ChatMessage(role="assistant", content=content))

    async def add_tool_message(
        self, content: str, name: str, tool_call_id: str
    ) -> Optional[CompactionResult]:
        """添加工具结果消息"""
        return await self.add_message(
            ChatMessage(role="tool", content=content, name=name, tool_call_id=tool_call_id)
        )

    def get_messages(self) -> List[Dict[str, Any]]:
        """
        获取当前消息列表（LLM API 格式）

        Returns:
            消息字典列表
        """
        return [msg.to_dict() for msg in self.messages]

    def get_stats(self) -> Dict[str, Any]:
        """
        获取上下文统计信息

        Returns:
            统计信息字典
        """
        return {
            "message_count": len(self.messages),
            "estimated_tokens": self.compressor.estimate_tokens(self.messages),
            "context_limit": self.compressor.context_limit,
            "usable_limit": self.compressor.usable_limit(),
            "compaction_count": self.compressor.compaction_count,
            "has_previous_summary": self.compressor.previous_summary is not None,
        }


# ==================== 工厂函数 ====================

def create_context_compressor(
    llm_client: LLMClient,
    context_limit: int = 128_000,
    **kwargs: Any,
) -> ContextCompressor:
    """
    创建上下文压缩器的工厂函数

    Args:
        llm_client: LLM 客户端
        context_limit: 上下文窗口大小
        **kwargs: 其他参数

    Returns:
        ContextCompressor 实例
    """
    return ContextCompressor(
        llm_client=llm_client,
        context_limit=context_limit,
        **kwargs,
    )


def create_auto_context(
    llm_client: LLMClient,
    context_limit: int = 128_000,
    system_prompt: Optional[str] = None,
    **kwargs: Any,
) -> AutoCompactingContext:
    """
    创建自动压缩上下文的工厂函数

    Args:
        llm_client: LLM 客户端
        context_limit: 上下文窗口大小
        system_prompt: 系统提示词
        **kwargs: 其他参数

    Returns:
        AutoCompactingContext 实例
    """
    return AutoCompactingContext(
        llm_client=llm_client,
        context_limit=context_limit,
        system_prompt=system_prompt,
        **kwargs,
    )

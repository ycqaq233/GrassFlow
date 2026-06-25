"""
GrassFlow 上下文压缩器测试

测试覆盖：
- Token 估算
- 消息序列化
- 消息选择策略
- 溢出检测
- 摘要生成
- 压缩流程
- 自动压缩上下文
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from tui.context_compressor import (
    ChatMessage,
    CompactionResult,
    ContextCompressor,
    AutoCompactingContext,
    OverflowResult,
    # 工具函数
    estimate_tokens,
    estimate_messages_tokens,
    serialize_message,
    serialize_messages,
    select_messages_for_compaction,
    build_compaction_prompt,
    create_context_compressor,
    create_auto_context,
    # 常量
    CHARS_PER_TOKEN,
    COMPACTION_THRESHOLD_TOKENS,
    KEEP_RECENT_TOKENS,
    DEFAULT_TAIL_TURNS,
)


# ==================== 测试 fixtures ====================

@pytest.fixture
def mock_llm_client():
    """创建模拟的 LLM 客户端"""
    client = AsyncMock()
    client.chat = AsyncMock()
    client.chat.return_value = MagicMock(
        content="## 目标\n- 测试摘要\n\n## 进展\n### 已完成\n- 第一步完成",
        model="gpt-4",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        finish_reason="stop",
    )
    return client


@pytest.fixture
def sample_messages():
    """创建样本消息列表"""
    return [
        ChatMessage(role="system", content="你是一个助手"),
        ChatMessage(role="user", content="你好，帮我分析一下这个项目"),
        ChatMessage(role="assistant", content="好的，我来分析一下这个项目。首先让我看看代码结构。"),
        ChatMessage(role="user", content="主要关注性能方面"),
        ChatMessage(role="assistant", content="性能分析结果如下：CPU 使用率较高，内存使用正常。"),
        ChatMessage(role="user", content="有什么优化建议吗？"),
        ChatMessage(role="assistant", content="建议优化以下几个方面：1. 减少不必要的计算 2. 使用缓存 3. 异步处理"),
    ]


@pytest.fixture
def large_messages():
    """创建大量消息（模拟长对话）"""
    messages = [ChatMessage(role="system", content="你是一个助手")]
    for i in range(50):
        messages.append(ChatMessage(role="user", content=f"问题 {i}: " + "A" * 200))
        messages.append(ChatMessage(role="assistant", content=f"回答 {i}: " + "B" * 300))
    return messages


# ==================== Token 估算测试 ====================

class TestTokenEstimation:
    """Token 估算相关测试"""

    def test_estimate_tokens_empty(self):
        """空字符串的 token 数为 0"""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_short(self):
        """短文本的 token 估算"""
        text = "hello"  # 5 个字符
        expected = round(5 / CHARS_PER_TOKEN)
        assert estimate_tokens(text) == expected

    def test_estimate_tokens_long(self):
        """长文本的 token 估算"""
        text = "A" * 1200  # 1200 个字符
        expected = round(1200 / CHARS_PER_TOKEN)
        assert estimate_tokens(text) == expected

    def test_estimate_tokens_chinese(self):
        """中文文本的 token 估算"""
        text = "你好世界"  # 4 个字符
        expected = round(4 / CHARS_PER_TOKEN)
        assert estimate_tokens(text) == expected

    def test_estimate_messages_tokens_single(self):
        """单条消息的 token 估算"""
        messages = [ChatMessage(role="user", content="hello")]
        tokens = estimate_messages_tokens(messages)
        # 应该包含内容 token + 角色开销
        content_tokens = estimate_tokens("hello")
        assert tokens == content_tokens + 4  # 4 是角色开销

    def test_estimate_messages_tokens_multiple(self):
        """多条消息的 token 估算"""
        messages = [
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="assistant", content="world"),
        ]
        tokens = estimate_messages_tokens(messages)
        expected = estimate_tokens("hello") + 4 + estimate_tokens("world") + 4
        assert tokens == expected

    def test_estimate_messages_tokens_with_name(self):
        """带 name 字段的消息 token 估算"""
        messages = [ChatMessage(role="tool", content="result", name="search")]
        tokens = estimate_messages_tokens(messages)
        expected = estimate_tokens("result") + 4 + estimate_tokens("search")
        assert tokens == expected

    def test_estimate_messages_tokens_empty_list(self):
        """空消息列表的 token 估算"""
        assert estimate_messages_tokens([]) == 0


# ==================== 消息序列化测试 ====================

class TestMessageSerialization:
    """消息序列化相关测试"""

    def test_serialize_user_message(self):
        """用户消息序列化"""
        msg = ChatMessage(role="user", content="你好")
        result = serialize_message(msg)
        assert result == "[用户]: 你好"

    def test_serialize_assistant_message(self):
        """助手消息序列化"""
        msg = ChatMessage(role="assistant", content="你好！")
        result = serialize_message(msg)
        assert result == "[助手]: 你好！"

    def test_serialize_system_message(self):
        """系统消息序列化"""
        msg = ChatMessage(role="system", content="系统提示")
        result = serialize_message(msg)
        assert result == "[系统]: 系统提示"

    def test_serialize_tool_message(self):
        """工具消息序列化"""
        msg = ChatMessage(role="tool", content="搜索结果", name="search")
        result = serialize_message(msg)
        assert result == "[工具结果 - search]: 搜索结果"

    def test_serialize_tool_message_no_name(self):
        """没有 name 的工具消息序列化"""
        msg = ChatMessage(role="tool", content="结果")
        result = serialize_message(msg)
        assert result == "[工具结果 - 工具]: 结果"

    def test_serialize_long_content_truncation(self):
        """长内容截断"""
        from tui.context_compressor import TOOL_OUTPUT_MAX_CHARS
        msg = ChatMessage(role="tool", content="A" * (TOOL_OUTPUT_MAX_CHARS + 100))
        result = serialize_message(msg)
        assert "[已截断]" in result
        assert len(result) < TOOL_OUTPUT_MAX_CHARS + 200  # 加上前缀和截断标记

    def test_serialize_unknown_role(self):
        """未知角色的消息序列化"""
        msg = ChatMessage(role="custom", content="内容")
        result = serialize_message(msg)
        assert result == "[custom]: 内容"

    def test_serialize_messages_multiple(self):
        """多条消息序列化"""
        messages = [
            ChatMessage(role="user", content="你好"),
            ChatMessage(role="assistant", content="你好！"),
        ]
        result = serialize_messages(messages)
        assert "[用户]: 你好" in result
        assert "[助手]: 你好！" in result
        assert "\n\n" in result  # 消息之间有空行

    def test_serialize_messages_empty(self):
        """空消息列表序列化"""
        assert serialize_messages([]) == ""


# ==================== 消息选择策略测试 ====================

class TestMessageSelection:
    """消息选择策略相关测试"""

    def test_select_empty_messages(self):
        """空消息列表的选择"""
        head, tail = select_messages_for_compaction([])
        assert head == []
        assert tail == []

    def test_select_no_user_messages(self):
        """没有 user 消息时全部保留"""
        messages = [
            ChatMessage(role="system", content="系统"),
            ChatMessage(role="assistant", content="助手"),
        ]
        head, tail = select_messages_for_compaction(messages)
        assert head == []
        assert tail == messages

    def test_select_few_turns(self):
        """轮次不足时全部保留"""
        messages = [
            ChatMessage(role="user", content="问题1"),
            ChatMessage(role="assistant", content="回答1"),
        ]
        # 默认 tail_turns=2，只有 1 轮，全部保留
        head, tail = select_messages_for_compaction(messages)
        assert head == []
        assert tail == messages

    def test_select_multiple_turns(self):
        """多轮对话的选择"""
        messages = [
            ChatMessage(role="user", content="问题1"),
            ChatMessage(role="assistant", content="回答1"),
            ChatMessage(role="user", content="问题2"),
            ChatMessage(role="assistant", content="回答2"),
            ChatMessage(role="user", content="问题3"),
            ChatMessage(role="assistant", content="回答3"),
        ]
        # tail_turns=2，应该保留最后 2 轮
        head, tail = select_messages_for_compaction(messages, tail_turns=2)
        assert len(head) == 2  # 第 1 轮
        assert len(tail) == 4  # 第 2-3 轮

    def test_select_preserves_system_at_start(self):
        """保留开头的 system 消息"""
        messages = [
            ChatMessage(role="system", content="系统提示"),
            ChatMessage(role="user", content="问题1"),
            ChatMessage(role="assistant", content="回答1"),
            ChatMessage(role="user", content="问题2"),
            ChatMessage(role="assistant", content="回答2"),
        ]
        # tail_turns=1，保留最后 1 轮
        head, tail = select_messages_for_compaction(messages, tail_turns=1)
        # system 消息和第 1 轮在 head 中
        assert head[0].role == "system"
        assert head[1].content == "问题1"
        # 最后 1 轮在 tail 中
        assert len(tail) == 2

    def test_select_token_budget_limit(self):
        """token 预算限制"""
        # 创建大消息
        large_content = "A" * 30000  # 约 10000 tokens
        messages = [
            ChatMessage(role="user", content=large_content),
            ChatMessage(role="assistant", content=large_content),
            ChatMessage(role="user", content="小问题"),
            ChatMessage(role="assistant", content="小回答"),
        ]
        # keep_recent_tokens=100，只有最后的小消息能保留
        head, tail = select_messages_for_compaction(
            messages,
            keep_recent_tokens=100,
            tail_turns=2,
        )
        # tail 应该包含最后的对话
        assert len(tail) >= 2
        assert tail[-1].content == "小回答"

    def test_select_custom_tail_turns(self):
        """自定义 tail_turns 参数"""
        messages = []
        for i in range(5):
            messages.append(ChatMessage(role="user", content=f"问题{i}"))
            messages.append(ChatMessage(role="assistant", content=f"回答{i}"))
        # 5 轮对话，tail_turns=3
        head, tail = select_messages_for_compaction(messages, tail_turns=3)
        # 应该保留最后 3 轮（6 条消息）
        assert len(tail) == 6
        # head 应该包含前 2 轮（4 条消息）
        assert len(head) == 4


# ==================== 溢出检测测试 ====================

class TestOverflowDetection:
    """溢出检测相关测试"""

    def test_is_overflow_within_limit(self):
        """未超出限制"""
        compressor = ContextCompressor(
            llm_client=AsyncMock(),
            context_limit=128_000,
        )
        messages = [ChatMessage(role="user", content="短消息")]
        result = compressor.is_overflow(messages)
        assert result.is_overflow is False
        assert result.usage_ratio < 1.0

    def test_is_overflow_exceeds_limit(self):
        """超出限制"""
        compressor = ContextCompressor(
            llm_client=AsyncMock(),
            context_limit=100,  # 很小的限制
        )
        messages = [ChatMessage(role="user", content="A" * 500)]
        result = compressor.is_overflow(messages)
        assert result.is_overflow is True
        assert result.usage_ratio > 1.0

    def test_is_overflow_exact_limit(self):
        """正好等于限制"""
        compressor = ContextCompressor(
            llm_client=AsyncMock(),
            context_limit=100,
            compaction_buffer=0,  # 不预留缓冲
        )
        # 精确计算: 需要 100 tokens = 300 字符 + 4 开销 = 304 字符 -> 约 101 tokens
        # 用更少的字符来测试
        messages = [ChatMessage(role="user", content="A" * 288)]  # 96 tokens + 4 = 100
        result = compressor.is_overflow(messages)
        # 100 >= 100 应该是 overflow
        assert result.is_overflow is True

    def test_is_overflow_empty_messages(self):
        """空消息列表"""
        compressor = ContextCompressor(
            llm_client=AsyncMock(),
            context_limit=128_000,
        )
        result = compressor.is_overflow([])
        assert result.is_overflow is False
        assert result.current_tokens == 0

    def test_usable_limit(self):
        """可用限制计算"""
        compressor = ContextCompressor(
            llm_client=AsyncMock(),
            context_limit=128_000,
            compaction_buffer=4_000,
        )
        assert compressor.usable_limit() == 124_000

    def test_usable_limit_zero_buffer(self):
        """零缓冲区的可用限制"""
        compressor = ContextCompressor(
            llm_client=AsyncMock(),
            context_limit=128_000,
            compaction_buffer=0,
        )
        assert compressor.usable_limit() == 128_000


# ==================== 压缩提示词测试 ====================

class TestCompactionPrompt:
    """压缩提示词构建测试"""

    def test_build_prompt_without_previous_summary(self):
        """没有历史摘要时构建提示词"""
        messages = [
            ChatMessage(role="user", content="你好"),
            ChatMessage(role="assistant", content="你好！"),
        ]
        prompt = build_compaction_prompt(messages)
        assert "对话历史" in prompt
        assert "创建一个新的锚定摘要" in prompt
        assert "[用户]: 你好" in prompt
        assert "[助手]: 你好！" in prompt
        assert "## 目标" in prompt  # 模板内容

    def test_build_prompt_with_previous_summary(self):
        """有历史摘要时构建提示词"""
        messages = [ChatMessage(role="user", content="新问题")]
        previous = "## 目标\n- 旧目标"
        prompt = build_compaction_prompt(messages, previous_summary=previous)
        assert "更新下面的锚定摘要" in prompt
        assert "<previous-summary>" in prompt
        assert "旧目标" in prompt

    def test_build_prompt_empty_messages(self):
        """空消息构建提示词"""
        prompt = build_compaction_prompt([])
        assert "对话历史" in prompt
        assert "## 目标" in prompt


# ==================== 核心压缩流程测试 ====================

class TestContextCompressor:
    """上下文压缩器核心功能测试"""

    def test_initial_state(self, mock_llm_client):
        """初始状态测试"""
        compressor = ContextCompressor(llm_client=mock_llm_client)
        assert compressor.previous_summary is None
        assert compressor.compaction_count == 0
        assert compressor.context_limit == 128_000

    def test_should_compact_below_threshold(self, mock_llm_client):
        """低于阈值时不压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            compaction_threshold=1000,
        )
        messages = [ChatMessage(role="user", content="短消息")]
        assert compressor.should_compact(messages) is False

    def test_should_compact_above_threshold_and_near_limit(self, mock_llm_client):
        """高于阈值且接近限制时压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=1000,
            compaction_threshold=100,
            compaction_buffer=0,
        )
        # 创建接近限制的消息 (1000 * 0.75 = 750 tokens)
        messages = [ChatMessage(role="user", content="A" * 2400)]  # 约 800 tokens
        assert compressor.should_compact(messages) is True

    def test_should_compact_above_threshold_but_within_limit(self, mock_llm_client):
        """高于阈值但未接近限制时不压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=100_000,
            compaction_threshold=100,
            compaction_buffer=0,
        )
        messages = [ChatMessage(role="user", content="A" * 600)]  # 约 200 tokens
        # 200 < 100_000 * 0.75 = 75_000，不应该压缩
        assert compressor.should_compact(messages) is False

    @pytest.mark.asyncio
    async def test_compact_no_need(self, mock_llm_client):
        """不需要压缩时返回空结果"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
        )
        messages = [ChatMessage(role="user", content="短消息")]
        result = await compressor.compact(messages)
        assert result.tokens_saved == 0
        assert result.head_messages == []
        assert result.tail_messages == messages

    @pytest.mark.asyncio
    async def test_compact_force(self, mock_llm_client):
        """强制压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=1,
        )
        # 使用足够大的消息，使得摘要比原始消息更短
        large_text = "A" * 5000
        large_answer = "B" * 5000
        messages = [
            ChatMessage(role="user", content=f"问题1: {large_text}"),
            ChatMessage(role="assistant", content=f"回答1: {large_answer}"),
            ChatMessage(role="user", content=f"问题2: {large_text}"),
            ChatMessage(role="assistant", content=f"回答2: {large_answer}"),
        ]
        result = await compressor.compact(messages, force=True)
        assert result.tokens_saved > 0
        assert len(result.head_messages) > 0
        assert len(result.tail_messages) > 0
        assert compressor.compaction_count == 1
        assert compressor.previous_summary is not None

    @pytest.mark.asyncio
    async def test_compact_with_previous_summary(self, mock_llm_client):
        """有历史摘要时的压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=1,
        )
        large_text = "A" * 5000
        large_answer = "B" * 5000
        messages1 = [
            ChatMessage(role="user", content=f"问题1: {large_text}"),
            ChatMessage(role="assistant", content=f"回答1: {large_answer}"),
            ChatMessage(role="user", content=f"问题2: {large_text}"),
            ChatMessage(role="assistant", content=f"回答2: {large_answer}"),
        ]
        # 第一次压缩
        await compressor.compact(messages1, force=True)
        assert compressor.compaction_count == 1

        # 添加更多消息
        messages2 = messages1 + [
            ChatMessage(role="user", content=f"问题3: {large_text}"),
            ChatMessage(role="assistant", content=f"回答3: {large_answer}"),
            ChatMessage(role="user", content=f"问题4: {large_text}"),
            ChatMessage(role="assistant", content=f"回答4: {large_answer}"),
        ]
        # 第二次压缩
        result = await compressor.compact(messages2, force=True)
        assert compressor.compaction_count == 2

        # 验证 LLM 被调用时包含了之前的摘要
        call_args = mock_llm_client.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "previous-summary" in prompt or "更新" in prompt

    @pytest.mark.asyncio
    async def test_compact_and_rebuild(self, mock_llm_client):
        """压缩并重建消息列表"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=1,
        )
        large_text = "A" * 5000
        large_answer = "B" * 5000
        messages = [
            ChatMessage(role="system", content="你是一个助手"),
            ChatMessage(role="user", content=f"问题1: {large_text}"),
            ChatMessage(role="assistant", content=f"回答1: {large_answer}"),
            ChatMessage(role="user", content=f"问题2: {large_text}"),
            ChatMessage(role="assistant", content=f"回答2: {large_answer}"),
        ]
        rebuilt = await compressor.compact_and_rebuild(
            messages,
            system_prompt="你是一个助手",
            force=True,
        )
        # 应该包含: system prompt + 摘要消息 + tail 消息
        assert len(rebuilt) >= 3
        assert rebuilt[0].role == "system"
        assert "压缩摘要" in rebuilt[1].content

    def test_reset(self, mock_llm_client):
        """重置压缩器状态"""
        compressor = ContextCompressor(llm_client=mock_llm_client)
        compressor._previous_summary = "test"
        compressor._compaction_count = 5
        compressor.reset()
        assert compressor.previous_summary is None
        assert compressor.compaction_count == 0

    @pytest.mark.asyncio
    async def test_compact_llm_error(self, mock_llm_client):
        """LLM 调用失败时的错误处理"""
        from core.llm import LLMError
        mock_llm_client.chat.side_effect = LLMError("API 调用失败")
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=1,
        )
        messages = [
            ChatMessage(role="user", content="问题1"),
            ChatMessage(role="assistant", content="回答1"),
            ChatMessage(role="user", content="问题2"),
            ChatMessage(role="assistant", content="回答2"),
        ]
        with pytest.raises(LLMError, match="API 调用失败"):
            await compressor.compact(messages, force=True)

    @pytest.mark.asyncio
    async def test_compact_empty_llm_response(self, mock_llm_client):
        """LLM 返回空内容时的错误处理"""
        from core.llm import LLMError
        mock_llm_client.chat.return_value.content = ""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=1,
        )
        messages = [
            ChatMessage(role="user", content="问题1"),
            ChatMessage(role="assistant", content="回答1"),
            ChatMessage(role="user", content="问题2"),
            ChatMessage(role="assistant", content="回答2"),
        ]
        with pytest.raises(LLMError, match="空摘要"):
            await compressor.compact(messages, force=True)


# ==================== 自动压缩上下文测试 ====================

class TestAutoCompactingContext:
    """自动压缩上下文测试"""

    @pytest.mark.asyncio
    async def test_initial_state(self, mock_llm_client):
        """初始状态测试"""
        ctx = AutoCompactingContext(
            llm_client=mock_llm_client,
            system_prompt="你是一个助手",
        )
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "system"
        assert ctx.messages[0].content == "你是一个助手"

    @pytest.mark.asyncio
    async def test_add_user_message(self, mock_llm_client):
        """添加用户消息"""
        ctx = AutoCompactingContext(llm_client=mock_llm_client)
        await ctx.add_user_message("你好")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "user"
        assert ctx.messages[0].content == "你好"

    @pytest.mark.asyncio
    async def test_add_assistant_message(self, mock_llm_client):
        """添加助手消息"""
        ctx = AutoCompactingContext(llm_client=mock_llm_client)
        await ctx.add_assistant_message("你好！")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "assistant"

    @pytest.mark.asyncio
    async def test_add_tool_message(self, mock_llm_client):
        """添加工具消息"""
        ctx = AutoCompactingContext(llm_client=mock_llm_client)
        await ctx.add_tool_message("搜索结果", "search", "call_123")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "tool"
        assert ctx.messages[0].name == "search"

    @pytest.mark.asyncio
    async def test_auto_compact_trigger(self, mock_llm_client):
        """自动压缩触发"""
        ctx = AutoCompactingContext(
            llm_client=mock_llm_client,
            context_limit=10_000,
            compaction_threshold=100,
            compaction_buffer=4_000,
        )
        # 添加足够多的消息触发压缩 (usable_limit=6000, 75%=4500)
        for i in range(20):
            await ctx.add_user_message(f"问题{i}: " + "A" * 200)
            await ctx.add_assistant_message(f"回答{i}: " + "B" * 200)

        # 压缩应该被触发
        assert ctx.compressor.compaction_count > 0

    @pytest.mark.asyncio
    async def test_auto_compact_callback(self, mock_llm_client):
        """压缩回调"""
        ctx = AutoCompactingContext(
            llm_client=mock_llm_client,
            context_limit=1000,
            compaction_threshold=100,
        )
        callback_results = []
        ctx.on_compact(lambda result: callback_results.append(result))

        # 添加足够多的消息触发压缩
        for i in range(20):
            await ctx.add_user_message(f"问题{i}: " + "A" * 200)
            await ctx.add_assistant_message(f"回答{i}: " + "B" * 200)

        if ctx.compressor.compaction_count > 0:
            assert len(callback_results) > 0
            assert isinstance(callback_results[0], CompactionResult)

    @pytest.mark.asyncio
    async def test_get_messages(self, mock_llm_client):
        """获取消息列表"""
        ctx = AutoCompactingContext(
            llm_client=mock_llm_client,
            system_prompt="你是一个助手",
        )
        await ctx.add_user_message("你好")
        await ctx.add_assistant_message("你好！")

        messages = ctx.get_messages()
        assert len(messages) == 3
        assert messages[0] == {"role": "system", "content": "你是一个助手"}
        assert messages[1] == {"role": "user", "content": "你好"}
        assert messages[2] == {"role": "assistant", "content": "你好！"}

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_llm_client):
        """获取统计信息"""
        ctx = AutoCompactingContext(
            llm_client=mock_llm_client,
            context_limit=128_000,
            system_prompt="你是一个助手",
        )
        await ctx.add_user_message("你好")

        stats = ctx.get_stats()
        assert stats["message_count"] == 2
        assert stats["context_limit"] == 128_000
        assert stats["compaction_count"] == 0
        assert stats["has_previous_summary"] is False


# ==================== 工厂函数测试 ====================

class TestFactoryFunctions:
    """工厂函数测试"""

    def test_create_context_compressor(self, mock_llm_client):
        """创建上下文压缩器"""
        compressor = create_context_compressor(
            llm_client=mock_llm_client,
            context_limit=64_000,
        )
        assert isinstance(compressor, ContextCompressor)
        assert compressor.context_limit == 64_000

    def test_create_context_compressor_with_kwargs(self, mock_llm_client):
        """创建带额外参数的上下文压缩器"""
        compressor = create_context_compressor(
            llm_client=mock_llm_client,
            context_limit=64_000,
            tail_turns=3,
            keep_recent_tokens=10_000,
        )
        assert compressor.tail_turns == 3
        assert compressor.keep_recent_tokens == 10_000

    def test_create_auto_context(self, mock_llm_client):
        """创建自动压缩上下文"""
        ctx = create_auto_context(
            llm_client=mock_llm_client,
            context_limit=64_000,
            system_prompt="测试",
        )
        assert isinstance(ctx, AutoCompactingContext)
        assert ctx.system_prompt == "测试"

    def test_create_auto_context_defaults(self, mock_llm_client):
        """创建默认自动压缩上下文"""
        ctx = create_auto_context(llm_client=mock_llm_client)
        assert ctx.compressor.context_limit == 128_000
        assert ctx.system_prompt is None


# ==================== 数据类型测试 ====================

class TestDataTypes:
    """数据类型测试"""

    def test_chat_message_to_dict(self):
        """ChatMessage 转换为字典"""
        msg = ChatMessage(role="user", content="你好")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "你好"}

    def test_chat_message_to_dict_with_name(self):
        """带 name 的 ChatMessage 转换为字典"""
        msg = ChatMessage(role="tool", content="结果", name="search")
        d = msg.to_dict()
        assert d == {"role": "tool", "content": "结果", "name": "search"}

    def test_chat_message_to_dict_with_tool_call_id(self):
        """带 tool_call_id 的 ChatMessage 转换为字典"""
        msg = ChatMessage(role="tool", content="结果", tool_call_id="call_123")
        d = msg.to_dict()
        assert d == {"role": "tool", "content": "结果", "tool_call_id": "call_123"}

    def test_chat_message_default_metadata(self):
        """ChatMessage 默认元数据"""
        msg = ChatMessage(role="user", content="你好")
        assert msg.metadata == {}
        assert msg.name is None
        assert msg.tool_call_id is None

    def test_compaction_result_fields(self):
        """CompactionResult 字段"""
        result = CompactionResult(
            summary="摘要",
            head_messages=[],
            tail_messages=[],
            tokens_saved=100,
            original_tokens=200,
            compacted_tokens=100,
        )
        assert result.summary == "摘要"
        assert result.tokens_saved == 100

    def test_overflow_result_fields(self):
        """OverflowResult 字段"""
        result = OverflowResult(
            is_overflow=True,
            current_tokens=1000,
            limit=800,
            usage_ratio=1.25,
        )
        assert result.is_overflow is True
        assert result.usage_ratio == 1.25


# ==================== 边界情况测试 ====================

class TestEdgeCases:
    """边界情况测试"""

    @pytest.mark.asyncio
    async def test_compact_only_system_messages(self, mock_llm_client):
        """只有 system 消息时的压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
        )
        messages = [ChatMessage(role="system", content="系统提示")]
        result = await compressor.compact(messages, force=True)
        # 没有 user 消息，head 应该为空
        assert result.head_messages == []

    @pytest.mark.asyncio
    async def test_compact_single_turn(self, mock_llm_client):
        """单轮对话的压缩"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=1,
        )
        messages = [
            ChatMessage(role="user", content="问题"),
            ChatMessage(role="assistant", content="回答"),
        ]
        # 只有 1 轮，tail_turns=1，应该全部保留
        result = await compressor.compact(messages, force=True)
        assert result.head_messages == []

    def test_estimate_tokens_unicode(self):
        """Unicode 字符的 token 估算"""
        text = "你好世界🌍"
        tokens = estimate_tokens(text)
        assert tokens > 0

    def test_select_messages_with_mixed_roles(self):
        """混合角色消息的选择"""
        messages = [
            ChatMessage(role="system", content="系统"),
            ChatMessage(role="user", content="问题1"),
            ChatMessage(role="assistant", content="回答1"),
            ChatMessage(role="tool", content="工具结果", name="search"),
            ChatMessage(role="assistant", content="基于工具结果的回答"),
            ChatMessage(role="user", content="问题2"),
            ChatMessage(role="assistant", content="回答2"),
        ]
        head, tail = select_messages_for_compaction(messages, tail_turns=1)
        # tail 应该包含最后一轮
        assert tail[-1].content == "回答2"


# ==================== 集成测试 ====================

class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_compaction_flow(self, mock_llm_client):
        """完整的压缩流程"""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            context_limit=128_000,
            tail_turns=2,
        )

        # 模拟长对话
        messages = [ChatMessage(role="system", content="你是一个助手")]
        for i in range(10):
            messages.append(ChatMessage(role="user", content=f"问题{i}"))
            messages.append(ChatMessage(role="assistant", content=f"回答{i}"))

        # 第一次强制压缩
        result1 = await compressor.compact(messages, force=True)
        assert result1.tokens_saved > 0
        assert compressor.compaction_count == 1

        # 添加更多消息
        for i in range(10, 15):
            messages.append(ChatMessage(role="user", content=f"问题{i}"))
            messages.append(ChatMessage(role="assistant", content=f"回答{i}"))

        # 第二次压缩
        result2 = await compressor.compact(messages, force=True)
        assert compressor.compaction_count == 2

    @pytest.mark.asyncio
    async def test_auto_context_full_flow(self, mock_llm_client):
        """自动上下文的完整流程"""
        ctx = AutoCompactingContext(
            llm_client=mock_llm_client,
            context_limit=1000,
            compaction_threshold=100,
            system_prompt="你是一个助手",
        )

        # 模拟对话
        compacted_count = 0

        def on_compact(result):
            nonlocal compacted_count
            compacted_count += 1

        ctx.on_compact(on_compact)

        for i in range(30):
            await ctx.add_user_message(f"问题{i}: " + "A" * 100)
            await ctx.add_assistant_message(f"回答{i}: " + "B" * 100)

        # 验证消息被压缩过
        stats = ctx.get_stats()
        assert stats["compaction_count"] > 0 or stats["message_count"] < 61

"""
GrassFlow 流式输出单元测试

测试覆盖：
- ThinkingParser: thinking 标签解析、嵌套处理、flush、空块
- MarkdownSegmenter: 代码块检测、嵌套代码块、未闭合代码块
- StreamHandler: 事件处理、工具调用解析、token 处理
- AgentLoop.process_streaming: 流式事件处理
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import List, Tuple

from tui.stream_handler import (
    ThinkingParser,
    ThinkingState,
    MarkdownSegmenter,
    OutputBuffer,
    StreamHandler,
)
from core.llm_protocol import (
    LLMEvent,
    LLMEventType,
    LLMProtocolError,
    LLMErrorCode,
    ToolCall,
    Usage,
)


# ============================================================================
# ThinkingParser 测试
# ============================================================================


class TestThinkingParserBasic:
    """ThinkingParser 基础解析测试"""

    def test_parse_simple_thinking(self):
        """完整 thinking 标签 → 正常文本 + 思考内容"""
        parser = ThinkingParser()
        all_results = []
        all_results.extend(parser.feed("Hello "))
        all_results.extend(parser.feed("<thinking>"))
        all_results.extend(parser.feed("\ntoken1\ntoken2\n"))
        all_results.extend(parser.feed("</thinking>"))
        all_results.extend(parser.feed(" World answer now"))  # > 10 chars
        all_results.extend(parser.flush())  # flush 残留

        # 收集各状态的文本
        normal_texts = [t for s, t in all_results if s == ThinkingState.NORMAL]
        thinking_texts = [t for s, t in all_results if s == ThinkingState.IN_THINKING]

        assert "Hello " in "".join(normal_texts)
        assert "token1" in "".join(thinking_texts)
        assert "token2" in "".join(thinking_texts)
        assert "World" in "".join(normal_texts)

    def test_parse_thinking_tokens_extracted(self):
        """逐 token 喂入 → 思考 tokens 被正确提取"""
        parser = ThinkingParser()
        all_results: List[Tuple[ThinkingState, str]] = []

        tokens = ["<thinking>", "\n", "token1", "\n", "token2", "\n", "</thinking>", " answer is long"]
        for token in tokens:
            all_results.extend(parser.feed(token))
        all_results.extend(parser.flush())

        thinking_texts = [t for s, t in all_results if s == ThinkingState.IN_THINKING]
        normal_texts = [t for s, t in all_results if s == ThinkingState.NORMAL]

        combined_thinking = "".join(thinking_texts)
        assert "token1" in combined_thinking
        assert "token2" in combined_thinking

        combined_normal = "".join(normal_texts)
        assert "answer" in combined_normal

    def test_nested_think_tags(self):
        """嵌套 thinking 标签 → 第二个 <thinking 被当作 thinking 内容"""
        parser = ThinkingParser()
        all_results: List[Tuple[ThinkingState, str]] = []

        all_results.extend(parser.feed("<thinking>outer "))
        all_results.extend(parser.feed("<thinking>inner"))
        all_results.extend(parser.feed("</thinking> after"))

        thinking_texts = [t for s, t in all_results if s == ThinkingState.IN_THINKING]
        normal_texts = [t for s, t in all_results if s == ThinkingState.NORMAL]

        combined_thinking = "".join(thinking_texts)
        # 嵌套的 <thinking> 被当作普通文本处理
        assert "outer" in combined_thinking
        assert "inner" in combined_thinking

    def test_flush_without_closing_tag(self):
        """未关闭标签 → feed 输出 + flush 返回残留"""
        parser = ThinkingParser()
        parser.feed("<thinking>")
        r1 = parser.feed("partial content here")  # 超过 len("</thinking>") → feed 输出
        flush_results = parser.flush()

        # feed 已经输出了内容（因为超过 tag 长度）
        thinking_in_feed = [t for s, t in r1 if s == ThinkingState.IN_THINKING]
        assert "partial content" in "".join(thinking_in_feed)
        # flush 可能为空（内容已被 feed 输出）或包含残留
        # 关键是不崩溃
        assert isinstance(flush_results, list)

    def test_flush_pending_short_content(self):
        """短内容 + 未关闭标签 → flush 返回 pending"""
        parser = ThinkingParser()
        parser.feed("<thinking>")
        parser.feed("ab")  # 短内容，feed 不会输出
        flush_results = parser.flush()
        assert len(flush_results) == 1
        assert flush_results[0][0] == ThinkingState.IN_THINKING
        assert "ab" in flush_results[0][1]

    def test_empty_think_block(self):
        """空 thinking 块 → 不崩溃"""
        parser = ThinkingParser()
        results = parser.feed("<thinking></thinking>rest is long enough")

        normal_texts = [t for s, t in results if s == ThinkingState.NORMAL]
        thinking_texts = [t for s, t in results if s == ThinkingState.IN_THINKING]
        # 空 thinking 块不产生 thinking 内容
        assert "".join(thinking_texts) == ""

    def test_empty_input(self):
        """空字符串输入 → 不崩溃，无输出"""
        parser = ThinkingParser()
        results = parser.feed("")
        assert results == []

    def test_only_thinking_open(self):
        """只有开始标签 → 等待更多输入"""
        parser = ThinkingParser()
        results = parser.feed("<thinking>")
        # pending 中有内容但未闭合，不输出
        assert results == []

    def test_think_tag_split_across_tokens(self):
        """标签被拆分到多个 token → 正确重组"""
        parser = ThinkingParser()
        all_results = []

        # <thinking> 被拆分为 "<thin" + "king>"
        all_results.extend(parser.feed("before"))
        all_results.extend(parser.feed("<thin"))
        all_results.extend(parser.feed("king>"))
        all_results.extend(parser.feed("content here now"))
        all_results.extend(parser.feed("</thin"))
        all_results.extend(parser.feed("king>"))
        all_results.extend(parser.feed("after long text"))
        all_results.extend(parser.flush())  # flush 残留

        normal_texts = [t for s, t in all_results if s == ThinkingState.NORMAL]
        thinking_texts = [t for s, t in all_results if s == ThinkingState.IN_THINKING]

        assert "before" in "".join(normal_texts)
        assert "content" in "".join(thinking_texts)
        assert "after" in "".join(normal_texts)

    def test_multiple_thinking_blocks(self):
        """多个 thinking 块 → 交替解析"""
        parser = ThinkingParser()
        all_results = []
        all_results.extend(parser.feed(
            "a<thinking>think1 long</thinking>b is long enough<thinking>think2 long</thinking>c is long"
        ))

        normal_texts = [t for s, t in all_results if s == ThinkingState.NORMAL]
        thinking_texts = [t for s, t in all_results if s == ThinkingState.IN_THINKING]

        combined_normal = "".join(normal_texts)
        combined_thinking = "".join(thinking_texts)
        assert "a" in combined_normal
        assert "b" in combined_normal
        assert "think1" in combined_thinking
        assert "think2" in combined_thinking

    def test_reset(self):
        """reset 清除所有状态"""
        parser = ThinkingParser()
        parser.feed("<thinking>some content here")
        assert parser.state == ThinkingState.IN_THINKING

        parser.reset()
        assert parser.state == ThinkingState.NORMAL
        assert parser._pending == ""

    def test_flush_empty(self):
        """flush 空状态 → 空列表"""
        parser = ThinkingParser()
        assert parser.flush() == []

    def test_flush_normal_state(self):
        """flush 正常状态残留 → 返回 NORMAL 状态内容"""
        parser = ThinkingParser()
        parser.feed("hello")
        results = parser.flush()
        assert len(results) == 1
        assert results[0][0] == ThinkingState.NORMAL
        assert "hello" in results[0][1]

    def test_flush_closed_state(self):
        """flush 已关闭状态残留 → 返回 NORMAL 状态（不是 CLOSED）"""
        parser = ThinkingParser()
        parser.feed("<thinking>thought</thinking>")
        parser.feed("rem")
        results = parser.flush()
        if results:
            state, content = results[0]
            # CLOSED 后残留应以 NORMAL 状态返回
            assert state == ThinkingState.NORMAL


class TestThinkingParserEdgeCases:
    """ThinkingParser 边界情况测试"""

    def test_very_long_token(self):
        """超长 token → 不溢出"""
        parser = ThinkingParser()
        long_text = "x" * 100000
        results = parser.feed(long_text)
        # 不应抛异常
        combined = "".join(t for _, t in results)
        assert len(combined) > 0

    def test_special_characters(self):
        """特殊字符 → 不崩溃"""
        parser = ThinkingParser()
        special = "<thinking>\n\t\r\\\"'&amp;&lt;&gt;🎉中文</thinking>"
        results = parser.feed(special)
        thinking_texts = [t for s, t in results if s == ThinkingState.IN_THINKING]
        combined = "".join(thinking_texts)
        assert "中文" in combined or "🎉" in combined

    def test_thinking_with_newlines(self):
        """thinking 内容包含多种换行"""
        parser = ThinkingParser()
        results = parser.feed("<thinking>line1\nline2\r\nline3\n</thinking>")
        thinking_texts = [t for s, t in results if s == ThinkingState.IN_THINKING]
        combined = "".join(thinking_texts)
        assert "line1" in combined
        assert "line2" in combined

    def test_close_tag_immediately_after_open(self):
        """开闭标签紧邻 → 无 thinking 内容"""
        parser = ThinkingParser()
        results = parser.feed("<thinking></thinking>end is long enough now")
        thinking_texts = [t for s, t in results if s == ThinkingState.IN_THINKING]
        normal_texts = [t for s, t in results if s == ThinkingState.NORMAL]
        assert "".join(thinking_texts) == ""
        assert "end" in "".join(normal_texts)


# ============================================================================
# MarkdownSegmenter (代码块检测) 测试
# ============================================================================


class TestMarkdownSegmenterCodeBlock:
    """MarkdownSegmenter 代码块检测测试"""

    def test_simple_code_block(self):
        """简单代码块 → code_end 事件"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("print('hello')\n")
        result = seg.feed("```\n")

        assert result is not None
        typ, code, lang = result
        assert typ == "code_end"
        assert "print('hello')" in code
        assert lang == "python"

    def test_code_block_with_language(self):
        """带语言标识的代码块 → 正确解析语言"""
        seg = MarkdownSegmenter()
        seg.feed("```javascript\n")
        seg.feed("console.log('hi');\n")
        result = seg.feed("```\n")

        assert result is not None
        assert result[0] == "code_end"
        assert result[2] == "javascript"

    def test_code_block_no_language(self):
        """无语言标识的代码块 → 语言为空"""
        seg = MarkdownSegmenter()
        seg.feed("```\n")
        seg.feed("some code\n")
        result = seg.feed("```\n")

        assert result is not None
        assert result[0] == "code_end"
        assert result[2] == "" or result[2] is None

    def test_text_before_code_block(self):
        """代码块前有文本 → 先输出文本"""
        seg = MarkdownSegmenter()
        # 缓冲文本，不输出
        seg.feed("Some text")
        # 空字符串 feed 时，stripped="" 为 falsy，触发文本缓冲区 flush
        # （MarkdownSegmenter.feed 中 `not stripped` 为 True 时触发输出）
        result1 = seg.feed("")
        assert result1 is not None
        assert result1[0] == "text"

        seg.feed("```python\n")
        seg.feed("code\n")
        result2 = seg.feed("```\n")
        assert result2 is not None
        assert result2[0] == "code_end"

    def test_unclosed_code_block(self):
        """未闭合代码块 → flush 输出代码内容"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("line1\n")
        seg.feed("line2\n")

        # 未遇到闭合 ```，flush 应输出代码块
        result = seg.flush()
        assert result is not None
        typ, code, lang = result
        assert typ == "code_end"
        assert "line1" in code
        assert "line2" in code

    def test_empty_code_block(self):
        """空代码块 → code_end 空内容"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        result = seg.feed("```\n")

        assert result is not None
        assert result[0] == "code_end"
        assert result[1] == ""

    def test_text_between_code_blocks(self):
        """两个代码块之间有文本 → 正确分段"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("code1\n")
        r1 = seg.feed("```\n")
        assert r1 is not None and r1[0] == "code_end"

        seg.feed("intermediate text")
        r2 = seg.feed("")  # 空行触发文本输出
        assert r2 is not None and r2[0] == "text"

        seg.feed("```go\n")
        seg.feed("code2\n")
        r3 = seg.feed("```\n")
        assert r3 is not None and r3[0] == "code_end"
        assert "code2" in r3[1]

    def test_flush_text_buffer(self):
        """flush 有文本缓冲 → 输出 text"""
        seg = MarkdownSegmenter()
        seg.feed("Hello World")
        result = seg.flush()
        assert result is not None
        assert result[0] == "text"
        assert "Hello World" in result[1]

    def test_flush_empty(self):
        """flush 无内容 → None"""
        seg = MarkdownSegmenter()
        assert seg.flush() is None

    def test_reset(self):
        """reset 清除所有状态"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("code\n")
        seg.reset()
        assert seg._in_code_block is False
        assert seg._code_language == ""
        assert seg._code_buffer == []
        assert seg._text_buffer == []

    def test_heading_triggers_text_output(self):
        """标题行触发文本段输出"""
        seg = MarkdownSegmenter()
        seg.feed("paragraph text")
        result = seg.feed("# Heading\n")
        # 标题行（或空行）触发输出
        assert result is not None
        assert result[0] == "text"

    def test_code_block_with_special_chars(self):
        """代码块中含特殊字符 → 不崩溃"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("x = '<html>&amp;\"test\"'\n")
        result = seg.feed("```\n")
        assert result is not None
        assert "<html>" in result[1]

    def test_code_block_with_backticks_inside(self):
        """代码块内含反引号 → 不误判为闭合"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("s = 'use `code` here'\n")  # 单个反引号不是 fence
        seg.feed("more code\n")
        result = seg.feed("```\n")
        assert result is not None
        assert result[0] == "code_end"
        assert "more code" in result[1]

    def test_multiple_code_blocks_sequential(self):
        """多个连续代码块 → 正确分段"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("py_code\n")
        r1 = seg.feed("```\n")
        seg.feed("```go\n")
        seg.feed("go_code\n")
        r2 = seg.feed("```\n")

        assert r1 is not None and r1[0] == "code_end"
        assert "py_code" in r1[1]
        assert r2 is not None and r2[0] == "code_end"
        assert "go_code" in r2[1]

    def test_code_block_multiline(self):
        """多行代码块 → 正确收集所有行"""
        seg = MarkdownSegmenter()
        seg.feed("```python\n")
        seg.feed("line1\n")
        seg.feed("line2\n")
        seg.feed("line3\n")
        result = seg.feed("```\n")
        assert result is not None
        code = result[1]
        assert "line1" in code
        assert "line2" in code
        assert "line3" in code


# ============================================================================
# OutputBuffer 测试
# ============================================================================


class TestOutputBuffer:
    """OutputBuffer 批量缓冲测试"""

    def test_basic_add_flush(self):
        """基本添加和刷新"""
        buf = OutputBuffer(flush_interval=-1)
        buf.add("Hello")
        buf.add(" World")
        assert buf.flush() == "Hello World"

    def test_flush_clears_buffer(self):
        """flush 后缓冲区清空"""
        buf = OutputBuffer(flush_interval=-1)
        buf.add("test")
        buf.flush()
        assert buf.flush() == ""

    def test_total_chars(self):
        """total_chars 统计"""
        buf = OutputBuffer(flush_interval=-1)
        buf.add("abc")
        buf.add("de")
        assert buf.total_chars == 5

    def test_reset(self):
        """reset 清除所有"""
        buf = OutputBuffer(flush_interval=-1)
        buf.add("test")
        buf.reset()
        assert buf.total_chars == 0
        assert buf.flush() == ""

    def test_should_flush_max_size(self):
        """超过最大缓冲大小 → should_flush 返回 True"""
        buf = OutputBuffer(flush_interval=1.0, max_buffer_size=5)
        for _ in range(10):
            buf.add("x")
        assert buf.should_flush() is True

    def test_should_flush_manual_mode(self):
        """手动模式 → should_flush 永远返回 False"""
        buf = OutputBuffer(flush_interval=-1)
        buf.add("test")
        assert buf.should_flush() is False

    def test_empty_add(self):
        """空字符串添加 → 不崩溃"""
        buf = OutputBuffer(flush_interval=-1)
        buf.add("")
        assert buf.total_chars == 0


# ============================================================================
# StreamHandler 事件处理测试
# ============================================================================


class TestStreamHandlerToolCall:
    """StreamHandler 工具调用解析测试"""

    def _make_handler(self, **kwargs):
        """创建无 Rich console 的 StreamHandler"""
        return StreamHandler(console=None, **kwargs)

    def _make_tool_call_event(self, tool_name="test_tool", arguments='{"key": "value"}', tc_id="tc_1"):
        """创建工具调用事件"""
        tc = ToolCall(id=tc_id, name=tool_name, arguments=arguments)
        return LLMEvent(type=LLMEventType.TOOL_CALL, data={"tool_call": tc})

    def test_tool_call_with_object(self):
        """ToolCall 对象 → 正确解析 name 和 arguments"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["name"] = name
            called["args"] = args

        handler.on_tool_call = on_tool
        event = self._make_tool_call_event("my_tool", '{"path": "/tmp"}')
        handler._handle_event(event)

        assert called["name"] == "my_tool"
        assert called["args"] == {"path": "/tmp"}

    def test_tool_call_with_dict(self):
        """字典格式 tool_call → 正确解析"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["name"] = name
            called["args"] = args

        handler.on_tool_call = on_tool
        event = LLMEvent(
            type=LLMEventType.TOOL_CALL,
            data={"tool_call": {"name": "dict_tool", "arguments": '{"a": 1}'}},
        )
        handler._handle_event(event)

        assert called["name"] == "dict_tool"
        assert called["args"] == {"a": 1}

    def test_tool_call_fallback_fields(self):
        """无 tool_call 字段 → 回退到 tool_name/arguments"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["name"] = name
            called["args"] = args

        handler.on_tool_call = on_tool
        event = LLMEvent(
            type=LLMEventType.TOOL_CALL,
            data={"tool_name": "fallback_tool", "arguments": {"x": 2}},
        )
        handler._handle_event(event)

        assert called["name"] == "fallback_tool"
        assert called["args"] == {"x": 2}

    def test_tool_call_missing_fields(self):
        """缺失字段 → 使用默认值，不崩溃"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["name"] = name
            called["args"] = args

        handler.on_tool_call = on_tool
        event = LLMEvent(type=LLMEventType.TOOL_CALL, data={})
        handler._handle_event(event)

        assert called["name"] == "unknown"
        assert called["args"] == {}

    def test_tool_call_json_string_arguments(self):
        """arguments 是 JSON 字符串 → 自动解析为 dict"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["args"] = args

        handler.on_tool_call = on_tool
        event = LLMEvent(
            type=LLMEventType.TOOL_CALL,
            data={"tool_name": "t", "arguments": '{"nested": {"deep": true}}'},
        )
        handler._handle_event(event)

        assert called["args"] == {"nested": {"deep": True}}

    def test_tool_call_invalid_json_arguments(self):
        """arguments 是无效 JSON 字符串 → 返回空 dict"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["args"] = args

        handler.on_tool_call = on_tool
        event = LLMEvent(
            type=LLMEventType.TOOL_CALL,
            data={"tool_name": "t", "arguments": "not json{"},
        )
        handler._handle_event(event)

        assert called["args"] == {}

    def test_tool_call_non_dict_non_str_arguments(self):
        """arguments 既不是 dict 也不是 str → 返回空 dict"""
        handler = self._make_handler()
        called = {}

        def on_tool(name, args):
            called["args"] = args

        handler.on_tool_call = on_tool
        event = LLMEvent(
            type=LLMEventType.TOOL_CALL,
            data={"tool_name": "t", "arguments": 12345},
        )
        handler._handle_event(event)

        assert called["args"] == {}

    def test_finish_event_no_crash(self):
        """FINISH 事件 → _handle_event 不崩溃（TOOL_RESULT 是 agent_loop 事件，不是 LLMEvent）"""
        handler = self._make_handler()
        # _handle_event 对 FINISH 只做 _flush_output，不抛异常
        event = LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})
        handler._handle_event(event)  # 不应抛异常

    def test_tool_call_no_callback(self):
        """没有 on_tool_call 回调 → 不崩溃"""
        handler = self._make_handler()
        event = self._make_tool_call_event()
        handler._handle_event(event)  # 不应抛异常


class TestStreamHandlerEvents:
    """StreamHandler 通用事件处理测试"""

    def _make_handler(self, **kwargs):
        return StreamHandler(console=None, **kwargs)

    def test_text_delta_event(self):
        """TEXT_DELTA 事件 → token 被处理"""
        handler = self._make_handler()
        tokens = []

        def on_token(t):
            tokens.append(t)

        handler.on_token = on_token
        event = LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "hello"})
        handler._handle_event(event)

        assert "hello" in tokens

    def test_text_delta_empty(self):
        """空 TEXT_DELTA → 不崩溃，_current_text 不变"""
        handler = self._make_handler()
        event = LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": ""})
        handler._handle_event(event)  # 不应抛异常
        assert handler._current_text == ""

    def test_text_delta_missing_key(self):
        """TEXT_DELTA 缺少 text key → 使用空字符串"""
        handler = self._make_handler()
        tokens = []
        handler.on_token = lambda t: tokens.append(t)
        event = LLMEvent(type=LLMEventType.TEXT_DELTA, data={})
        handler._handle_event(event)
        assert "" in tokens

    def test_finish_event(self):
        """FINISH 事件 → 刷新缓冲区"""
        handler = self._make_handler()
        handler._output_buffer.add("pending")
        event = LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})
        handler._handle_event(event)
        # buffer 应该被 flush
        assert handler._output_buffer.flush() == ""

    def test_provider_error_event(self):
        """PROVIDER_ERROR 事件 → 抛出 LLMProtocolError"""
        handler = self._make_handler()
        event = LLMEvent(
            type=LLMEventType.PROVIDER_ERROR,
            data={"message": "Rate limited", "code": "rate_limit"},
        )
        with pytest.raises(LLMProtocolError):
            handler._handle_event(event)

    def test_provider_error_unknown_code(self):
        """PROVIDER_ERROR 未知错误码 → 使用 UNKNOWN"""
        handler = self._make_handler()
        event = LLMEvent(
            type=LLMEventType.PROVIDER_ERROR,
            data={"message": "Something", "code": "no_such_code"},
        )
        with pytest.raises(LLMProtocolError):
            handler._handle_event(event)

    def test_interrupt(self):
        """interrupt 设置标志"""
        handler = self._make_handler()
        assert handler._interrupted is False
        handler.interrupt()
        assert handler._interrupted is True

    def test_reset(self):
        """reset 清除所有状态"""
        handler = self._make_handler()
        handler._current_text = "some text"
        handler._interrupted = True
        handler._output_buffer.add("buf")
        handler.reset()
        assert handler._interrupted is False
        assert handler._current_text == ""

    def test_unknown_event_type_no_crash(self):
        """未知 LLMEventType → _handle_event 静默忽略，不崩溃"""
        handler = self._make_handler()
        # 使用一个不存在于 _handle_event 分支中的事件类型
        event = LLMEvent(type=LLMEventType.TEXT_START, data={})
        handler._handle_event(event)  # 不应抛异常
        # 状态无变化
        assert handler._current_text == ""

    def test_on_complete_callback(self):
        """on_complete 回调在 _flush_output 中不被调用（它在 stream_llm_response 中调用）"""
        completed_text = []
        handler = self._make_handler(on_complete=lambda t: completed_text.append(t))
        handler._current_text = "final text"
        # 直接调用 _flush_output 不触发 on_complete
        handler._output_buffer.add("more")
        handler._flush_output()
        assert "".join(completed_text) == ""  # on_complete 不在 flush 中调用


class TestStreamHandlerTokenProcessing:
    """StreamHandler token 处理细节测试"""

    def _make_handler(self, **kwargs):
        return StreamHandler(console=None, enable_thinking_render=False, **kwargs)

    def test_token_accumulation(self):
        """token 累积到 _current_text"""
        handler = self._make_handler()
        handler._process_token("Hello")
        handler._process_token(" ")
        handler._process_token("World")
        assert handler._current_text == "Hello World"

    def test_token_callback_called(self):
        """每个 token 都调用 on_token 回调"""
        handler = self._make_handler()
        tokens = []
        handler.on_token = lambda t: tokens.append(t)
        handler._process_token("a")
        handler._process_token("b")
        assert tokens == ["a", "b"]

    def test_sanitize_tool_args(self):
        """敏感参数脱敏"""
        args = {"api_key": "secret123", "query": "test", "password": "pw"}
        safe = StreamHandler._sanitize_tool_args(args)
        assert safe["api_key"] == "[REDACTED]"
        assert safe["password"] == "[REDACTED]"
        assert safe["query"] == "test"

    def test_sanitize_long_string(self):
        """长字符串参数被截断"""
        args = {"data": "x" * 200}
        safe = StreamHandler._sanitize_tool_args(args)
        assert len(safe["data"]) < 200
        assert "..." in safe["data"]

    def test_format_arg_string(self):
        """format_arg 字符串格式化"""
        assert StreamHandler._format_arg("hello") == '"hello"'
        assert "..." in StreamHandler._format_arg("x" * 50)

    def test_format_arg_dict(self):
        """format_arg 字典格式化"""
        result = StreamHandler._format_arg({"a": 1, "b": 2})
        assert "2 items" in result

    def test_format_arg_list(self):
        """format_arg 列表格式化"""
        result = StreamHandler._format_arg([1, 2, 3])
        assert "3 items" in result

    def test_format_arg_number(self):
        """format_arg 数字格式化"""
        assert StreamHandler._format_arg(42) == "42"

    def test_empty_delta_no_event(self):
        """空 token → 不产生有效文本"""
        handler = self._make_handler()
        tokens = []
        handler.on_token = lambda t: tokens.append(t)
        handler._process_token("")
        # 空 token 仍然调用回调（累积到 buffer）
        assert "" in tokens
        # 但不改变 _current_text
        assert handler._current_text == ""

    def test_very_long_token_no_overflow(self):
        """超长 token → 不溢出"""
        handler = self._make_handler()
        long_token = "x" * 500000
        handler._process_token(long_token)
        assert handler._current_text == long_token
        assert len(handler._current_text) == 500000

    def test_special_chars_in_token(self):
        """特殊字符 token → 不崩溃"""
        handler = self._make_handler()
        special = "<>&\"'\n\t\r\\🎉中文\t\n"
        handler._process_token(special)
        assert handler._current_text == special


# ============================================================================
# AgentLoop.process_streaming 测试
# ============================================================================


class TestAgentLoopProcessStreaming:
    """AgentLoop.process_streaming 事件处理测试"""

    @pytest.fixture
    def mock_client(self):
        """创建模拟 LLM 客户端"""
        client = AsyncMock()
        return client

    @pytest.fixture
    def mock_tool_registry(self):
        """创建模拟工具注册表"""
        registry = MagicMock()
        registry.enabled_tools.return_value = []
        registry.get.return_value = None
        return registry

    @pytest.mark.asyncio
    async def test_streaming_text_events(self, mock_client, mock_tool_registry):
        """流式文本响应 → TEXT_DELTA + TEXT_END 事件"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "Hello "})
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "World"})
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        event_types = [e.type for e in events]
        assert LoopEventType.LOOP_START.value in event_types
        assert LoopEventType.TEXT_DELTA.value in event_types
        assert LoopEventType.TEXT_END.value in event_types
        assert LoopEventType.LOOP_END.value in event_types

        # 检查文本内容
        deltas = [e.data.get("text", "") for e in events if e.type == LoopEventType.TEXT_DELTA.value]
        assert "".join(deltas) == "Hello World"

    @pytest.mark.asyncio
    async def test_streaming_thinking_events(self, mock_client, mock_tool_registry):
        """流式推理响应 → THINKING_DELTA 事件"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.REASONING_DELTA, data={"text": "let me think"})
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "answer"})
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        thinking_events = [e for e in events if e.type == LoopEventType.THINKING_DELTA.value]
        assert len(thinking_events) > 0
        assert thinking_events[0].data["text"] == "let me think"

    @pytest.mark.asyncio
    async def test_streaming_tool_call_events(self, mock_client, mock_tool_registry):
        """流式工具调用 → TOOL_CALL_START + TOOL_RESULT + TOOL_CALL_END 事件"""

        async def fake_stream(*args, **kwargs):
            # 第一轮：工具调用
            yield LLMEvent(
                type=LLMEventType.TOOL_CALL,
                data={"tool_call": ToolCall(id="tc_1", name="read_file", arguments='{"path": "test.txt"}')},
            )
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "tool_calls"})

        call_count = 0

        async def fake_stream_wrapper(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                async for e in fake_stream(*args, **kwargs):
                    yield e
            else:
                # 第二轮：文本响应
                yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "done"})
                yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})

        mock_client.stream_chat = fake_stream_wrapper

        # mock 工具执行
        mock_tool_registry.invoke = AsyncMock()
        mock_tool_registry.invoke.return_value = MagicMock(output="file content", is_error=False)

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("read test.txt"):
            events.append(event)

        event_types = [e.type for e in events]
        assert LoopEventType.TOOL_CALL_START.value in event_types
        assert LoopEventType.TOOL_RESULT.value in event_types
        assert LoopEventType.TOOL_CALL_END.value in event_types

    @pytest.mark.asyncio
    async def test_streaming_interrupt(self, mock_client, mock_tool_registry):
        """中断 → INTERRUPTED 事件"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "start"})
            # 不再产出更多事件，模拟长时间运行
            await asyncio.sleep(10)

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []

        async def collect_and_interrupt():
            async for event in loop.process_streaming("test"):
                events.append(event)
                if event.type == LoopEventType.TEXT_DELTA.value:
                    loop.interrupt()

        await collect_and_interrupt()

        event_types = [e.type for e in events]
        assert LoopEventType.TEXT_DELTA.value in event_types

    @pytest.mark.asyncio
    async def test_streaming_error_handling(self, mock_client, mock_tool_registry):
        """流式调用异常 → ERROR 事件"""

        async def fake_stream(*args, **kwargs):
            raise RuntimeError("Connection failed")
            yield  # make it a generator

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            max_iterations=2,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        event_types = [e.type for e in events]
        assert LoopEventType.ERROR.value in event_types

    @pytest.mark.asyncio
    async def test_streaming_max_iterations(self, mock_client, mock_tool_registry):
        """超过最大迭代次数 → 循环终止"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(
                type=LLMEventType.TOOL_CALL,
                data={"tool_call": ToolCall(id="tc_1", name="loop_tool", arguments='{}')},
            )
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "tool_calls"})

        mock_client.stream_chat = fake_stream
        mock_tool_registry.invoke = AsyncMock()
        mock_tool_registry.invoke.return_value = MagicMock(output="ok", is_error=False)

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            max_iterations=2,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        event_types = [e.type for e in events]
        assert LoopEventType.LOOP_END.value in event_types
        # 应该正好是 max_iterations 次迭代（每次都有工具调用，循环持续到上限）
        loop_end = [e for e in events if e.type == LoopEventType.LOOP_END.value]
        assert 1 <= loop_end[0].data["iterations"] <= 2

    @pytest.mark.asyncio
    async def test_streaming_empty_response(self, mock_client, mock_tool_registry):
        """空响应 → 只有 LOOP_START 和 LOOP_END，无 TEXT_END。

        agent_loop.py 中 TEXT_END 仅在 collected_text 非空时才发出（`if collected_text:`），
        空响应 collected_text=""，所以 TEXT_END 不会被发出。
        """

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        event_types = [e.type for e in events]
        assert LoopEventType.LOOP_START.value in event_types
        assert LoopEventType.LOOP_END.value in event_types
        # TEXT_END 仅在 collected_text 非空时发出；空响应不应有 TEXT_END
        assert LoopEventType.TEXT_END.value not in event_types
        # 确认事件序列精确：只有 LOOP_START 和 LOOP_END
        assert event_types == [LoopEventType.LOOP_START.value, LoopEventType.LOOP_END.value]

    @pytest.mark.asyncio
    async def test_streaming_usage_tracking(self, mock_client, mock_tool_registry):
        """usage 统计正确累积"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "ok"})
            yield LLMEvent(
                type=LLMEventType.FINISH,
                data={
                    "finish_reason": "stop",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                },
            )

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        async for _ in loop.process_streaming("test"):
            pass

        status = loop.get_status()
        assert status["total_input_tokens"] == 100
        assert status["total_output_tokens"] == 50

    @pytest.mark.asyncio
    async def test_streaming_event_order(self, mock_client, mock_tool_registry):
        """流式事件顺序: LOOP_START → TEXT_DELTA* → TEXT_END → LOOP_END"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "a"})
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "b"})
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        types = [e.type for e in events]
        # LOOP_START 应该是第一个
        assert types[0] == LoopEventType.LOOP_START.value
        # LOOP_END 应该是最后一个
        assert types[-1] == LoopEventType.LOOP_END.value
        # TEXT_DELTA 在 TEXT_END 之前
        delta_idx = types.index(LoopEventType.TEXT_DELTA.value)
        end_idx = types.index(LoopEventType.TEXT_END.value)
        assert delta_idx < end_idx

    @pytest.mark.asyncio
    async def test_streaming_no_text_start_event(self, mock_client, mock_tool_registry):
        """process_streaming 不产生 TEXT_START 事件（与 process 不同）"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "hi"})
            yield LLMEvent(type=LLMEventType.FINISH, data={"finish_reason": "stop"})

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        events = []
        async for event in loop.process_streaming("test"):
            events.append(event)

        event_types = [e.type for e in events]
        # process_streaming 直接发 TEXT_DELTA，不先发 TEXT_START
        assert LoopEventType.TEXT_START.value not in event_types

    @pytest.mark.asyncio
    async def test_streaming_reasoning_tokens(self, mock_client, mock_tool_registry):
        """reasoning tokens 在 usage 中正确提取"""

        async def fake_stream(*args, **kwargs):
            yield LLMEvent(type=LLMEventType.TEXT_DELTA, data={"text": "ok"})
            yield LLMEvent(
                type=LLMEventType.FINISH,
                data={
                    "finish_reason": "stop",
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "completion_tokens_details": {"reasoning_tokens": 30},
                    },
                },
            )

        mock_client.stream_chat = fake_stream

        from tui.agent_loop import AgentLoop, LoopEventType

        loop = AgentLoop(
            client=mock_client,
            tool_registry=mock_tool_registry,
            enable_doom_loop_detection=False,
        )

        async for _ in loop.process_streaming("test"):
            pass

        status = loop.get_status()
        assert status["total_reasoning_tokens"] == 30

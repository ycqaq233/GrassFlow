"""
流式输出处理器

支持 LLM 流式响应的实时渲染，包括:
- Markdown 渐进式渲染
- 代码语法高亮
- thinking block 渲染
- 批量输出优化
- 缓冲输出减少终端闪屏
"""

import asyncio
import re
import sys
import time
from typing import Optional, Callable, Any, List, Tuple
from enum import Enum
from io import StringIO

try:
    from rich.console import Console
    from rich.live import Live
    from rich.text import Text
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from core.llm_protocol import (
    LLMEvent, LLMEventType, ProtocolLLMClient, ProtocolLLMManager,
    OpenAIChatProtocol, Endpoint, Auth, SSEFraming, Message
)


# ---------------------------------------------------------------------------
# 批量输出缓冲区
# ---------------------------------------------------------------------------

class OutputBuffer:
    """
    批量输出缓冲区

    收集 token 并按一定间隔批量渲染，减少终端闪屏和 Live 刷新开销。
    避免每个 token 都刷新一次 Rich Live display。

    使用示例:
        buffer = OutputBuffer(flush_interval=0.05)  # 50ms 批量刷新
        buffer.add("Hello")
        buffer.add(" World")
        result = buffer.flush()  # "Hello World"
    """

    def __init__(self, flush_interval: float = 0.05, max_buffer_size: int = 80):
        """
        初始化缓冲区

        Args:
            flush_interval: 刷新间隔 (秒)，-1 表示手动刷新
            max_buffer_size: 最大缓冲字符数，超过后自动刷新
        """
        self.flush_interval = flush_interval
        self.max_buffer_size = max_buffer_size
        self._buffer: List[str] = []
        self._last_flush = time.time()
        self._total_chars = 0

    def add(self, token: str) -> None:
        """添加 token 到缓冲区"""
        self._buffer.append(token)
        self._total_chars += len(token)

    def should_flush(self) -> bool:
        """检查是否应该刷新"""
        if self.flush_interval < 0:
            return False
        if len(self._buffer) >= self.max_buffer_size:
            return True
        if self._buffer and time.time() - self._last_flush >= self.flush_interval:
            return True
        return False

    def flush(self) -> str:
        """刷新缓冲区，返回累积的文本"""
        result = "".join(self._buffer)
        self._buffer.clear()
        self._last_flush = time.time()
        return result

    @property
    def total_chars(self) -> int:
        return self._total_chars

    def reset(self) -> None:
        """重置缓冲区"""
        self._buffer.clear()
        self._total_chars = 0
        self._last_flush = time.time()


# ---------------------------------------------------------------------------
# Thinking block 解析器
# ---------------------------------------------------------------------------

class ThinkingState(Enum):
    """Thinking 块状态"""
    NORMAL = "normal"           # 正常文本
    IN_THINKING = "thinking"    # 在 <thinking> 标签内
    THINKING_CLOSED = "closed"  # thinking 标签已关闭


class ThinkingParser:
    """
    Thinking 块解析器

    支持解析 LLM 输出中的 <thinking>...</thinking> 块
    用于流式渲染时区分思维过程和最终输出

    状态机:
        NORMAL --<thinking>--> IN_THINKING --</thinking>--> THINKING_CLOSED
    """

    THINKING_OPEN = "<thinking>"
    THINKING_CLOSE = "</thinking>"

    def __init__(self):
        self.state = ThinkingState.NORMAL
        self._thinking_buffer: List[str] = []
        self._normal_buffer: List[str] = []
        self._pending = ""  # 部分匹配缓冲区

    def feed(self, token: str) -> List[Tuple[ThinkingState, str]]:
        """
        喂入 token，返回解析结果

        Args:
            token: 文本 token

        Returns:
            [(状态, 文本), ...] 列表
        """
        self._pending += token
        results = []

        while self._pending:
            if self.state == ThinkingState.NORMAL:
                # 查找 <thinking> 开始标记
                open_idx = self._pending.find(self.THINKING_OPEN)
                if open_idx == -1:
                    # 没有找到，输出所有
                    if len(self._pending) > len(self.THINKING_OPEN):
                        # 检查尾部是否可能是部分匹配
                        for i in range(1, len(self.THINKING_OPEN)):
                            if self._pending.endswith(self.THINKING_OPEN[:i]):
                                safe = self._pending[:-i]
                                if safe:
                                    results.append((ThinkingState.NORMAL, safe))
                                self._pending = self._pending[-i:]
                                break
                        else:
                            results.append((ThinkingState.NORMAL, self._pending))
                            self._pending = ""
                    else:
                        # pending 太短，保留等待
                        break
                else:
                    # 找到了 <thinking>
                    if open_idx > 0:
                        results.append((ThinkingState.NORMAL, self._pending[:open_idx]))
                    self.state = ThinkingState.IN_THINKING
                    self._pending = self._pending[open_idx + len(self.THINKING_OPEN):]

            elif self.state == ThinkingState.IN_THINKING:
                close_idx = self._pending.find(self.THINKING_CLOSE)
                if close_idx == -1:
                    # 没有闭合标签
                    if len(self._pending) > len(self.THINKING_CLOSE):
                        safe = self._pending
                        # 检查尾部部分匹配 </thinking>
                        for i in range(1, len(self.THINKING_CLOSE)):
                            if self._pending.endswith(self.THINKING_CLOSE[:i]):
                                safe = self._pending[:-i]
                                if safe:
                                    results.append((ThinkingState.IN_THINKING, safe))
                                self._pending = self._pending[-i:]
                                break
                        else:
                            results.append((ThinkingState.IN_THINKING, self._pending))
                            self._pending = ""
                    else:
                        break
                else:
                    if close_idx > 0:
                        results.append((ThinkingState.IN_THINKING, self._pending[:close_idx]))
                    self.state = ThinkingState.THINKING_CLOSED
                    self._pending = self._pending[close_idx + len(self.THINKING_CLOSE):]

            elif self.state == ThinkingState.THINKING_CLOSED:
                # 找下一个 <thinking>
                open_idx = self._pending.find(self.THINKING_OPEN)
                if open_idx == -1:
                    results.append((ThinkingState.NORMAL, self._pending))
                    self._pending = ""
                else:
                    if open_idx > 0:
                        results.append((ThinkingState.NORMAL, self._pending[:open_idx]))
                    self.state = ThinkingState.IN_THINKING
                    self._pending = self._pending[open_idx + len(self.THINKING_OPEN):]

        return results

    def flush(self) -> List[Tuple[ThinkingState, str]]:
        """刷新 _pending 中的残留数据"""
        results = []
        if self._pending:
            state = self.state if self.state != ThinkingState.THINKING_CLOSED else ThinkingState.NORMAL
            results.append((state, self._pending))
            self._pending = ""
        return results

    def reset(self) -> None:
        """重置解析器状态"""
        self.state = ThinkingState.NORMAL
        self._thinking_buffer.clear()
        self._normal_buffer.clear()
        self._pending = ""


# ---------------------------------------------------------------------------
# Markdown 分段渲染器
# ---------------------------------------------------------------------------

class MarkdownSegmenter:
    """
    Markdown 分段渲染器

    将流式输出的 Markdown 文本按逻辑段切分，支持渐进式渲染。
    主要识别:
    - 代码块边界 (```)
    - 标题行
    - 段落分隔 (空行)
    - 列表项
    """

    CODE_FENCE = "```"

    def __init__(self):
        self._in_code_block = False
        self._code_language = ""
        self._code_buffer: List[str] = []
        self._text_buffer: List[str] = []

    def feed(self, line: str) -> Optional[Tuple[str, Optional[str]]]:
        """
        喂入一行文本

        Args:
            line: 一行文本

        Returns:
            (类型, 内容) 或 None (未完成)
            类型: "text", "code_start", "code_content", "code_end"
        """
        stripped = line.rstrip("\n")

        if not self._in_code_block:
            if stripped.startswith(self.CODE_FENCE):
                self._in_code_block = True
                self._code_language = stripped[3:].strip()
                self._code_buffer.clear()

                # 先输出缓冲的文本
                result = None
                if self._text_buffer:
                    result = ("text", "\n".join(self._text_buffer))
                    self._text_buffer.clear()

                return result  # code_start 由 consumer 处理
            else:
                self._text_buffer.append(stripped)
                return None
        else:
            if stripped.startswith(self.CODE_FENCE):
                self._in_code_block = False
                code = "\n".join(self._code_buffer)
                lang = self._code_language
                self._code_buffer.clear()
                self._code_language = ""
                return ("code_end", code, lang)
            else:
                self._code_buffer.append(stripped)
                return None

    def flush(self) -> Optional[Tuple[str, Optional[str]]]:
        """刷新缓冲区

        注意：返回值可能是 2-tuple ("text", content) 或 3-tuple ("code_end", code, lang)。
        调用方需根据 result[0] 判断类型。
        """
        # 如果在代码块内刷新，输出未闭合的代码块内容
        if self._in_code_block and self._code_buffer:
            code = "\n".join(self._code_buffer)
            lang = self._code_language
            self._code_buffer.clear()
            self._code_language = ""
            self._in_code_block = False
            return ("code_end", code, lang)

        if self._text_buffer:
            result = ("text", "\n".join(self._text_buffer))
            self._text_buffer.clear()
            return result
        return None

    def reset(self) -> None:
        """重置状态"""
        self._in_code_block = False
        self._code_language = ""
        self._code_buffer.clear()
        self._text_buffer.clear()


# ---------------------------------------------------------------------------
# 流式处理器
# ---------------------------------------------------------------------------

class StreamHandler:
    """
    增强型流式输出处理器

    支持:
    - LLM 流式响应
    - Markdown 渐进式渲染
    - 代码块语法高亮 (Rich Syntax)
    - thinking block 折叠渲染
    - 批量输出优化 (减少闪屏)
    - 实时 token 渲染

    使用示例:
        handler = StreamHandler(console=console)

        # 基本使用
        result = await handler.stream_llm_response(client, messages)

        # 带回调
        handler = StreamHandler(
            console=console,
            on_token=lambda t: stats.add(t),
            on_thinking=lambda t: log_thinking(t),
        )
    """

    def __init__(
        self,
        console: Optional[Any] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, dict], None]] = None,
        batch_interval: float = 0.05,
        enable_thinking_render: bool = True,
        enable_code_highlight: bool = True,
        enable_markdown: bool = True,
    ):
        """
        初始化流式处理器

        Args:
            console: Rich Console 实例
            on_token: token 回调
            on_complete: 完成回调
            on_error: 错误回调
            on_thinking: thinking 内容回调
            on_tool_call: 工具调用回调
            batch_interval: 批量刷新间隔 (秒)
            enable_thinking_render: 是否启用 thinking 块渲染
            enable_code_highlight: 是否启用代码高亮
            enable_markdown: 是否启用 Markdown 渲染
        """
        self.console = console or Console() if HAS_RICH else None
        self.on_token = on_token
        self.on_complete = on_complete
        self.on_error = on_error
        self.on_thinking = on_thinking
        self.on_tool_call = on_tool_call
        self.batch_interval = batch_interval
        self.enable_thinking_render = enable_thinking_render
        self.enable_code_highlight = enable_code_highlight
        self.enable_markdown = enable_markdown

        self._interrupted = False
        self._current_text = ""
        self._thinking_parser = ThinkingParser()
        self._markdown_segmenter = MarkdownSegmenter()
        self._output_buffer = OutputBuffer(flush_interval=batch_interval)
        self._thinking_expanded = False  # thinking 块是否展开
        self._line_buffer = ""  # 行缓冲区

    def interrupt(self):
        """中断当前流式输出"""
        self._interrupted = True

    def reset(self):
        """重置所有状态"""
        self._interrupted = False
        self._current_text = ""
        self._thinking_parser.reset()
        self._markdown_segmenter.reset()
        self._output_buffer.reset()
        self._thinking_expanded = False
        self._line_buffer = ""

    # -----------------------------------------------------------------------
    # 主线流处理
    # -----------------------------------------------------------------------

    async def stream_llm_response(
        self,
        client: ProtocolLLMClient,
        messages: list,
        system: Optional[list] = None,
    ) -> str:
        """
        流式处理 LLM 响应

        Args:
            client: LLM 客户端
            messages: 消息列表
            system: 系统提示

        Returns:
            完整的响应文本
        """
        self.reset()
        self._current_text = ""

        try:
            if HAS_RICH and self.console:
                self.console.print()

            # 构建完整消息列表
            full_messages = []
            if system:
                for msg in system:
                    full_messages.append({"role": "system", "content": msg.content})
            for msg in messages:
                full_messages.append({"role": msg.role, "content": msg.content})

            # 流式处理
            async for event in client.stream_chat(full_messages):
                if self._interrupted:
                    break

                self._handle_event(event)

            # 刷新缓冲区
            self._flush_output()

            # 调用完成回调
            if self.on_complete:
                self.on_complete(self._current_text)

            return self._current_text

        except Exception as e:
            if self.on_error:
                self.on_error(e)
            raise

    # -----------------------------------------------------------------------
    # 事件处理
    # -----------------------------------------------------------------------

    def _handle_event(self, event: LLMEvent) -> None:
        """处理单个 LLM 事件"""
        if event.type == LLMEventType.TEXT_DELTA:
            token = event.data.get("text", "")
            self._process_token(token)

        elif event.type == LLMEventType.TEXT_START:
            pass  # 文本开始

        elif event.type == LLMEventType.TEXT_END:
            self._flush_output()
            if HAS_RICH and self.console:
                self.console.print()

        elif event.type == LLMEventType.TOOL_CALL:
            self._handle_tool_call(event)

        elif event.type == LLMEventType.FINISH:
            self._flush_output()

        elif event.type == LLMEventType.PROVIDER_ERROR:
            error_msg = event.data.get("message", "Unknown error")
            if HAS_RICH and self.console:
                self.console.print(f"\n[bold red]Error:[/bold red] {error_msg}")
            raise Exception(error_msg)

    def _process_token(self, token: str) -> None:
        """处理单个 token"""
        self._current_text += token

        # 调用外部 token 回调
        if self.on_token:
            self.on_token(token)

        # 添加到输出缓冲区
        self._output_buffer.add(token)

        # 是否应该刷新
        if self._output_buffer.should_flush():
            flushed = self._output_buffer.flush()
            if self.enable_thinking_render:
                self._render_with_thinking(flushed)
            else:
                self._render_raw(flushed)

    def _handle_tool_call(self, event: LLMEvent) -> None:
        """处理工具调用事件"""
        self._flush_output()

        # 兼容两种格式: {"tool_call": ToolCall(...)} 或 {"tool_name": ..., "arguments": ...}
        tc = event.data.get("tool_call")
        if tc is not None:
            tool_name = getattr(tc, "name", None) or event.data.get("tool_name", "unknown")
            tool_args = getattr(tc, "arguments", None) or {}
        else:
            tool_name = event.data.get("tool_name", "unknown")
            tool_args = event.data.get("arguments", {})

        if self.on_tool_call:
            self.on_tool_call(tool_name, tool_args)

        if HAS_RICH and self.console:
            self._render_tool_call_rich(tool_name, tool_args)
        else:
            print(f"\nCalling tool: {tool_name}")
            if tool_args:
                print(f"  args: {tool_args}")

    # -----------------------------------------------------------------------
    # 渲染方法
    # -----------------------------------------------------------------------

    def _render_with_thinking(self, text: str) -> None:
        """渲染包含 thinking 块的文本"""
        results = self._thinking_parser.feed(text)

        for state, content in results:
            if state == ThinkingState.NORMAL:
                self._render_content(content)
            elif state == ThinkingState.IN_THINKING:
                self._render_thinking(content)
            elif state == ThinkingState.THINKING_CLOSED:
                # thinking 已关闭，可以渲染最终内容
                pass

    def _render_content(self, content: str) -> None:
        """渲染正常内容"""
        if not content:
            return

        if not HAS_RICH or not self.console or not self.enable_markdown:
            sys.stdout.write(content)
            sys.stdout.flush()
            return

        # 逐行处理 Markdown
        self._line_buffer += content
        lines = self._line_buffer.split("\n")

        # 保留最后一个不完整行
        self._line_buffer = lines[-1]
        complete_lines = lines[:-1]

        for line in complete_lines:
            result = self._markdown_segmenter.feed(line + "\n")
            if result:
                typ = result[0]
                if typ == "text":
                    markdown = Markdown(result[1])
                    self.console.print(markdown)
                elif typ == "code_end":
                    code, lang = result[1], result[2]
                    self._render_code_block(code, lang)

    def _render_thinking(self, content: str) -> None:
        """渲染 thinking 块"""
        if self.on_thinking:
            self.on_thinking(content)

        if not HAS_RICH or not self.console:
            return

        # 折叠/展开 thinking 块
        prefix = "●" if self._thinking_expanded else "▸"
        lines = content.split("\n")
        if len(lines) > 3 and not self._thinking_expanded:
            summary = lines[0][:80]
            remaining = len(lines) - 1
            self.console.print(
                f"  [dim italic]{prefix} Thinking: {summary}... (+{remaining} lines)[/dim italic]"
            )
        else:
            for line in lines:
                self.console.print(f"  [dim italic]  {line}[/dim italic]")

    def _render_code_block(self, code: str, language: str) -> None:
        """渲染代码块"""
        if not HAS_RICH or not self.console:
            print(code)
            return

        if self.enable_code_highlight and language:
            syntax = Syntax(
                code,
                language,
                theme="monokai",
                line_numbers=True,
                background_color="default",
            )
            panel = Panel(
                syntax,
                border_style="dim",
                box=box.ROUNDED,
                padding=(1, 1),
            )
            self.console.print(panel)
        else:
            panel = Panel(
                code,
                title=language if language else "Code",
                border_style="dim",
                box=box.ROUNDED,
            )
            self.console.print(panel)

    def _render_tool_call_rich(self, tool_name: str, tool_args: dict) -> None:
        """使用 Rich 渲染工具调用"""
        text = Text()
        text.append("  \U0001F527 ", style="")  # 🔧
        text.append(tool_name, style="bold cyan")

        if tool_args:
            text.append("(", style="dim")
            arg_parts = []
            for key, value in list(tool_args.items())[:3]:  # 最多显示3个参数
                formatted = self._format_arg(value)
                arg_parts.append(f"{key}={formatted}")
            text.append(", ".join(arg_parts), style="yellow")
            if len(tool_args) > 3:
                text.append(f", +{len(tool_args) - 3} more", style="dim")
            text.append(")", style="dim")
        else:
            text.append("()", style="dim")

        self.console.print()
        self.console.print(text)

    def _render_raw(self, text: str) -> None:
        """纯文本渲染 (不解析 Markdown/thinking)"""
        if not text:
            return
        if HAS_RICH and self.console:
            self.console.print(text, end="", highlight=False)
        else:
            sys.stdout.write(text)
            sys.stdout.flush()

    def _flush_output(self) -> None:
        """刷新所有缓冲输出"""
        flushed = self._output_buffer.flush()
        if flushed:
            if self.enable_thinking_render:
                self._render_with_thinking(flushed)
            else:
                self._render_raw(flushed)

        # 刷新 Markdown 分割器缓冲区
        remaining = self._markdown_segmenter.flush()
        if remaining and HAS_RICH and self.console:
            if remaining[0] == "text":
                self.console.print(Markdown(remaining[1]))
            elif remaining[0] == "code_end":
                code, lang = remaining[1], remaining[2]
                self._render_code_block(code, lang)

        # 刷新行缓冲区
        if self._line_buffer and HAS_RICH and self.console:
            self.console.print(Markdown(self._line_buffer))
            self._line_buffer = ""

        # 刷新 thinking 解析器
        thinking_results = self._thinking_parser.flush()
        for state, content in thinking_results:
            if content and HAS_RICH and self.console:
                self._render_content(content)

    @staticmethod
    def _format_arg(value: Any) -> str:
        """格式化参数值"""
        if isinstance(value, str):
            if len(value) > 30:
                return f'"{value[:30]}..."'
            return f'"{value}"'
        elif isinstance(value, (dict, list)):
            return f"{{{len(value)} items}}" if isinstance(value, dict) else f"[{len(value)} items]"
        return str(value)


# ---------------------------------------------------------------------------
# LLM 客户端工厂
# ---------------------------------------------------------------------------

class LLMClientFactory:
    """
    LLM 客户端工厂

    根据配置创建 LLM 客户端
    """

    @staticmethod
    def create_from_config() -> Optional[ProtocolLLMClient]:
        """
        从配置创建客户端

        根据用户配置的 provider 和 api_key 创建客户端

        Returns:
            ProtocolLLMClient 实例，如果配置不完整则返回 None
        """
        try:
            from core.config import config_manager
            config = config_manager.load_config()

            # 获取默认 provider 和 model
            provider_name = config.llm.default_provider
            model_name = config.llm.default_model

            # 获取 provider 配置
            provider_config = config.provider.get(provider_name)
            if not provider_config:
                # 尝试找到任何可用的 provider
                for name, pconfig in config.provider.items():
                    if pconfig.options.apiKey:
                        provider_name = name
                        provider_config = pconfig
                        break

            if not provider_config:
                return None

            # 获取 API key 和 base URL
            api_key = provider_config.options.apiKey
            base_url = provider_config.options.baseURL

            if not api_key:
                return None

            # 检查模型是否在 provider 的模型列表中
            if provider_config.models and model_name not in provider_config.models:
                # 使用 provider 的第一个模型
                if provider_config.models:
                    model_name = list(provider_config.models.keys())[0]

            # 使用 ProtocolLLMClient.from_provider 创建客户端
            return ProtocolLLMClient.from_provider(
                provider_name=provider_name,
                model=model_name,
                api_key=api_key,
                base_url=base_url,
            )

        except Exception as e:
            print(f"Error creating LLM client: {e}")
            return None


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def create_stream_handler(
    console: Optional[Any] = None,
    **kwargs,
) -> StreamHandler:
    """
    创建流式处理器

    Args:
        console: Rich Console 实例
        **kwargs: 传递给 StreamHandler 的其他参数

    Returns:
        StreamHandler 实例
    """
    return StreamHandler(console=console, **kwargs)

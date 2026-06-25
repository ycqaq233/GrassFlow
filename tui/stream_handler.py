"""
流式输出处理器

支持 LLM 流式响应的实时渲染
"""

import asyncio
import sys
from typing import Optional, Callable, Any

try:
    from rich.console import Console
    from rich.live import Live
    from rich.text import Text
    from rich.markdown import Markdown
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from core.llm_protocol import (
    LLMEvent, LLMEventType, ProtocolLLMClient, ProtocolLLMManager,
    OpenAIChatProtocol, Endpoint, Auth, SSEFraming, Message
)


class StreamHandler:
    """
    流式输出处理器

    支持：
    - LLM 流式响应
    - 实时 token 渲染
    - 中断处理
    """

    def __init__(
        self,
        console: Optional[Any] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        self.console = console or Console() if HAS_RICH else None
        self.on_token = on_token
        self.on_complete = on_complete
        self.on_error = on_error
        self._interrupted = False
        self._current_text = ""

    def interrupt(self):
        """中断当前流式输出"""
        self._interrupted = True

    def reset(self):
        """重置状态"""
        self._interrupted = False
        self._current_text = ""

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
            # 开始流式输出
            if HAS_RICH and self.console:
                self.console.print()  # 换行

            # 构建完整消息列表（包含系统提示）
            full_messages = []
            if system:
                for msg in system:
                    full_messages.append({"role": "system", "content": msg.content})
            for msg in messages:
                full_messages.append({"role": msg.role, "content": msg.content})

            # 使用 stream_chat 方法
            async for event in client.stream_chat(full_messages):
                # 检查中断
                if self._interrupted:
                    break

                # 处理事件
                if event.type == LLMEventType.TEXT_DELTA:
                    token = event.data.get("text", "")
                    self._current_text += token

                    # 调用回调
                    if self.on_token:
                        self.on_token(token)

                    # 实时输出
                    if HAS_RICH and self.console:
                        self.console.print(token, end="", highlight=False)
                    else:
                        sys.stdout.write(token)
                        sys.stdout.flush()

                elif event.type == LLMEventType.TEXT_START:
                    # 文本开始
                    pass

                elif event.type == LLMEventType.TEXT_END:
                    # 文本结束
                    if HAS_RICH and self.console:
                        self.console.print()  # 换行
                    else:
                        print()

                elif event.type == LLMEventType.TOOL_CALL:
                    # 工具调用
                    tool_name = event.data.get("tool_name", "unknown")
                    if HAS_RICH and self.console:
                        self.console.print(f"\n[dim]Calling tool: {tool_name}[/dim]")
                    else:
                        print(f"\nCalling tool: {tool_name}")

                elif event.type == LLMEventType.FINISH:
                    # 完成
                    break

                elif event.type == LLMEventType.PROVIDER_ERROR:
                    # 错误
                    error_msg = event.data.get("message", "Unknown error")
                    raise Exception(error_msg)

            # 调用完成回调
            if self.on_complete:
                self.on_complete(self._current_text)

            return self._current_text

        except Exception as e:
            # 调用错误回调
            if self.on_error:
                self.on_error(e)
            raise


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


def create_stream_handler(console: Optional[Any] = None) -> StreamHandler:
    """
    创建流式处理器

    Args:
        console: Rich Console 实例

    Returns:
        StreamHandler 实例
    """
    return StreamHandler(console=console)

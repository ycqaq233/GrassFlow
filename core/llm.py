"""
GrassFlow LLM API 调用封装

使用 LiteLLM 封装 LLM API 调用，支持：
- OpenAI API
- Anthropic API
- 本地模型（Ollama）
"""

import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    usage: Dict[str, int]  # {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    finish_reason: str
    tool_calls: Optional[List[Any]] = None


class LLMError(Exception):
    """LLM 调用错误"""
    pass


class LLMClient:
    """LLM 客户端"""

    def __init__(
        self,
        model: str = "default",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
        max_retries: int = 3,
    ):
        """
        初始化 LLM 客户端

        Args:
            model: 模型名称
            api_key: API 密钥
            base_url: API 基础 URL（用于本地模型）
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        发送聊天请求

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Returns:
            LLMResponse 对象

        Raises:
            LLMError: 调用失败
        """
        try:
            import litellm

            # 准备参数
            params = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }

            if max_tokens is not None:
                params["max_tokens"] = max_tokens

            if self.api_key:
                params["api_key"] = self.api_key

            if self.base_url:
                params["api_base"] = self.base_url

            # 传递超时参数，防止 HTTP 请求无限挂起
            params["timeout"] = self.timeout

            params.update(kwargs)

            # 调用 API
            response = await litellm.acompletion(**params)

            # 解析 tool_calls（如果有）
            tool_calls_data = None
            if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
                tool_calls_data = response.choices[0].message.tool_calls

            # 解析响应
            return LLMResponse(
                content=response.choices[0].message.content,
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                finish_reason=response.choices[0].finish_reason,
                tool_calls=tool_calls_data,
            )

        except ImportError:
            raise LLMError("litellm is not installed. Run: pip install litellm")
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}")

    async def complete(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        发送补全请求

        Args:
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Returns:
            LLMResponse 对象
        """
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature, max_tokens, **kwargs)


class LLMManager:
    """LLM 管理器"""

    def __init__(self):
        """初始化 LLM 管理器"""
        self._clients: Dict[str, LLMClient] = {}

    def register(self, name: str, client: LLMClient) -> None:
        """
        注册 LLM 客户端

        Args:
            name: 客户端名称
            client: LLM 客户端实例
        """
        self._clients[name] = client

    def get(self, name: str) -> LLMClient:
        """
        获取 LLM 客户端

        Args:
            name: 客户端名称

        Returns:
            LLM 客户端实例

        Raises:
            LLMError: 客户端不存在
        """
        if name not in self._clients:
            raise LLMError(f"LLM client '{name}' not registered")
        return self._clients[name]

    def create(
        self,
        name: str,
        model: str = "default",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> LLMClient:
        """
        创建并注册 LLM 客户端

        Args:
            name: 客户端名称
            model: 模型名称
            api_key: API 密钥
            base_url: API 基础 URL
            **kwargs: 其他参数

        Returns:
            LLM 客户端实例
        """
        client = LLMClient(model=model, api_key=api_key, base_url=base_url, **kwargs)
        self.register(name, client)
        return client


# 全局 LLM 管理器
llm_manager = LLMManager()

"""
GrassFlow LLM Agent

使用 LLM API 的 Agent 实现
"""

import logging
from typing import Dict, Any, Optional, List
from core.agent import Agent, AgentConfig
from core.llm import LLMClient, LLMManager, llm_manager

logger = logging.getLogger(__name__)


def _resolve_default_model() -> str:
    """从配置中获取默认模型，而非硬编码 gpt-4。"""
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        return config.llm.default_model
    except Exception:
        return "gpt-4"


def _resolve_model(model: str) -> str:
    """解析模型名称，处理 'default' 和 provider 前缀。

    - 'default' 或空字符串 -> 使用配置中的默认模型
    - 已有 provider 前缀 (如 'deepseek/xxx') -> 原样返回
    - 模型名不在当前 provider 的模型列表中 -> 回退到配置默认模型

    这解决了 DSL 工作流硬编码 'gpt-4' 但系统使用 DeepSeek 的问题。
    """
    if not model or model == "default":
        return _resolve_default_model()

    # 如果模型名已包含 provider 前缀，直接返回
    if "/" in model:
        return model

    # 检查配置的 provider，判断模型是否在可用列表中
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        provider = config.llm.default_provider
        default_model = config.llm.default_model

        # 优先检查 provider 的模型列表
        provider_config = config.provider.get(provider)
        if provider_config and provider_config.models:
            available_models = set(provider_config.models.keys())
            if model not in available_models:
                logger.info(
                    "Model '%s' not found in provider '%s' models, "
                    "falling back to configured default '%s'",
                    model, provider, default_model,
                )
                return default_model
        else:
            # 已知的 provider 模型前缀映射（后备方案）
            provider_model_prefixes = {
                "openai": ["gpt-", "o1-", "o3-", "o4-"],
                "deepseek": ["deepseek-"],
                "anthropic": ["claude-"],
                "ollama": [],
            }
            prefixes = provider_model_prefixes.get(provider, [])
            if prefixes:
                matches_provider = any(model.startswith(p) for p in prefixes)
                if not matches_provider:
                    logger.info(
                        "Model '%s' does not match provider '%s', using default: %s",
                        model, provider, default_model,
                    )
                    return default_model

        # deepseek 模型需要前缀才能被 LiteLLM 正确路由
        if provider == "deepseek" and "deepseek" in model.lower() and "/" not in model:
            return f"deepseek/{model}"

    except Exception:
        pass
    return model


class LLMAgent(Agent):
    """
    LLM Agent

    使用 LLM API 执行任务的 Agent。

    使用方式：
    1. 在 DSL 中定义：agent classify { model: "gpt-4", prompt: "分类工单: {input}" }
    2. 在执行流中使用：classify -> route

    LLMAgent 会：
    1. 将输入数据格式化为 prompt
    2. 调用 LLM API
    3. 解析 LLM 输出为结构化数据
    """

    def __init__(
        self,
        name: str,
        model: str = "default",
        prompt: str = "",
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        llm_client: Optional[LLMClient] = None,
        llm_manager: Optional[LLMManager] = None,
    ):
        """
        初始化 LLMAgent

        Args:
            name: Agent 名称
            model: 模型名称
            prompt: 提示词模板，支持 {input} 和 {field} 占位符
            input_schema: 输入 Schema
            output_schema: 输出 Schema
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            llm_client: LLM 客户端实例（优先使用）
            llm_manager: LLM 管理器（用于获取客户端）
        """
        # 解析模型名称（处理 'default'、provider 前缀等）
        resolved_model = _resolve_model(model)
        if resolved_model != model:
            logger.debug("Model resolved: %s -> %s", model, resolved_model)

        config = AgentConfig(
            name=name,
            model=resolved_model,
            prompt=prompt,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
        )
        super().__init__(config)

        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 获取 LLM 客户端
        if llm_client:
            self._client = llm_client
        else:
            manager = llm_manager or globals()["llm_manager"]
            # 如果客户端不存在，创建一个（使用解析后的模型名）
            try:
                self._client = manager.get(resolved_model)
            except Exception:
                self._client = manager.create(resolved_model, model=resolved_model)

    def _format_prompt(self, input_data: Dict[str, Any]) -> str:
        """
        格式化提示词

        Args:
            input_data: 输入数据

        Returns:
            格式化后的提示词
        """
        if not self.config.prompt:
            # 如果没有 prompt，直接返回输入数据的字符串表示
            return str(input_data)

        # 准备替换变量
        variables = {"input": str(input_data)}

        # 添加输入数据的各个字段
        for key, value in input_data.items():
            if key != "_deps":
                variables[key] = str(value)

        # 添加依赖数据
        deps = input_data.get("_deps", {})
        for dep_name, dep_data in deps.items():
            variables[f"dep_{dep_name}"] = str(dep_data)

        # 格式化 prompt
        try:
            return self.config.prompt.format(**variables)
        except KeyError as e:
            # 如果缺少变量，返回原始 prompt
            return self.config.prompt

    def _parse_response(self, response_content: str) -> Dict[str, Any]:
        """
        解析 LLM 响应

        Args:
            response_content: LLM 响应内容

        Returns:
            解析后的数据
        """
        # 尝试解析为 JSON
        try:
            import json
            return json.loads(response_content)
        except json.JSONDecodeError:
            pass

        # 如果不是 JSON，返回为文本
        return {"text": response_content}

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 LLM Agent

        Args:
            input_data: 输入数据

        Returns:
            输出数据
        """
        # 格式化 prompt
        prompt = self._format_prompt(input_data)

        # 准备消息
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 调用 LLM API
        response = await self._client.chat(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        # 解析响应
        result = self._parse_response(response.content)

        # 添加元数据
        result["_llm"] = {
            "model": response.model,
            "usage": response.usage,
            "finish_reason": response.finish_reason,
        }

        return result


class LLMAgentFactory:
    """LLM Agent 工厂"""

    def __init__(self, llm_manager: Optional[LLMManager] = None):
        """
        初始化工厂

        Args:
            llm_manager: LLM 管理器
        """
        self._manager = llm_manager or globals()["llm_manager"]

    def create(
        self,
        name: str,
        model: Optional[str] = None,
        prompt: str = "",
        **kwargs,
    ) -> LLMAgent:
        """
        创建 LLM Agent

        Args:
            name: Agent 名称
            model: 模型名称
            prompt: 提示词模板
            **kwargs: 其他参数

        Returns:
            LLMAgent 实例
        """
        # Resolve model: use provided, or fall back to configured default
        resolved = model if model is not None else _resolve_model("gpt-4")
        return LLMAgent(
            name=name,
            model=resolved,
            prompt=prompt,
            llm_manager=self._manager,
            **kwargs,
        )

    def create_from_config(self, config: AgentConfig) -> LLMAgent:
        """
        从配置创建 LLM Agent

        Args:
            config: Agent 配置

        Returns:
            LLMAgent 实例
        """
        return LLMAgent(
            name=config.name,
            model=config.model,
            prompt=config.prompt,
            input_schema=config.input_schema,
            output_schema=config.output_schema,
            llm_manager=self._manager,
        )


# 全局工厂
llm_agent_factory = LLMAgentFactory()

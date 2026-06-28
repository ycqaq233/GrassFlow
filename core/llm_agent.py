"""
GrassFlow LLM Agent

使用 LLM API 的 Agent 实现。
LLMAgent 从 Component 构造。
"""

import logging
from typing import Dict, Any, Optional

from core.agent import Agent
from core.models import Component, ModelConfig
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
    """
    if not model or model == "default":
        return _resolve_default_model()

    if "/" in model:
        return model

    try:
        from core.config import config_manager
        config = config_manager.load_config()
        provider = config.llm.default_provider
        default_model = config.llm.default_model

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

        if provider == "deepseek" and "deepseek" in model.lower() and "/" not in model:
            return f"deepseek/{model}"

    except Exception:
        pass
    return model


class LLMAgent(Agent):
    """
    LLM Agent

    使用 LLM API 执行任务的 Agent。

    从 DSL v2 Component 构造：
        agent = LLMAgent(component)

    LLMAgent 会：
    1. 将输入数据格式化为 prompt
    2. 调用 LLM API
    3. 解析 LLM 输出为结构化数据
    """

    def __init__(
        self,
        component: Component,
        llm_client: Optional[LLMClient] = None,
        llm_manager: Optional[LLMManager] = None,
    ):
        """
        从 Component 初始化 LLMAgent

        Args:
            component: DSL v2 组件定义
            llm_client: LLM 客户端实例（优先使用）
            llm_manager: LLM 管理器（用于获取客户端）
        """
        super().__init__(component)

        # 解析模型名称（处理 'default'、provider 前缀等）
        raw_model = component.model.default or "default"
        resolved_model = _resolve_model(raw_model)
        if resolved_model != raw_model:
            logger.debug("Model resolved: %s -> %s", raw_model, resolved_model)

        # 保存解析后的模型名
        self._resolved_model = resolved_model

        # 从 Component 提取配置
        self.system_prompt = component.system_prompt
        self.temperature = component.model.temperature if component.model.temperature is not None else 0.7
        self.max_tokens = component.model.max_tokens

        # 获取 LLM 客户端
        if llm_client:
            self._client = llm_client
        else:
            from core.config import config_manager
            manager = llm_manager or globals()["llm_manager"]

            # 从配置获取 provider 的 api_key 和 base_url
            config = config_manager.load_config()
            provider_name = config.llm.default_provider
            provider_config = config.provider.get(provider_name)
            api_key = provider_config.options.apiKey if provider_config else None
            base_url = provider_config.options.baseURL if provider_config else None

            try:
                self._client = manager.get(resolved_model)
            except Exception:
                self._client = manager.create(
                    resolved_model,
                    model=resolved_model,
                    api_key=api_key,
                    base_url=base_url,
                )

    @property
    def resolved_model(self) -> str:
        return self._resolved_model

    def _format_prompt(self, input_data: Dict[str, Any]) -> str:
        """格式化提示词

        当 input_data 中包含 `task` 字段时，优先使用 task 作为 prompt 的主输入内容。
        这使得工作流可以通过 --task 选项接收用户指令。
        """
        prompt = self._component.system_prompt or ""

        if not prompt:
            return str(input_data)

        # 优先使用 task 字段作为 input 变量的值
        task_value = input_data.get("task")
        if task_value:
            variables = {"input": str(task_value), "task": str(task_value)}
        else:
            variables = {"input": str(input_data)}

        for key, value in input_data.items():
            if key != "_deps":
                variables[key] = str(value)

        deps = input_data.get("_deps", {})
        for dep_name, dep_data in deps.items():
            variables[f"dep_{dep_name}"] = str(dep_data)

        try:
            return prompt.format(**variables)
        except KeyError:
            return prompt

    def _parse_response(self, response_content: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        try:
            import json
            return json.loads(response_content)
        except json.JSONDecodeError:
            pass

        return {"text": response_content}

    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行 LLM Agent"""
        prompt = self._format_prompt(input_data)

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        result = self._parse_response(response.content)

        result["_llm"] = {
            "model": response.model,
            "usage": response.usage,
            "finish_reason": response.finish_reason,
        }

        return result


class LLMAgentFactory:
    """LLM Agent 工厂"""

    def __init__(self, llm_manager: Optional[LLMManager] = None):
        self._manager = llm_manager or globals()["llm_manager"]

    def create(
        self,
        component: Component,
        **kwargs,
    ) -> LLMAgent:
        """
        从 Component 创建 LLM Agent

        Args:
            component: DSL v2 组件定义
            **kwargs: 额外参数（如 llm_client）

        Returns:
            LLMAgent 实例
        """
        return LLMAgent(
            component=component,
            llm_manager=self._manager,
            **kwargs,
        )


# 全局工厂
llm_agent_factory = LLMAgentFactory()

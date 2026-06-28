"""
GrassFlow LLM Agent

使用 LLM API 的 Agent 实现

重构：LLMAgent 从 Component 构造，而非分散参数。
"""

import logging
from typing import Dict, Any, Optional, List

from core.agent import Agent, AgentConfig
from core.llm import LLMClient, LLMManager, llm_manager

try:
    from core.models import Component
except ImportError:
    from core.dsl_v2_ast import Component

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


def _build_agent_config(component: Component) -> AgentConfig:
    """从 Component 构建 AgentConfig，用于 Agent 基类初始化。

    Args:
        component: DSL v2 组件定义

    Returns:
        AgentConfig 实例
    """
    # 获取端口定义
    input_ports = {p.name: p.type for p in component.ports if p.direction == "input"}
    output_ports = {p.name: p.type for p in component.ports if p.direction == "output"}

    # 构建 JSON Schema
    input_schema: Dict[str, Any] = {}
    if input_ports:
        input_schema = {
            "type": "object",
            "properties": {name: {"type": t} for name, t in input_ports.items()},
        }

    output_schema: Dict[str, Any] = {}
    if output_ports:
        output_schema = {
            "type": "object",
            "properties": {name: {"type": t} for name, t in output_ports.items()},
        }

    return AgentConfig(
        name=component.name,
        model=component.model.default or "default",
        prompt=component.system_prompt or "",
        input_schema=input_schema,
        output_schema=output_schema,
        on_fail=component.on_fail,
        retry_count=component.retry_count,
    )


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
            component: DSL v2 组件定义，提供模型名、系统提示词、参数等配置
            llm_client: LLM 客户端实例（优先使用）
            llm_manager: LLM 管理器（用于获取客户端）
        """
        # 从 Component 构建 AgentConfig 给基类
        config = _build_agent_config(component)
        super().__init__(config)

        # 保留 Component 引用
        self.component = component

        # 解析模型名称（处理 'default'、provider 前缀等）
        raw_model = component.model.default or "default"
        resolved_model = _resolve_model(raw_model)
        if resolved_model != raw_model:
            logger.debug("Model resolved: %s -> %s", raw_model, resolved_model)

        # 更新基类 config 中的模型名（已解析）
        self.config.model = resolved_model

        # 从 Component 提取配置
        self.system_prompt = component.system_prompt
        self.temperature = component.model.temperature if component.model.temperature is not None else 0.7
        self.max_tokens = component.model.max_tokens

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

    def create_from_config(self, config: AgentConfig) -> LLMAgent:
        """
        从旧版 AgentConfig 创建 LLM Agent（向后兼容）

        Args:
            config: Agent 配置

        Returns:
            LLMAgent 实例
        """
        # 将旧版 AgentConfig 转换为 Component
        from core.dsl_v2_ast import ModelConfig
        component = Component(
            name=config.name,
            system_prompt=config.prompt,
            model=ModelConfig(
                default=config.model,
                temperature=0.7,
                max_tokens=None,
            ),
            on_fail=config.on_fail,
            retry_count=config.retry_count,
        )
        return LLMAgent(
            component=component,
            llm_manager=self._manager,
        )


# 全局工厂
llm_agent_factory = LLMAgentFactory()

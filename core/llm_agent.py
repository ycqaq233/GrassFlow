"""
GrassFlow LLM Agent

使用 LLM API 的 Agent 实现。
LLMAgent 从 Component 构造。
"""

import json
import logging
from typing import Dict, Any, List, Optional

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
        tool_registry=None,
    ):
        """
        从 Component 初始化 LLMAgent

        Args:
            component: DSL v2 组件定义
            llm_client: LLM 客户端实例（优先使用）
            llm_manager: LLM 管理器（用于获取客户端）
            tool_registry: 工具注册表（core.tool_registry.ToolRegistry），用于工具调用
        """
        super().__init__(component)
        self.tool_registry = tool_registry

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

        # 记录 MCP 声明（基础版：仅打印日志，不做实际连接）
        if component.mcp:
            for mcp in component.mcp:
                logger.info(
                    "[MCP] %s declares MCP server '%s' with tools: %s",
                    component.name, mcp.server_name, mcp.tools,
                )
                # TODO: 实际连接 MCP 服务器并注册工具

    @property
    def resolved_model(self) -> str:
        return self._resolved_model

    def _format_prompt(self, input_data: Dict[str, Any]) -> str:
        """格式化提示词

        当 input_data 中包含 `task` 字段时，优先使用 task 作为 prompt 的主输入内容。
        这使得工作流可以通过 --task 选项接收用户指令。

        如果 prompt 中没有 {input} 或 {task} 占位符，会自动将 task 内容追加到末尾。
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
            formatted = prompt.format(**variables)
        except KeyError:
            formatted = prompt

        # 如果 prompt 中没有 {input} 或 {task} 占位符，但有 task 内容，追加到末尾
        has_placeholder = "{input}" in prompt or "{task}" in prompt
        if not has_placeholder and task_value:
            formatted = f"{formatted}\n\n任务: {task_value}"

        return formatted

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

        # 如果有工具注册表，使用工具调用循环
        if self.tool_registry:
            return await self._run_with_tools(messages, input_data)

        # 原有的无工具路径
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

    async def _run_with_tools(self, messages: List[Dict], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """带工具调用的执行循环"""
        # 允许通过 component.max_tool_iterations 自定义，默认 30
        max_iterations = getattr(self._component, 'max_tool_iterations', None) or 30
        tools_schema = self._get_tools_schema()
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        last_model = ""
        tool_calls_log = []

        for i in range(max_iterations):
            response = await self._client.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=tools_schema,
            )

            # 累计 usage
            if response.usage:
                for key in total_usage:
                    total_usage[key] += response.usage.get(key, 0)
            last_model = response.model

            # 如果有工具调用，执行它们
            if response.tool_calls:
                # 把 assistant 消息（含 tool_calls）加入 messages
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": response.content or ""}
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    } for tc in response.tool_calls
                ]
                messages.append(assistant_msg)

                # 执行每个工具调用
                for tc in response.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}

                    # 通过 tool_registry 调用
                    try:
                        if self.tool_registry.has(tool_name):
                            tool_result = await self.tool_registry.invoke(tool_name, tool_args)
                            result_str = tool_result.output if hasattr(tool_result, 'output') else str(tool_result)
                        else:
                            result_str = f"Error: Tool '{tool_name}' not found"
                    except Exception as e:
                        result_str = f"Error: {e}"

                    # 截断过大的工具结果，防止上下文窗口溢出
                    # 保留首尾各 MAX_TOOL_RESULT_CHARS/2 字符，中间用省略提示
                    MAX_TOOL_RESULT_CHARS = 6000
                    if len(result_str) > MAX_TOOL_RESULT_CHARS:
                        half = MAX_TOOL_RESULT_CHARS // 2
                        truncated_msg = (
                            f"\n\n... [truncated {len(result_str) - MAX_TOOL_RESULT_CHARS} chars, "
                            f"total {len(result_str)} chars] ..."
                        )
                        result_str = result_str[:half] + truncated_msg + result_str[-half:]

                    tool_calls_log.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result_preview": result_str[:200] if len(result_str) > 200 else result_str,
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
                continue  # 继续循环，让 LLM 处理工具结果

            # 没有工具调用，解析最终结果
            result = self._parse_response(response.content)

            result["_llm"] = {
                "model": last_model,
                "usage": total_usage,
                "finish_reason": response.finish_reason,
            }
            if tool_calls_log:
                result["_tool_calls"] = tool_calls_log

            return result

        # 达到最大迭代次数 — 强制 LLM 生成最终回复（不带工具）
        logger.warning(
            "Agent '%s' reached max tool iterations (%d), forcing final response",
            self._component.name, max_iterations,
        )
        messages.append({
            "role": "user",
            "content": (
                "You have reached the maximum number of tool calls. "
                "Please stop calling tools and generate your final response NOW "
                "based on the data you have collected so far. "
                "Output your analysis/report as text."
            ),
        })
        try:
            final_response = await self._client.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            result = self._parse_response(final_response.content)
            if final_response.usage:
                for key in total_usage:
                    total_usage[key] += final_response.usage.get(key, 0)
        except Exception:
            result = {"text": "[Agent reached iteration limit and could not generate final response]"}

        result["_llm"] = {
            "model": last_model,
            "usage": total_usage,
            "finish_reason": "max_tool_iterations",
        }
        if tool_calls_log:
            result["_tool_calls"] = tool_calls_log
        return result

    def _get_tools_schema(self) -> List[Dict]:
        """从 tool_registry 获取 OpenAI 格式的工具定义"""
        if not self.tool_registry:
            return []
        # 优先使用 core.tool_registry.ToolRegistry 的 to_llm_tool_list()
        if hasattr(self.tool_registry, 'to_llm_tool_list'):
            return self.tool_registry.to_llm_tool_list()
        # 回退：手动从 list_tools 构建
        tools = []
        for tool in self.tool_registry.list_tools():
            schema = tool.schema() if hasattr(tool, 'schema') else {}
            tools.append({
                "type": "function",
                "function": {
                    "name": schema.get("name", tool.id),
                    "description": schema.get("description", ""),
                    "parameters": schema.get("parameters", {"type": "object", "properties": {}}),
                }
            })
        return tools


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

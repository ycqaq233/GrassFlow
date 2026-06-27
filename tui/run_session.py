"""
GrassFlow Run Session — 单次 prompt 执行

提供 `grassflow ask` 命令的后端实现：
- 创建临时会话（不持久化到 SQLite）
- 初始化工具、MCP 和 Skills（复用 AgentIntegration）
- 将 prompt 发送给 agent loop
- 流式输出到 stdout（纯文本，无 Rich 格式）
- 响应完成后退出

参考 opencode 的 `run` 命令模式。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _print(text: str) -> None:
    """输出纯文本到 stdout（无 Rich 格式）"""
    print(text, flush=True)


def _print_err(text: str) -> None:
    """输出错误信息到 stderr"""
    print(text, file=sys.stderr, flush=True)


async def run_single_prompt(
    prompt: str,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    no_tools: bool = False,
    system_prompt: Optional[str] = None,
) -> int:
    """执行单次 prompt 并输出结果。

    创建临时 AgentIntegration 实例，初始化 agent loop，
    发送 prompt 并流式输出响应到 stdout。

    Args:
        prompt: 用户 prompt 文本
        model: 模型名称（覆盖配置默认值）
        provider: provider 名称（覆盖配置默认值）
        no_tools: 是否禁用工具调用
        system_prompt: 自定义系统提示词

    Returns:
        退出码：0 表示成功，1 表示出错
    """
    from tui.agent_integration import AgentIntegration
    from tui.config_integration import config_manager

    # 创建 AgentIntegration（不使用 session manager）
    integration = AgentIntegration(
        config_manager=config_manager,
        session_manager=None,
        enable_streaming=True,
    )

    # 初始化 agent loop
    if not integration.init_agent_loop():
        _print_err("Error: Failed to initialize agent loop. Check your LLM configuration.")
        return 1

    # 设置权限回调：非交互模式下自动批准所有工具调用
    if integration._agent_loop:
        async def _auto_approve(tool_name: str, description: str, args_preview: str) -> str:
            """非交互模式自动批准工具调用"""
            return "session"
        integration._agent_loop.set_permission_callback(_auto_approve)

    # 如果指定了 model/provider，覆盖 agent loop 配置
    if model or provider:
        _apply_model_override(integration, model, provider)

    # 如果禁用工具，清空工具注册表
    if no_tools and integration._agent_loop:
        try:
            integration._agent_loop._tool_registry = None
            integration._agent_loop._tools_cache = None
        except Exception:
            pass

    # 构建系统提示词
    if system_prompt is None:
        system_prompt = _build_system_prompt()

    # 执行
    exit_code = 0
    try:
        full_response = await _consume_stream(integration, prompt, system_prompt)
        if not full_response.strip():
            _print_err("Warning: Empty response from agent.")
    except KeyboardInterrupt:
        _print_err("\nInterrupted.")
        exit_code = 130
    except Exception as e:
        _print_err(f"Error: {e}")
        exit_code = 1
    finally:
        # 清理 MCP 资源
        try:
            await integration.shutdown()
        except Exception:
            pass

    return exit_code


async def _consume_stream(
    integration: Any,
    prompt: str,
    system_prompt: str,
) -> str:
    """消费 agent loop 事件流，输出到 stdout。

    事件处理：
    - text_delta: 流式输出文本 token
    - text_end: 刷新缓冲区
    - thinking_delta: 累积（可选折叠显示）
    - tool_call_start: 打印工具调用摘要
    - tool_result: 打印工具结果摘要
    - error: 打印错误
    - usage: 记录统计

    Returns:
        完整的响应文本
    """
    full_response = ""
    buf = ""
    thinking_count = 0
    tool_call_count = 0
    box_opened = False

    async for event in integration.process_streaming(
        text=prompt,
        history=[],
        system_prompt=system_prompt,
    ):
        etype = event.type
        edata = event.data

        if etype == "text_delta":
            token = edata.get("text", "")
            if not token:
                continue
            full_response += token
            buf += token

            # 首次可见文本时打印空行分隔
            if not box_opened:
                stripped = token.lstrip("\n")
                if stripped:
                    box_opened = True

            # 行缓冲：发射完整行
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                _print(line)

        elif etype == "text_end":
            # 刷新剩余缓冲
            if buf:
                _print(buf)
                buf = ""

        elif etype == "thinking_delta":
            thinking_count += 1

        elif etype == "tool_call_start":
            # 刷新文本缓冲
            if buf:
                _print(buf)
                buf = ""
            tool_call_count += 1
            name = edata.get("name", "tool")
            args = edata.get("args", {})
            args_str = json.dumps(args, ensure_ascii=False)
            if len(args_str) > 120:
                args_str = args_str[:117] + "..."
            _print_err(f"  [tool] {name}({args_str})")

        elif etype == "tool_result":
            # 刷新文本缓冲
            if buf:
                _print(buf)
                buf = ""
            result = edata.get("result", edata.get("output", ""))
            is_err = edata.get("is_error", edata.get("success", True) is False)
            result_str = str(result).replace("\n", " ").strip()
            if len(result_str) > 200:
                result_str = result_str[:197] + "..."
            if is_err:
                _print_err(f"  [tool error] {result_str}")
            else:
                _print_err(f"  [tool] -> {result_str}")

        elif etype == "error":
            if buf:
                _print(buf)
                buf = ""
            msg = edata.get("message", str(edata))
            _print_err(f"  [error] {msg}")

        elif etype == "interrupted":
            if buf:
                _print(buf)
                buf = ""
            _print_err("  Interrupted.")
            break

        elif etype == "usage":
            # 静默记录统计
            pass

    # 最终刷新
    if buf:
        _print(buf)

    return full_response


def _apply_model_override(
    integration: Any,
    model: Optional[str],
    provider: Optional[str],
) -> None:
    """覆盖 agent loop 的模型配置。"""
    if not integration._agent_loop:
        return
    loop = integration._agent_loop
    try:
        if model:
            loop._model_name = model
        if provider:
            loop._provider_name = provider
        # 重建 LLM client
        if model or provider:
            _rebuild_client(loop, model, provider)
    except Exception as e:
        logger.debug("Failed to apply model override: %s", e)


def _rebuild_client(loop: Any, model: Optional[str], provider: Optional[str]) -> None:
    """根据新的 model/provider 重建 LLM client。"""
    from tui.config_integration import get_api_key

    provider_name = provider or loop._provider_name
    model_name = model or loop._model_name

    api_key = get_api_key(provider_name)
    base_url = None

    # 从配置获取 base_url
    try:
        from tui.config_integration import load_config_readonly
        config = load_config_readonly()
        provider_config = config.provider.get(provider_name)
        if provider_config:
            opts = getattr(provider_config, "options", None)
            if opts:
                if not api_key:
                    api_key = getattr(opts, "apiKey", None) or getattr(opts, "api_key", None)
                base_url = getattr(opts, "baseURL", None) or getattr(opts, "base_url", None)
    except Exception:
        pass

    if not api_key:
        logger.warning("No API key for provider '%s', using existing client", provider_name)
        return

    from core.llm_protocol import (
        ProtocolLLMClient,
        openai_provider,
        deepseek_provider,
        ollama_provider,
        custom_provider,
    )

    provider_map = {
        "openai": openai_provider,
        "deepseek": deepseek_provider,
        "ollama": ollama_provider,
    }

    provider_fn = provider_map.get(provider_name)
    if provider_fn:
        provider_obj = provider_fn(api_key=api_key, model=model_name, base_url=base_url)
        loop._client = ProtocolLLMClient(provider=provider_obj, model=model_name)
        loop._model_name = model_name
        loop._provider_name = provider_name
    else:
        # 尝试 custom provider
        if base_url:
            provider_obj = custom_provider(
                api_key=api_key, model=model_name,
                base_url=base_url, provider_name=provider_name,
            )
            loop._client = ProtocolLLMClient(provider=provider_obj, model=model_name)
            loop._model_name = model_name
            loop._provider_name = provider_name


def _build_system_prompt() -> str:
    """构建 run session 的系统提示词。"""
    import os
    cwd = os.getcwd()
    base = (
        f"You are GrassFlow AI assistant.\n\n"
        f"Current directory: {cwd}\n"
        f"Answer the user's question concisely and accurately. "
        f"Use tools when needed to complete tasks."
    )
    # 注入 skills prompt
    try:
        from tui.skills_system import get_skills_manager
        skills_mgr = get_skills_manager()
        skills_prompt = skills_mgr.build_skills_prompt()
        if skills_prompt:
            base += "\n\n" + skills_prompt
    except Exception:
        pass
    return base


def run_prompt_sync(
    prompt: str,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    no_tools: bool = False,
    system_prompt: Optional[str] = None,
) -> int:
    """同步入口，包装 asyncio.run。

    Args:
        prompt: 用户 prompt
        model: 模型名称
        provider: provider 名称
        no_tools: 禁用工具
        system_prompt: 自定义系统提示词

    Returns:
        退出码
    """
    return asyncio.run(run_single_prompt(
        prompt=prompt,
        model=model,
        provider=provider,
        no_tools=no_tools,
        system_prompt=system_prompt,
    ))

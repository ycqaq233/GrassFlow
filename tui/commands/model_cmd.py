"""
grassflow models 命令

参考 opencode /models 命令，列出可用的 AI 模型：
- 从配置中读取 provider 信息
- 按 provider 分组显示模型
- 显示模型详情（上下文窗口等）
"""

import sys
from typing import Dict, List, Tuple, Optional

import click

from tui.display import display


# 已知模型的元数据（从文档和 API 获取）
KNOWN_MODELS: Dict[str, Dict[str, dict]] = {
    "openai": {
        "gpt-4o": {"display": "GPT-4o", "context": 128000},
        "gpt-4o-mini": {"display": "GPT-4o Mini", "context": 128000},
        "gpt-4-turbo": {"display": "GPT-4 Turbo", "context": 128000},
        "gpt-4": {"display": "GPT-4", "context": 8192},
        "gpt-3.5-turbo": {"display": "GPT-3.5 Turbo", "context": 16385},
        "o1": {"display": "O1", "context": 200000},
        "o1-mini": {"display": "O1 Mini", "context": 128000},
        "o3-mini": {"display": "O3 Mini", "context": 200000},
    },
    "anthropic": {
        "claude-sonnet-4-6": {"display": "Claude Sonnet 4.6", "context": 200000},
        "claude-opus-4-8": {"display": "Claude Opus 4.8", "context": 200000},
        "claude-haiku-4-5": {"display": "Claude Haiku 4.5", "context": 200000},
        "claude-fable-5": {"display": "Claude Fable 5", "context": 200000},
    },
    "deepseek": {
        "deepseek-chat": {"display": "DeepSeek Chat (V3)", "context": 65536},
        "deepseek-coder": {"display": "DeepSeek Coder (V3)", "context": 65536},
        "deepseek-reasoner": {"display": "DeepSeek Reasoner (R1)", "context": 65536},
    },
    "ollama": {
        "llama3.3": {"display": "Llama 3.3", "context": 131072},
        "llama3.2": {"display": "Llama 3.2", "context": 131072},
        "qwen3": {"display": "Qwen 3", "context": 131072},
        "deepseek-r1": {"display": "DeepSeek R1", "context": 131072},
        "codestral": {"display": "Codestral", "context": 32768},
        "mistral": {"display": "Mistral", "context": 32768},
    },
    "gemini": {
        "gemini-2.5-pro": {"display": "Gemini 2.5 Pro", "context": 1048576},
        "gemini-2.5-flash": {"display": "Gemini 2.5 Flash", "context": 1048576},
        "gemini-2.0-flash": {"display": "Gemini 2.0 Flash", "context": 1048576},
    },
}


def _get_configured_models() -> Dict[str, List[Tuple[str, str, Optional[int]]]]:
    """
    从配置中获取已配置的模型列表

    Returns:
        {provider_name: [(model_id, display_name, context_window), ...]}
    """
    result: Dict[str, List[Tuple[str, str, Optional[int]]]] = {}

    try:
        from core.config import config_manager
        config = config_manager.load_config()

        for provider_name, provider_config in config.provider.items():
            if provider_config.models:
                models = []
                for model_id, model_config in provider_config.models.items():
                    display_name = model_config.name or model_id
                    # 尝试从已知模型获取显示名称
                    if provider_name in KNOWN_MODELS and model_id in KNOWN_MODELS[provider_name]:
                        display_name = KNOWN_MODELS[provider_name][model_id]["display"]
                    context = model_config.limit.get("context") if model_config.limit else None
                    models.append((model_id, display_name, context))
                if models:
                    result[provider_name] = models

        # 如果配置中有 API key 但没有模型列表，显示已知模型
        for provider_name, provider_config in config.provider.items():
            if provider_name not in result and provider_config.options.apiKey:
                if provider_name in KNOWN_MODELS:
                    result[provider_name] = [
                        (model_id, info["display"], info["context"])
                        for model_id, info in KNOWN_MODELS[provider_name].items()
                    ]

    except Exception:
        pass

    # 如果没有在配置中找到任何模型，检查环境变量中的 API key
    if not result:
        import os
        env_providers = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        for provider, env_var in env_providers.items():
            if os.environ.get(env_var) and provider in KNOWN_MODELS:
                result[provider] = [
                    (model_id, info["display"], info["context"])
                    for model_id, info in KNOWN_MODELS[provider].items()
                ]

    return result


def model_command(provider: Optional[str] = None) -> None:
    """
    列出可用模型

    参考 opencode /models：
    - 从配置中读取已配置的 provider 和模型
    - 如果没有配置，显示已知模型列表
    - 支持按 provider 过滤

    Args:
        provider: 过滤特定 provider（可选）
    """
    try:
        from rich.table import Table
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()
    except ImportError:
        console = None

    models = _get_configured_models()

    if not models:
        # 显示所有已知模型（作为参考）
        if console:
            console.print(Panel(
                "[yellow]No API providers configured.[/yellow]\n\n"
                "Configure a provider first:\n"
                "  grassflow config api-key <provider> <key>\n\n"
                "Example:\n"
                "  grassflow config api-key openai sk-xxx\n"
                "  grassflow config api-key deepseek sk-xxx\n\n"
                "Then run 'grassflow models' again.",
                title="No Models Available",
                border_style="yellow"
            ))
            console.print()
            console.print("[bold]Available providers and models (for reference):[/bold]")
            console.print()
        else:
            display.print_info("No API providers configured.")
            display.print_info("Use 'grassflow config api-key <provider> <key>' to configure.")
            print()

        # 显示所有已知模型作为参考
        models = {}
        for pname, pmodels in KNOWN_MODELS.items():
            if provider is None or provider == pname:
                models[pname] = [
                    (mid, info["display"], info["context"])
                    for mid, info in pmodels.items()
                ]

    # 过滤
    if provider:
        if provider in models:
            models = {provider: models[provider]}
        else:
            if console:
                console.print(f"[yellow]Provider '{provider}' not found in configuration[/yellow]")
            else:
                display.print_info(f"Provider '{provider}' not found in configuration")
            return

    if console:
        for pname, pmodels in models.items():
            # Provider 标题
            provider_title = f"Provider: [bold cyan]{pname}[/bold cyan]"
            if pname in KNOWN_MODELS:
                is_configured = _is_provider_configured(pname)
            else:
                is_configured = True

            if not is_configured:
                provider_title += " [dim](reference only - not configured)[/dim]"

            console.print(Panel(provider_title, border_style="blue"))

            # 模型表格
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Model ID", style="cyan")
            table.add_column("Display Name", style="green")
            table.add_column("Context Window", style="yellow", justify="right")

            for model_id, display_name, context in pmodels:
                ctx_str = f"{context:,}" if context else "unknown"
                table.add_row(model_id, display_name, ctx_str)

            console.print(table)
            console.print()
    else:
        # 无 Rich 降级
        for pname, pmodels in models.items():
            print(f"Provider: {pname}")
            print("-" * 40)
            for model_id, display_name, context in pmodels:
                ctx_str = f" ({context:,} tokens)" if context else ""
                print(f"  {model_id} - {display_name}{ctx_str}")
            print()

    # 提示默认模型
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        default_model = config.llm.default_model
        default_provider = config.llm.default_provider

        if console:
            console.print(
                f"[dim]Default: {default_provider}/{default_model}[/dim]"
            )
            console.print("[dim]Use 'grassflow config set llm.default_model <model>' to change[/dim]")
        else:
            print(f"Default: {default_provider}/{default_model}")
            print("Use 'grassflow config set llm.default_model <model>' to change")
    except Exception:
        pass


def _is_provider_configured(provider_name: str) -> bool:
    """检查 provider 是否已配置（有 API key）"""
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        if provider_name in config.provider:
            return bool(config.provider[provider_name].options.apiKey)
        return False
    except Exception:
        return False

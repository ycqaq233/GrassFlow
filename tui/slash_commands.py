"""
GrassFlow 斜杠命令系统 — 声明式命令注册与分发

从 tui.repl 中提取，参考 hermes 的 CommandDef + COMMAND_REGISTRY 设计。
所有命令处理函数通过 repl_instance 参数访问 GrassFlowREPL 实例。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.completion import PathCompleter


# ---------------------------------------------------------------------------
# 解析推理力度（参考 hermes_constants.parse_reasoning_effort）
# ---------------------------------------------------------------------------

VALID_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")


def parse_reasoning_effort(effort: str) -> dict | None:
    """解析推理力度级别为配置字典。

    有效级别: "on", "off", "low", "medium", "high", "xhigh", "show".
    返回 None 表示输入为空或无法识别。
    返回 {"enabled": False} 对应 "off"。
    返回 {"enabled": True, "effort": <level>} 对应有效力度级别。
    """
    if not effort or not effort.strip():
        return None
    effort = effort.strip().lower()
    if effort in ("off",):
        return {"enabled": False}
    if effort in ("on",):
        return {"enabled": True, "effort": "medium"}
    if effort in VALID_REASONING_EFFORTS:
        return {"enabled": True, "effort": effort}
    return None


# ---------------------------------------------------------------------------
# CommandDef dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CommandDef:
    """单个斜杠命令的定义"""

    name: str           # "model"
    description: str    # "切换模型"
    category: str       # "Configuration"
    aliases: tuple      # ("mo",)
    args_hint: str      # "[provider:model]"
    handler_name: str   # "_cmd_model"
    visible: bool = True
    subcommands: tuple = ()


# ---------------------------------------------------------------------------
# 命令处理函数（独立于 GrassFlowREPL 类）
# ---------------------------------------------------------------------------

def _cmd_help(repl, args: List[str]) -> None:
    """显示帮助"""
    lines = [
        "",
        "  Available commands:",
    ]
    for cmd_def in command_registry.all_commands():
        if not cmd_def.visible:
            continue
        name = cmd_def.name
        desc = cmd_def.description
        args_hint = cmd_def.args_hint
        if args_hint:
            lines.append(f"    /{name:<14} {args_hint:<22} —  {desc}")
        else:
            lines.append(f"    /{name:<14} —  {desc}")
        if cmd_def.aliases:
            alias_str = ", ".join(f"/{a}" for a in cmd_def.aliases)
            lines.append(f"                   aliases: {alias_str}")

    lines.extend([
        "",
        "  Keyboard shortcuts:",
        "    Enter           Submit input",
        "    Alt+Enter       New line (multi-line input)",
        "    Ctrl+C          Interrupt / Exit",
        "    Ctrl+D          EOF / Exit (empty input)",
        "    Ctrl+L          Clear screen",
        "    Tab             Complete command / file path",
        "    Ctrl+X C        Compact context",
        "    Ctrl+X N        New session",
        "    Ctrl+X L        List sessions",
        "    Ctrl+X U        Undo",
        "    Ctrl+X R        Redo",
        "    Ctrl+X Q        Exit",
        "    Ctrl+X M        List models",
        "    Ctrl+P          Toggle permission mode (ask/approve)",
        "    Ctrl+T          Toggle thinking display (collapsed/expanded)",
        "",
    ])

    repl.add_output("\n".join(lines), role="system")


def _cmd_model(repl, args: List[str]) -> None:
    """切换模型"""
    from tui.layout import DEFAULT_MODEL

    if not args:
        current = repl.session.metadata.get("model", DEFAULT_MODEL) if repl.session else DEFAULT_MODEL
        repl.add_output(f"Current model: {current}\nUsage: /model <model_name>", role="system")
        return

    model_name = args[0]
    if repl.session:
        repl.session.metadata["model"] = model_name
    repl.add_output(f"Model switched to: {model_name}", role="system")


def _cmd_list_models(repl, args: List[str]) -> None:
    """列出可用模型（从 Provider API 动态发现，失败时 fallback 到配置）"""
    from tui.config_integration import load_config_readonly

    use_api = "--api" in args or "-a" in args
    force_config = "--config" in args or "-c" in args

    try:
        config = load_config_readonly()
        lines = ["", "  Available models:"]

        discovered_any = False

        # 尝试从 Provider API 发现模型
        if not force_config:
            try:
                import asyncio as _aio
                from core.model_discovery import discover_all_models

                # 如果在事件循环中，用同步包装
                try:
                    loop = _aio.get_running_loop()
                    # 已在事件循环中，用 run_in_executor 或创建新 loop
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(
                            _aio.run,
                            discover_all_models(config, timeout=10.0),
                        )
                        discovered = future.result(timeout=15.0)
                except RuntimeError:
                    # 没有运行中的事件循环
                    discovered = _aio.run(discover_all_models(config, timeout=10.0))

                if discovered and any(models for models in discovered.values()):
                    discovered_any = True
                    for provider_name, models in discovered.items():
                        lines.append(f"\n  [{provider_name}] (API discovery)")
                        if not models:
                            lines.append("    (no models discovered)")
                            continue
                        for m in models:
                            cap_parts = []
                            if m.context_window:
                                ctx_k = m.context_window // 1024
                                cap_parts.append(f"ctx:{ctx_k}k")
                            if m.max_output:
                                out_k = m.max_output // 1024
                                cap_parts.append(f"out:{out_k}k")
                            if m.vision:
                                cap_parts.append("vision")
                            if m.reasoning:
                                cap_parts.append("reasoning")
                            cap_str = f"  [{', '.join(cap_parts)}]" if cap_parts else ""
                            lines.append(f"    - {m.name}{cap_str}")
            except Exception as e:
                logger.debug(f"Model discovery failed, falling back to config: {e}")

        # Fallback: 从配置文件读取
        if not discovered_any:
            for provider_name, provider_config in config.provider.items():
                lines.append(f"\n  [{provider_name}] (config)")
                if provider_config.models:
                    for model_name, model_info in provider_config.models.items():
                        name = model_info.name or model_name
                        # 尝试从已知能力表补充信息
                        cap_parts = []
                        try:
                            from core.model_discovery import KNOWN_MODEL_CAPABILITIES
                            caps = KNOWN_MODEL_CAPABILITIES.get(name, {})
                            if caps.get("context_window"):
                                ctx_k = caps["context_window"] // 1024
                                cap_parts.append(f"ctx:{ctx_k}k")
                            if caps.get("max_output"):
                                out_k = caps["max_output"] // 1024
                                cap_parts.append(f"out:{out_k}k")
                            if caps.get("vision"):
                                cap_parts.append("vision")
                            if caps.get("reasoning"):
                                cap_parts.append("reasoning")
                        except ImportError:
                            pass
                        cap_str = f"  [{', '.join(cap_parts)}]" if cap_parts else ""
                        lines.append(f"    - {name}{cap_str}")
                else:
                    lines.append("    (no models configured)")

        lines.append("")
        lines.append("  Flags: --api  Force API discovery | --config  Config only")
        repl.add_output("\n".join(lines), role="system")
    except Exception as e:
        repl.add_output(f"Failed to list models: {e}", role="error")


def _cmd_new_session(repl, args: List[str]) -> None:
    """创建新会话"""
    _handle_new_session(repl)


def _cmd_clear(repl, args: List[str]) -> None:
    """清空会话"""
    repl.clear_output()
    repl.add_output("Screen cleared.", role="system")


def _cmd_compact(repl, args: List[str]) -> None:
    """手动压缩上下文"""
    _handle_compact(repl)


def _cmd_compress(repl, args: List[str]) -> None:
    """手动压缩上下文（别名）"""
    _handle_compact(repl)


def _cmd_list_sessions(repl, args: List[str]) -> None:
    """列出历史会话"""
    _handle_list_sessions(repl)


def _cmd_init(repl, args: List[str]) -> None:
    """分析项目创建 AGENTS.md"""
    repl.add_output(
        "Run /init to analyze the current project and create an AGENTS.md file.\n"
        "This feature requires the init skill or an initialized agent.",
        role="system",
    )


def _cmd_undo(repl, args: List[str]) -> None:
    """撤销"""
    _handle_undo(repl)


def _cmd_redo(repl, args: List[str]) -> None:
    """重做"""
    _handle_redo(repl)


def _cmd_exit(repl, args: List[str]) -> None:
    """退出

    职责划分：
    - 本函数只负责设置 _should_exit 标志
    - app.exit() 由 _process_user_input 统一调用
    - 避免与 hermes 模式的退出流程冲突（双重 app.exit 导致 "Return value already set"）
    """
    repl._should_exit = True


def _cmd_theme(repl, args: List[str]) -> None:
    """切换主题"""
    if not args:
        themes = ", ".join(repl.theme_names)
        current = repl._theme.name
        repl.add_output(f"Current theme: {current}\nAvailable: {themes}\nUsage: /theme <name>", role="system")
        return

    name = args[0].lower()
    if repl.switch_theme(name):
        repl.add_output(f"Theme switched to: {name}", role="system")
    else:
        available = ", ".join(repl.theme_names)
        repl.add_output(f"Unknown theme '{name}'. Available: {available}", role="error")


def _cmd_provider(repl, args: List[str]) -> None:
    """切换 provider"""
    from tui.config_integration import load_config_readonly

    if not args:
        try:
            config = load_config_readonly()
            default = config.llm.default_provider
            repl.add_output(f"Current provider: {default}\nUsage: /provider <provider_name>", role="system")
        except Exception:
            repl.add_output(f"Usage: /provider <provider_name>", role="system")
        return

    name = args[0]
    # Persist to session metadata
    if repl.session:
        repl.session.metadata["provider"] = name
    # Persist to config
    try:
        from tui.config_integration import config_manager
        config = config_manager.load_config()
        config.llm.default_provider = name
        config_manager.save_config(config)
    except Exception as e:
        repl.add_output(f"Failed to persist provider change: {e}", role="error")
        return
    repl.add_output(f"Provider set to: {name}", role="system")


def _cmd_run(repl, args: List[str]) -> None:
    """执行工作流"""
    if not args:
        repl.add_output("Usage: /run <workflow_file>", role="error")
        return
    repl.add_output(f"Executing workflow: {args[0]}", role="system")


def _cmd_list_workflows(repl, args: List[str]) -> None:
    """列出工作流"""
    try:
        from core.storage import workflow_storage
        workflows = workflow_storage.list()
        if not workflows:
            repl.add_output("No workflows found.", role="system")
            return
        lines = ["  Saved workflows:"]
        for wf in sorted(workflows):
            lines.append(f"    - {wf}")
        repl.add_output("\n".join(lines), role="system")
    except ImportError:
        repl.add_output("Storage module not available.", role="system")


def _cmd_history(repl, args: List[str]) -> None:
    """执行历史"""
    try:
        from core.db import execution_db
        try:
            limit = int(args[0]) if args else 10
        except (ValueError, IndexError):
            repl.add_output("Usage: /history [limit]  (limit must be a number)", role="error")
            return
        executions = execution_db.list_executions(limit=limit)
        if not executions:
            repl.add_output("No execution history found.", role="system")
            return
        lines = ["  Execution history:"]
        for ex in executions:
            status = ex.get("status", "unknown")
            name = ex.get("workflow_name", "?")
            dur = ex.get("total_duration_ms")
            dur_s = f"{dur}ms" if dur else "N/A"
            lines.append(f"    [{ex.get('id', '?')}] {name} - {status} ({dur_s})")
        repl.add_output("\n".join(lines), role="system")
    except ImportError:
        repl.add_output("Database module not available.", role="system")


def _cmd_validate(repl, args: List[str]) -> None:
    """验证工作流"""
    if not args:
        repl.add_output("Usage: /validate <workflow_file>", role="error")
        return
    repl.add_output(f"Validating: {args[0]}", role="system")


def _cmd_templates(repl, args: List[str]) -> None:
    """列出模板"""
    try:
        from tui.templates import get_templates
        templates = get_templates()
        if not templates:
            repl.add_output("No templates available.", role="system")
            return
        lines = ["  Available templates:"]
        for t in templates:
            lines.append(f"    - {t['name']}: {t['description']} ({t['agent_count']} agents)")
        repl.add_output("\n".join(lines), role="system")
    except ImportError:
        repl.add_output("Templates module not available.", role="system")


def _cmd_config(repl, args: List[str]) -> None:
    """查看配置"""
    from tui.config_integration import load_config_readonly

    try:
        config = load_config_readonly()
        info = {
            "provider": config.llm.default_provider,
            "model": config.llm.default_model,
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
            "timeout": config.llm.timeout,
        }
        lines = ["  Current configuration:"]
        for k, v in info.items():
            lines.append(f"    {k}: {v}")
        repl.add_output("\n".join(lines), role="system")
    except Exception as e:
        repl.add_output(f"Config error: {e}", role="error")


def _cmd_stats(repl, args: List[str]) -> None:
    """显示上下文统计"""
    lines = [
        "  Context statistics:",
        f"    Output entries: {len(repl.output)}",
        f"    Conversation messages: {len(repl._conversation_history)}",
        f"    Estimated tokens: {repl._token_count}",
        f"    Token limit: {repl._token_limit}",
        f"    API calls: {repl._api_call_count}",
        f"    Last latency: {repl._last_latency_ms}ms",
    ]
    # Compressor stats
    if repl._compressor:
        from tui.context_compressor import estimate_messages_tokens, ChatMessage
        msgs = [ChatMessage(role=m["role"], content=m.get("content", "")) for m in repl._conversation_history]
        est = estimate_messages_tokens(msgs)
        lines.append(f"    Compressor: active (compactions: {repl._compressor.compaction_count})")
        lines.append(f"    Context tokens (estimated): {est}")
        threshold = repl._compressor.compaction_threshold
        lines.append(f"    Compress threshold: {threshold}")
    else:
        lines.append("    Compressor: not initialized")
    if repl.session:
        lines.append(f"    Session: {repl.session.id[:16]}")
        lines.append(f"    Session status: {repl.session.status.value}")
        lines.append(f"    Session messages: {repl.session.message_count}")
    repl.add_output("\n".join(lines), role="system")


def _cmd_status(repl, args: List[str]) -> None:
    """显示当前会话状态"""
    _cmd_stats(repl, args)


def _cmd_think(repl, args: List[str]) -> None:
    """切换/设置思考模式"""
    if not args:
        # 显示当前 thinking 状态
        thinking = repl.session.metadata.get("thinking", {}) if repl.session else {}
        enabled = thinking.get("enabled", False)
        effort = thinking.get("effort", "medium")
        display = thinking.get("display", "collapsed")
        status = "ON" if enabled else "OFF"
        repl.add_output(
            f"Thinking mode: {status}\n"
            f"Effort: {effort}\n"
            f"Display: {display}\n"
            f"Usage: /think [on|off|low|medium|high|xhigh|show|full|collapsed]",
            role="system",
        )
        return

    arg = args[0].lower()

    if arg == "show":
        thinking = repl.session.metadata.get("thinking", {}) if repl.session else {}
        enabled = thinking.get("enabled", False)
        effort = thinking.get("effort", "medium")
        display = thinking.get("display", "collapsed")
        repl.add_output(
            f"  Thinking configuration:\n"
            f"    enabled: {enabled}\n"
            f"    effort: {effort}\n"
            f"    display: {display}",
            role="system",
        )
        return

    # Shortcut: /think full or /think collapsed (without "display" prefix)
    if arg in ("collapsed", "full"):
        if repl.session:
            thinking = repl.session.metadata.get("thinking", {})
            thinking["display"] = arg
            repl.session.metadata["thinking"] = thinking
        repl.add_output(f"Thinking display mode: {arg}", role="system")
        return


    if arg == "display":
        if len(args) < 2:
            repl.add_output("Usage: /think display [collapsed|full]", role="error")
            return
        mode = args[1].lower()
        if mode not in ("collapsed", "full"):
            repl.add_output("Invalid display mode. Use: collapsed, full", role="error")
            return
        if repl.session:
            thinking = repl.session.metadata.get("thinking", {})
            thinking["display"] = mode
            repl.session.metadata["thinking"] = thinking
        repl.add_output(f"Thinking display mode: {mode}", role="system")
        return

    parsed = parse_reasoning_effort(arg)
    if parsed is None:
        repl.add_output(
            f"Unknown option: '{arg}'\n"
            f"Usage: /think [on|off|low|medium|high|xhigh|show|full|collapsed]",
            role="error",
        )
        return

    if repl.session:
        # Preserve display setting when changing effort
        existing_display = repl.session.metadata.get("thinking", {}).get("display", "collapsed")
        parsed["display"] = existing_display
        repl.session.metadata["thinking"] = parsed

    enabled = parsed.get("enabled", False)
    if enabled:
        effort = parsed.get("effort", "medium")
        # Check if current model supports reasoning
        current_model = ""
        try:
            if repl._agent and repl._agent._agent_loop:
                current_model = repl._agent._agent_loop._model_name
        except Exception:
            pass

        if current_model and "v4" not in current_model.lower() and "reasoner" not in current_model.lower():
            repl.add_output(
                f"Thinking mode: ON (effort: {effort})\n"
                f"\033[33m  Warning: Current model '{current_model}' may not support reasoning.\n"
                f"  Switch to 'deepseek-v4-flash' or 'deepseek-v4-pro' with: /model deepseek-v4-flash\n"
                f"  Both V4 models support thinking and non-thinking modes.\033[0m",
                role="system",
            )
        else:
            repl.add_output(f"Thinking mode: ON (effort: {effort})", role="system")
    else:
        repl.add_output("Thinking mode: OFF", role="system")


def _cmd_resume(repl, args: List[str]) -> None:
    """恢复历史会话"""
    _handle_list_sessions(repl)


def _cmd_retry(repl, args: List[str]) -> None:
    """重试上一条消息 — 直接重发，不依赖 fall-through 机制"""
    # Find the last user message in output history
    last_user_text = None
    for entry in reversed(repl.output):
        if entry.role == "user":
            last_user_text = entry.text
            break
    if not last_user_text:
        repl.add_output("No user message to retry.", role="error")
        return
    repl.add_output(f"Retrying: {last_user_text[:100]}...", role="system")
    # Directly invoke agent with the last user message
    repl._handle_agent_message(last_user_text)


def _cmd_fork(repl, args: List[str]) -> None:
    """分叉当前会话"""
    repl.add_output("Fork not yet implemented.", role="system")


def _cmd_title(repl, args: List[str]) -> None:
    """设置会话标题"""
    if not args:
        title = repl.session.title if repl.session and repl.session.title else "(untitled)"
        repl.add_output(f"Session title: {title}\nUsage: /title <name>", role="system")
        return

    new_title = " ".join(args)
    if repl.session:
        repl.session.title = new_title
    repl.add_output(f"Session title set to: {new_title}", role="system")


def _cmd_agent(repl, args: List[str]) -> None:
    """切换/列出 Agent"""
    from tui.layout import DEFAULT_MODEL

    model = repl.session.metadata.get("model", DEFAULT_MODEL) if repl.session else DEFAULT_MODEL
    provider = repl.session.metadata.get("provider", "default") if repl.session else "default"
    lines = [
        "  Current agent:",
        f"    model: {model}",
        f"    provider: {provider}",
    ]
    repl.add_output("\n".join(lines), role="system")


def _cmd_mcp(repl, args: List[str]) -> None:
    """MCP 服务器管理"""
    # Show runtime state if available
    mcp_mgr = getattr(getattr(repl, '_agent', None), '_mcp_manager', None)
    if mcp_mgr:
        try:
            summary = mcp_mgr.get_tools_summary()
            repl.add_output(summary, role="system")
            return
        except Exception:
            pass
    # Fallback to config display with "not started" status
    try:
        from tui.config_integration import get_mcp_servers
        mcp_servers = get_mcp_servers()
        if mcp_servers:
            lines = ["  MCP servers:"]
            for name, srv in mcp_servers.items():
                transport = "stdio" if "command" in srv else ("http" if "url" in srv else "auto")
                lines.append(f"    ⏳ {name} ({transport}) - not started")
            lines.append("")
            lines.append(f"  {len(mcp_servers)} servers configured (agent not initialized)")
            repl.add_output("\n".join(lines), role="system")
        else:
            repl.add_output("  No MCP servers configured.", role="system")
    except Exception:
        repl.add_output("  MCP status not available (config module error).", role="system")


def _cmd_skills(repl, args: List[str]) -> None:
    """浏览技能列表"""
    try:
        from tui.skills_system import get_skills_manager
        skills_mgr = get_skills_manager()
        summary = skills_mgr.get_skills_summary()
        repl.add_output(summary, role="system")
    except Exception as e:
        repl.add_output(f"Skills system error: {e}", role="error")


def _cmd_skill_load(repl, args: List[str]) -> None:
    """Load a skill by name and inject its content into conversation.

    This is the generic handler invoked by dynamically registered /skill-name commands.
    The first element of ``args`` is the skill name (injected by the closure that
    wraps each dynamically registered command). Any remaining elements are joined
    as the user's text after the skill name.
    """
    if not args:
        repl.add_output("Usage: /<skill-name> [user text]", role="error")
        return

    skill_name = args[0]
    user_text = " ".join(args[1:]).strip() if len(args) > 1 else ""
    try:
        from tui.skills_system import get_skills_manager
        skills_mgr = get_skills_manager()
        skill = skills_mgr.get_skill(skill_name)

        if not skill:
            repl.add_output(f"Skill not found: {skill_name}", role="error")
            return

        # Inject skill content as a system message into conversation history
        skill_message = f"[Skill Loaded: {skill.name}]\n\n{skill.content}"
        repl._conversation_history.append({
            "role": "system",
            "content": skill_message,
        })

        repl.add_output(f"✅ Skill loaded: {skill.name}", role="system")

        if user_text:
            # User provided text after the skill name — send it as a user message
            repl._handle_agent_message(user_text)
        else:
            # No user text — just confirm the skill load to the agent
            if repl._agent.is_initialized:
                repl._handle_agent_message(
                    f"I've loaded the '{skill.name}' skill. "
                    f"Please read its instructions and confirm you understand what you can now do."
                )
    except Exception as e:
        repl.add_output(f"Failed to load skill: {e}", role="error")


def register_skill_commands() -> None:
    """Dynamically register a /skill-name command for every discovered skill.

    Called once during REPL startup (after SkillsManager has scanned).
    Each registered command maps to a closure that loads the corresponding
    skill content into the conversation history.
    """
    try:
        from tui.skills_system import get_skills_manager
        skills_mgr = get_skills_manager()
        skills = skills_mgr.scan()

        for skill in skills:
            # Never overwrite a built-in command (e.g. /skills, /help)
            if command_registry.get(skill.name) is not None:
                continue

            desc = skill.description or skill.name
            cmd_def = CommandDef(
                name=skill.name,
                description=f"Load skill: {desc}",
                category="Skills",
                aliases=(),
                args_hint="",
                handler_name=f"_cmd_skill_load:{skill.name}",
                visible=True,
            )
            command_registry.register(cmd_def)
            # Register a closure so each skill name maps to the right load call.
            # Pass the skill name as the first element and any user-provided
            # arguments (text after the skill name) as subsequent elements.
            command_registry.register_handler(
                f"_cmd_skill_load:{skill.name}",
                lambda repl, _args, _name=skill.name: _cmd_skill_load(repl, [_name] + _args),
            )
    except Exception as e:
        logger.debug("Failed to register skill commands: %s", e)


def _cmd_copy(repl, args: List[str]) -> None:
    """复制最后助手回复到剪贴板"""
    last_assistant_msg = None
    for entry in reversed(repl.output):
        if hasattr(entry, "role") and entry.role == "assistant":
            last_assistant_msg = entry
            break

    if not last_assistant_msg:
        repl.add_output("No assistant response to copy.", role="error")
        return

    content = last_assistant_msg.text if hasattr(last_assistant_msg, "text") else str(last_assistant_msg)

    # 尝试多种剪贴板方案
    copied = False

    # 方案 1: pyperclip
    if not copied:
        try:
            import pyperclip
            pyperclip.copy(content)
            copied = True
        except (ImportError, Exception):
            pass

    # 方案 2: subprocess (Windows)
    if not copied:
        try:
            import subprocess
            process = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
                shell=True,
            )
            process.communicate(content.encode("utf-16le"))
            copied = True
        except Exception:
            pass

    if copied:
        preview = content[:80].replace("\n", " ")
        repl.add_output(f"Copied to clipboard: {preview}...", role="system")
    else:
        repl.add_output(
            "Failed to copy. Install pyperclip: pip install pyperclip",
            role="error",
        )


def _cmd_usage(repl, args: List[str]) -> None:
    """显示 token 用量"""
    lines = [
        "  Token usage:",
        f"    Current session: {len(repl.output)} entries",
        f"    Conversation messages: {len(repl._conversation_history)}",
        f"    Estimated tokens: {repl._token_count}",
        f"    Token limit: {repl._token_limit}",
        f"    API calls: {repl._api_call_count}",
        f"    Last latency: {repl._last_latency_ms}ms",
    ]
    if repl._compressor:
        from tui.context_compressor import estimate_messages_tokens, ChatMessage
        msgs = [ChatMessage(role=m["role"], content=m.get("content", "")) for m in repl._conversation_history]
        est = estimate_messages_tokens(msgs)
        lines.append(f"    Context tokens (estimated): {est}")
        lines.append(f"    Compressions: {repl._compressor.compaction_count}")
    if repl.session:
        lines.append(f"    Session ID: {repl.session.id[:16]}")
        lines.append(f"    Session status: {repl.session.status.value}")
        lines.append(f"    Session messages: {repl.session.message_count}")
    usage_pct = (repl._token_count / repl._token_limit * 100) if repl._token_limit else 0
    lines.append(f"    Usage: {usage_pct:.1f}%")
    repl.add_output("\n".join(lines), role="system")


def _cmd_version(repl, args: List[str]) -> None:
    """显示版本信息"""
    version = "0.1.0"
    try:
        # 尝试从项目根目录读取版本
        import pathlib
        setup_py = pathlib.Path(__file__).parent.parent / "setup.py"
        if setup_py.exists():
            content = setup_py.read_text(encoding="utf-8")
            import re
            match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
            if match:
                version = match.group(1)
    except Exception:
        pass

    repl.add_output(
        f"  GrassFlow v{version}\n"
        f"  Visual multi-agent orchestration platform",
        role="system",
    )


def _cmd_connect(repl, args: List[str]) -> None:
    """连接 Provider"""
    repl.add_output(
        "Provider connection not yet implemented.\n"
        "Use /config to view current configuration.",
        role="system",
    )


def _cmd_yolo(repl, args: List[str]) -> None:
    """切换 YOLO 模式"""
    current = repl.session.metadata.get("yolo", False) if repl.session else False
    new_val = not current
    if repl.session:
        repl.session.metadata["yolo"] = new_val
    status = "ON" if new_val else "OFF"
    repl.add_output(f"YOLO mode: {status}", role="system")


def _cmd_perm(repl, args: List[str]) -> None:
    """查看/切换权限模式"""
    valid_modes = ("ask", "approve")
    current = getattr(repl, '_permission_mode', 'ask')

    if not args:
        repl.add_output(
            f"Permission mode: {current}\n"
            f"Usage: /perm [ask|approve]\n"
            f"  ask     — Ask before executing tools (default)\n"
            f"  approve — Auto-approve tool execution\n"
            f"  Ctrl+P  — Toggle between modes",
            role="system",
        )
        return

    arg = args[0].lower()
    if arg not in valid_modes:
        repl.add_output(f"Unknown permission mode: '{arg}'. Valid: ask, approve", role="error")
        return

    repl._permission_mode = arg
    if arg == "approve":
        repl.add_output("Permission mode: APPROVE (tools will execute automatically)", role="system")
    else:
        repl.add_output("Permission mode: ASK (tools require approval before execution)", role="system")


def _cmd_tools(repl, args: List[str]) -> None:
    """切换工具调用显示模式（compact / verbose）"""
    if not args:
        mode = "verbose" if repl._tool_verbose else "compact"
        repl.add_output(
            f"Tool display: {mode}\n"
            f"Usage: /tools [compact|verbose|on|off|toggle]",
            role="system",
        )
        return

    arg = args[0].lower()
    if arg in ("compact", "off"):
        repl._tool_verbose = False
        repl.add_output("Tool display: compact (summary lines, truncated output)", role="system")
    elif arg in ("verbose", "on"):
        repl._tool_verbose = True
        repl.add_output("Tool display: verbose (full args and output)", role="system")
    elif arg == "toggle":
        repl._tool_verbose = not repl._tool_verbose
        mode = "verbose" if repl._tool_verbose else "compact"
        repl.add_output(f"Tool display: {mode}", role="system")
    else:
        repl.add_output(f"Unknown option: '{arg}'. Use: compact|verbose|on|off|toggle", role="error")


# ---------------------------------------------------------------------------
# 操作处理函数
# ---------------------------------------------------------------------------

def _handle_compact(repl) -> None:
    """压缩上下文（手动触发）"""
    import asyncio

    repl._init_compressor()
    if not repl._compressor:
        repl.add_output("Context compressor not available (agent loop not initialized).", role="error")
        return

    if len(repl._conversation_history) < 2:
        repl.add_output("Not enough messages to compress.", role="system")
        return

    from tui.context_compressor import ChatMessage, SUMMARY_PREFIX, SUMMARY_END_MARKER

    messages = [ChatMessage(role=m["role"], content=m.get("content", "")) for m in repl._conversation_history]
    original_tokens = repl._compressor.estimate_tokens(messages)

    repl.add_output(f"Compressing context ({original_tokens} estimated tokens)...", role="system")

    async def _do_compress():
        try:
            result = await repl._compressor.compact(messages, force=True)
            if result.tokens_saved <= 0:
                repl.add_output("Nothing to compress.", role="system")
                return

            # Rebuild history into a new list (atomic swap avoids race condition)
            rebuilt = []
            rebuilt.append(ChatMessage(
                role="system",
                content=f"{SUMMARY_PREFIX}\n\n{result.summary}\n\n{SUMMARY_END_MARKER}",
            ))
            rebuilt.extend(result.tail_messages)
            rebuilt = repl._compressor._sanitize_tool_pairs(rebuilt)

            new_history = []
            for msg in rebuilt:
                entry = {"role": msg.role, "content": msg.content}
                if msg.tool_call_id:
                    entry["tool_call_id"] = msg.tool_call_id
                if msg.name:
                    entry["name"] = msg.name
                if msg.tool_calls:
                    entry["tool_calls"] = msg.tool_calls
                new_history.append(entry)

            # Atomic swap: replace the list reference instead of clear + append
            repl._conversation_history.clear()
            repl._conversation_history.extend(new_history)

            repl.add_output(
                f"Context compressed: {result.original_tokens} -> {result.compacted_tokens} tokens "
                f"(saved {result.tokens_saved} tokens, {result.tokens_saved/result.original_tokens*100:.1f}%)",
                role="system",
            )
        except Exception as e:
            logger.error("Context compression failed: %s", e)
            repl.add_output(f"Context compression failed: {e}", role="error")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_compress())
    except RuntimeError:
        asyncio.run(_do_compress())


def _handle_new_session(repl) -> None:
    """创建新会话"""
    from tui.layout import DEFAULT_MODEL, DEFAULT_PROVIDER

    if repl._enable_session and repl.session_mgr:
        try:
            old_id = repl.session.id if repl.session else None

            directory = os.getcwd()
            from tui.layout import DEFAULT_MODEL, DEFAULT_PROVIDER
            repl.session = repl.session_mgr.create_session(
                title=f"REPL Session",
                directory=directory,
                metadata={
                    "model": repl.session.metadata.get("model", DEFAULT_MODEL) if repl.session else DEFAULT_MODEL,
                    "provider": repl.session.metadata.get("provider", DEFAULT_PROVIDER) if repl.session else DEFAULT_PROVIDER,
                    "thinking": {"enabled": True, "effort": "medium", "display": "collapsed"},
                },
            )
            repl.clear_output()
            repl._reset_stats()
            repl._compressor = None  # Reset compressor for new session
            repl.add_output(
                f"New session created: {repl.session.id[:12]}",
                role="system",
            )
            if old_id:
                repl.add_output(f"Previous session: {old_id[:12]}", role="system")
        except Exception as e:
            repl.add_output(f"Failed to create session: {e}", role="error")
    else:
        repl.clear_output()
        repl._reset_stats()
        repl.add_output("New session started (session manager disabled).", role="system")


def _handle_list_sessions(repl) -> None:
    """列出会话"""
    if not repl._enable_session or not repl.session_mgr:
        repl.add_output("Session manager is disabled.", role="system")
        return

    try:
        sessions = repl.session_mgr.list_sessions(limit=20)
        if not sessions:
            repl.add_output("No saved sessions found.", role="system")
            return

        lines = ["  Recent sessions:"]
        for s in sessions:
            is_current = repl.session and s.id == repl.session.id
            marker = " *" if is_current else "  "
            title = s.title or "(untitled)"
            status = s.status.value
            updated = s.updated_at.strftime("%m/%d %H:%M") if s.updated_at else "?"
            lines.append(
                f"  {marker} [{s.id[:8]}] {title} — {status} ({updated}) — {s.message_count} msgs"
            )

        repl.add_output("\n".join(lines), role="system")
    except Exception as e:
        repl.add_output(f"Failed to list sessions: {e}", role="error")


def _handle_undo(repl) -> None:
    """撤销上次操作"""
    if not repl.output:
        repl.add_output("Nothing to undo.", role="system")
        return
    # Skip system messages at the end
    idx = len(repl.output) - 1
    while idx >= 0 and repl.output[idx].role == "system":
        idx -= 1
    if idx < 0:
        repl.add_output("Nothing to undo.", role="system")
        return
    entry = repl.output.pop(idx)
    repl._undo_stack.append(entry)
    # Clear redo stack — new undo invalidates redo history
    repl._redo_stack.clear()
    repl.add_output(f"Undone: {entry.text[:80]}...", role="system")


def _handle_redo(repl) -> None:
    """重做 — 从 _redo_stack 恢复"""
    if not repl._redo_stack:
        repl.add_output("Nothing to redo.", role="system")
        return
    # 移除 undo 产生的 'Undone:' 反馈消息，避免残留污染输出
    for i in range(len(repl.output) - 1, -1, -1):
        if repl.output[i].role == "system" and repl.output[i].text.startswith("Undone:"):
            repl.output.pop(i)
            break
    entry = repl._redo_stack.pop()
    repl.add_output(entry.text, role=entry.role, metadata=getattr(entry, 'metadata', None))


def _handle_list_models(repl) -> None:
    """Ctrl+X M：列出模型"""
    _cmd_list_models(repl, [])


# ---------------------------------------------------------------------------
# COMMAND_REGISTRY — 命令注册表
# ---------------------------------------------------------------------------

COMMAND_REGISTRY: List[CommandDef] = [
    # Session
    CommandDef(
        name="help",
        description="显示帮助信息",
        category="Session",
        aliases=("h",),
        args_hint="",
        handler_name="_cmd_help",
    ),
    CommandDef(
        name="new",
        description="创建新会话",
        category="Session",
        aliases=(),
        args_hint="",
        handler_name="_cmd_new_session",
    ),
    CommandDef(
        name="clear",
        description="清空会话",
        category="Session",
        aliases=("cls",),
        args_hint="",
        handler_name="_cmd_clear",
    ),
    CommandDef(
        name="compact",
        description="手动压缩上下文",
        category="Session",
        aliases=("compress",),
        args_hint="",
        handler_name="_cmd_compact",
    ),
    CommandDef(
        name="undo",
        description="撤销上次操作",
        category="Session",
        aliases=(),
        args_hint="",
        handler_name="_cmd_undo",
    ),
    CommandDef(
        name="redo",
        description="重做",
        category="Session",
        aliases=(),
        args_hint="",
        handler_name="_cmd_redo",
    ),
    CommandDef(
        name="exit",
        description="退出 REPL",
        category="Exit",
        aliases=("quit", "q"),
        args_hint="",
        handler_name="_cmd_exit",
    ),
    CommandDef(
        name="status",
        description="显示当前会话状态",
        category="Session",
        aliases=(),
        args_hint="",
        handler_name="_cmd_status",
    ),

    # Configuration
    CommandDef(
        name="model",
        description="切换模型",
        category="Configuration",
        aliases=(),
        args_hint="[model_name]",
        handler_name="_cmd_model",
    ),
    CommandDef(
        name="models",
        description="列出可用模型（支持 API 发现）",
        category="Configuration",
        aliases=(),
        args_hint="[--api|--config]",
        handler_name="_cmd_list_models",
    ),
    CommandDef(
        name="theme",
        description="切换主题",
        category="Configuration",
        aliases=(),
        args_hint="[name]",
        handler_name="_cmd_theme",
    ),
    CommandDef(
        name="provider",
        description="切换 provider",
        category="Configuration",
        aliases=(),
        args_hint="[provider_name]",
        handler_name="_cmd_provider",
    ),
    CommandDef(
        name="config",
        description="查看/修改配置",
        category="Configuration",
        aliases=(),
        args_hint="",
        handler_name="_cmd_config",
    ),

    # Workflow
    CommandDef(
        name="run",
        description="执行工作流文件",
        category="Workflow",
        aliases=(),
        args_hint="<workflow_file>",
        handler_name="_cmd_run",
    ),
    CommandDef(
        name="list",
        description="列出已保存的工作流",
        category="Workflow",
        aliases=("ls",),
        args_hint="",
        handler_name="_cmd_list_workflows",
    ),
    CommandDef(
        name="validate",
        description="验证工作流文件",
        category="Workflow",
        aliases=(),
        args_hint="<workflow_file>",
        handler_name="_cmd_validate",
    ),
    CommandDef(
        name="templates",
        description="列出可用模板",
        category="Workflow",
        aliases=(),
        args_hint="",
        handler_name="_cmd_templates",
    ),

    # Session (新增)
    CommandDef(
        name="resume",
        description="恢复历史会话",
        category="Session",
        aliases=("sessions",),
        args_hint="[session_id]",
        handler_name="_cmd_resume",
    ),
    CommandDef(
        name="retry",
        description="重试上一条消息",
        category="Session",
        aliases=(),
        args_hint="",
        handler_name="_cmd_retry",
    ),
    CommandDef(
        name="fork",
        description="分叉当前会话",
        category="Session",
        aliases=("branch",),
        args_hint="[name]",
        handler_name="_cmd_fork",
    ),
    CommandDef(
        name="title",
        description="设置会话标题",
        category="Session",
        aliases=(),
        args_hint="[name]",
        handler_name="_cmd_title",
    ),

    # Configuration (新增)
    CommandDef(
        name="think",
        description="切换/设置思考模式",
        category="Configuration",
        aliases=(),
        args_hint="[on|off|low|medium|high|xhigh|show|full|collapsed]",
        handler_name="_cmd_think",
    ),
    CommandDef(
        name="agent",
        description="切换/列出 Agent",
        category="Configuration",
        aliases=(),
        args_hint="",
        handler_name="_cmd_agent",
    ),
    CommandDef(
        name="mcp",
        description="MCP 服务器管理",
        category="Configuration",
        aliases=(),
        args_hint="",
        handler_name="_cmd_mcp",
    ),
    CommandDef(
        name="connect",
        description="连接 Provider",
        category="Configuration",
        aliases=(),
        args_hint="[provider]",
        handler_name="_cmd_connect",
    ),
    CommandDef(
        name="yolo",
        description="切换 YOLO 模式",
        category="Configuration",
        aliases=(),
        args_hint="[on|off|status]",
        handler_name="_cmd_yolo",
        subcommands=("on", "off", "status"),
    ),
    CommandDef(
        name="tools",
        description="切换工具调用显示模式",
        category="Configuration",
        aliases=(),
        args_hint="[compact|verbose|on|off|toggle]",
        handler_name="_cmd_tools",
    ),
    CommandDef(
        name="perm",
        description="查看/切换权限模式",
        category="Configuration",
        aliases=("permission",),
        args_hint="[ask|approve]",
        handler_name="_cmd_perm",
    ),

    # Info
    CommandDef(
        name="history",
        description="查看执行历史",
        category="Info",
        aliases=(),
        args_hint="[limit]",
        handler_name="_cmd_history",
    ),
    CommandDef(
        name="stats",
        description="显示上下文统计",
        category="Info",
        aliases=(),
        args_hint="",
        handler_name="_cmd_stats",
    ),
    CommandDef(
        name="init",
        description="分析项目创建 AGENTS.md",
        category="Info",
        aliases=(),
        args_hint="",
        handler_name="_cmd_init",
    ),
    CommandDef(
        name="skills",
        description="浏览技能列表",
        category="Info",
        aliases=(),
        args_hint="",
        handler_name="_cmd_skills",
    ),
    CommandDef(
        name="copy",
        description="复制最后助手回复",
        category="Info",
        aliases=(),
        args_hint="",
        handler_name="_cmd_copy",
    ),
    CommandDef(
        name="usage",
        description="显示 token 用量",
        category="Info",
        aliases=(),
        args_hint="",
        handler_name="_cmd_usage",
    ),
    CommandDef(
        name="version",
        description="显示版本信息",
        category="Info",
        aliases=("v",),
        args_hint="",
        handler_name="_cmd_version",
    ),
]


# ---------------------------------------------------------------------------
# Handler 映射表 — 将 handler_name 映射到实际函数
# ---------------------------------------------------------------------------

_HANDLER_MAP: Dict[str, Callable] = {
    "_cmd_help": _cmd_help,
    "_cmd_model": _cmd_model,
    "_cmd_list_models": _cmd_list_models,
    "_cmd_new_session": _cmd_new_session,
    "_cmd_clear": _cmd_clear,
    "_cmd_compact": _cmd_compact,
    "_cmd_compress": _cmd_compress,
    "_cmd_init": _cmd_init,
    "_cmd_undo": _cmd_undo,
    "_cmd_redo": _cmd_redo,
    "_cmd_exit": _cmd_exit,
    "_cmd_theme": _cmd_theme,
    "_cmd_provider": _cmd_provider,
    "_cmd_run": _cmd_run,
    "_cmd_list_workflows": _cmd_list_workflows,
    "_cmd_history": _cmd_history,
    "_cmd_validate": _cmd_validate,
    "_cmd_templates": _cmd_templates,
    "_cmd_config": _cmd_config,
    "_cmd_stats": _cmd_stats,
    "_cmd_status": _cmd_status,
    # 新增命令
    "_cmd_think": _cmd_think,
    "_cmd_resume": _cmd_resume,
    "_cmd_retry": _cmd_retry,
    "_cmd_fork": _cmd_fork,
    "_cmd_title": _cmd_title,
    "_cmd_agent": _cmd_agent,
    "_cmd_mcp": _cmd_mcp,
    "_cmd_skills": _cmd_skills,
    "_cmd_copy": _cmd_copy,
    "_cmd_usage": _cmd_usage,
    "_cmd_version": _cmd_version,
    "_cmd_connect": _cmd_connect,
    "_cmd_yolo": _cmd_yolo,
    "_cmd_tools": _cmd_tools,
    "_cmd_perm": _cmd_perm,
}


# ---------------------------------------------------------------------------
# CommandRegistry — 命令注册中心
# ---------------------------------------------------------------------------

class CommandRegistry:
    """命令注册中心，提供注册、查找、执行功能"""

    def __init__(self) -> None:
        self._commands: Dict[str, CommandDef] = {}
        self._aliases: Dict[str, CommandDef] = {}
        self._handlers: Dict[str, Callable] = dict(_HANDLER_MAP)

    def register(self, cmd: CommandDef) -> None:
        """注册一个命令"""
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._aliases[alias] = cmd

    def get(self, name: str) -> Optional[CommandDef]:
        """通过名称或别名查找命令"""
        # 先查主名
        cmd = self._commands.get(name)
        if cmd:
            return cmd
        # 再查别名
        return self._aliases.get(name)

    def execute(self, name: str, args: List[str], repl_instance) -> None:
        """执行一个命令

        Args:
            name: 命令名（不含 /）
            args: 参数列表
            repl_instance: GrassFlowREPL 实例
        """
        cmd = self.get(name)
        if cmd is None:
            repl_instance.add_output(
                f"Unknown command: /{name}. Type /help for available commands.",
                role="error",
            )
            return

        handler = self._handlers.get(cmd.handler_name)
        if handler is None:
            repl_instance.add_output(
                f"Handler not found for command: /{name}",
                role="error",
            )
            return

        handler(repl_instance, args)

    def register_handler(self, handler_name: str, handler: Callable) -> None:
        """注册自定义处理函数"""
        self._handlers[handler_name] = handler

    def all_commands(self) -> List[CommandDef]:
        """返回所有已注册的命令"""
        return list(self._commands.values())


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------

command_registry = CommandRegistry()

# Alias for convenience / backward compatibility
SlashCommandRegistry = CommandRegistry

# 从 COMMAND_REGISTRY 自动注册所有命令
for _cmd_def in COMMAND_REGISTRY:
    command_registry.register(_cmd_def)


# ---------------------------------------------------------------------------
# SlashCommandCompleter — 补全器（从 repl.py 提取）
# ---------------------------------------------------------------------------

class SlashCommandCompleter(Completer):
    """斜杠命令 + 文件路径补全器

    命令补全从 COMMAND_REGISTRY 动态获取，不再使用硬编码字典。
    """

    # 命令参数补全映射
    _ARG_COMPLETIONS: Dict[str, List[str]] = {
        "think": ["on", "off", "low", "medium", "high", "xhigh", "show", "full", "collapsed", "display"],
        "theme": ["default", "dark", "light", "cyber", "ocean"],
        "mcp": ["list", "start", "stop", "status", "add", "remove", "test"],
        "models": ["--api", "--config"],
        "skills": ["list", "view", "search", "install"],
        "yolo": ["on", "off", "status"],
        "tools": ["compact", "verbose", "on", "off", "toggle"],
        "perm": ["ask", "approve"],
        "permission": ["ask", "approve"],
        "connect": ["openai", "anthropic", "deepseek", "ollama"],
    }

    def __init__(self):
        self._path_completer = PathCompleter(
            expanduser=True,
            file_filter=lambda f: not f.startswith("."),
        )

    def _get_argument_completions(self, cmd_name: str, arg_part: str) -> List[Completion]:
        """获取命令参数补全

        Args:
            cmd_name: 命令名（不含 /）
            arg_part: 当前已输入的参数文本

        Returns:
            匹配的补全列表
        """
        completions: List[Completion] = []

        # /model: 从 config 读取模型名补全
        if cmd_name == "model":
            try:
                from tui.config_integration import load_config_readonly
                config = load_config_readonly()
                for provider_name, provider_config in config.provider.items():
                    if provider_config.models:
                        for model_name, model_info in provider_config.models.items():
                            name = model_info.name or model_name
                            if name.startswith(arg_part):
                                completions.append(Completion(
                                    text=name,
                                    start_position=-len(arg_part),
                                    display_meta=provider_name,
                                ))
            except Exception:
                pass
            return completions

        # 其他命令：从静态映射中查找
        options = self._ARG_COMPLETIONS.get(cmd_name, [])
        for opt in options:
            if opt.startswith(arg_part):
                completions.append(Completion(
                    text=opt,
                    start_position=-len(arg_part),
                ))
        return completions

    def get_completions(self, document: Document, complete_event) -> List[Completion]:
        text = document.text_before_cursor

        # 斜杠命令补全
        if text.startswith("/"):
            cmd_part = text[1:]
            # 空格后：先尝试参数补全，再 fallback 到文件路径补全
            if " " in cmd_part:
                space_idx = cmd_part.index(" ")
                cmd_name = cmd_part[:space_idx]
                arg_part = cmd_part[space_idx + 1:]

                # 尝试参数补全
                arg_completions = self._get_argument_completions(cmd_name, arg_part)
                if arg_completions:
                    yield from arg_completions
                    return

                # fallback: 文件路径补全
                file_doc = Document(arg_part, len(arg_part))
                for comp in self._path_completer.get_completions(file_doc, complete_event):
                    yield Completion(
                        text=comp.text,
                        start_position=comp.start_position,
                        display=comp.display,
                    )
                return

            # 补全命令名 — 从 command_registry 动态获取（包含技能命令）
            for cmd_def in command_registry.all_commands():
                if not cmd_def.visible:
                    continue
                # 主命令名匹配
                if cmd_def.name.startswith(cmd_part):
                    yield Completion(
                        text=cmd_def.name,
                        start_position=-len(cmd_part),
                        display_meta=cmd_def.description,
                    )
                # 别名匹配
                for alias in cmd_def.aliases:
                    if alias.startswith(cmd_part):
                        yield Completion(
                            text=alias,
                            start_position=-len(cmd_part),
                            display_meta=cmd_def.description,
                        )
            return

        # 文件路径补全（@file 语法）
        if text.startswith("@"):
            file_part = text[1:]
            file_doc = Document(file_part, len(file_part))
            for comp in self._path_completer.get_completions(file_doc, complete_event):
                yield Completion(
                    text=comp.text,
                    start_position=comp.start_position,
                    display=comp.display,
                )
            return

        return []

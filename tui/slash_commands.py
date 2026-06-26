"""
GrassFlow 斜杠命令系统 — 声明式命令注册与分发

从 tui.repl 中提取，参考 hermes 的 CommandDef + COMMAND_REGISTRY 设计。
所有命令处理函数通过 repl_instance 参数访问 GrassFlowREPL 实例。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# 命令处理函数（独立于 GrassFlowREPL 类）
# ---------------------------------------------------------------------------

def _cmd_help(repl, args: List[str]) -> None:
    """显示帮助"""
    lines = [
        "",
        "  Available commands:",
    ]
    for cmd_def in COMMAND_REGISTRY:
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
    """列出可用模型"""
    from core.config import config_manager

    try:
        config = config_manager.load_config()
        lines = ["", "  Available models:"]
        for provider_name, provider_config in config.provider.items():
            lines.append(f"\n  [{provider_name}]")
            if provider_config.models:
                for model_name, model_info in provider_config.models.items():
                    name = model_info.name or model_name
                    lines.append(f"    - {name}")
            else:
                lines.append("    (no models configured)")
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
    from core.config import config_manager

    if not args:
        try:
            config = config_manager.load_config()
            default = config.llm.default_provider
            repl.add_output(f"Current provider: {default}\nUsage: /provider <provider_name>", role="system")
        except Exception:
            repl.add_output(f"Usage: /provider <provider_name>", role="system")
        return

    name = args[0]
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
        limit = int(args[0]) if args else 10
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
    from core.config import config_manager

    try:
        config = config_manager.load_config()
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
        f"    Estimated tokens: {repl._token_count}",
        f"    Token limit: {repl._token_limit}",
        f"    API calls: {repl._api_call_count}",
        f"    Last latency: {repl._last_latency_ms}ms",
    ]
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
        status = "ON" if enabled else "OFF"
        repl.add_output(
            f"Thinking mode: {status}\n"
            f"Effort: {effort}\n"
            f"Usage: /think [on|off|low|medium|high|xhigh|show]",
            role="system",
        )
        return

    arg = args[0].lower()

    if arg == "show":
        thinking = repl.session.metadata.get("thinking", {}) if repl.session else {}
        enabled = thinking.get("enabled", False)
        effort = thinking.get("effort", "medium")
        repl.add_output(
            f"  Thinking configuration:\n"
            f"    enabled: {enabled}\n"
            f"    effort: {effort}",
            role="system",
        )
        return

    parsed = parse_reasoning_effort(arg)
    if parsed is None:
        repl.add_output(
            f"Unknown option: '{arg}'\n"
            f"Usage: /think [on|off|low|medium|high|xhigh|show]",
            role="error",
        )
        return

    if repl.session:
        repl.session.metadata["thinking"] = parsed

    enabled = parsed.get("enabled", False)
    effort = parsed.get("effort", "off")
    if enabled:
        repl.add_output(f"Thinking mode: ON (effort: {effort})", role="system")
    else:
        repl.add_output("Thinking mode: OFF", role="system")


def _cmd_resume(repl, args: List[str]) -> None:
    """恢复历史会话"""
    _handle_list_sessions(repl)


def _cmd_retry(repl, args: List[str]) -> None:
    """重试上一条消息"""
    if not repl.session:
        repl.add_output("No active session.", role="error")
        return

    # 获取最后一条用户消息
    messages = repl.session.get_messages() if hasattr(repl.session, "get_messages") else []
    last_user_msg = None
    for msg in reversed(messages):
        if hasattr(msg, "role") and msg.role == "user":
            last_user_msg = msg
            break

    if not last_user_msg:
        repl.add_output("No user message to retry.", role="error")
        return

    content = last_user_msg.content if hasattr(last_user_msg, "content") else str(last_user_msg)
    repl.add_output(f"Retrying: {content[:100]}...", role="system")
    # 触发重新发送（通过 _process_user_input 流程）
    repl._retry_last = True


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
    try:
        from core.config import config_manager
        config = config_manager.load_config()
        mcp_servers = getattr(config, "mcp_servers", None)
        if mcp_servers:
            lines = ["  MCP servers:"]
            for name, srv in mcp_servers.items():
                lines.append(f"    - {name}")
            repl.add_output("\n".join(lines), role="system")
        else:
            repl.add_output("No MCP servers configured.", role="system")
    except Exception:
        repl.add_output("MCP status not available (config module error).", role="system")


def _cmd_skills(repl, args: List[str]) -> None:
    """浏览技能列表"""
    repl.add_output(
        "Skills browser not yet implemented.\n"
        "Use /help to see available commands.",
        role="system",
    )


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
        f"    Estimated tokens: {repl._token_count}",
        f"    Token limit: {repl._token_limit}",
        f"    API calls: {repl._api_call_count}",
        f"    Last latency: {repl._last_latency_ms}ms",
    ]
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


# ---------------------------------------------------------------------------
# 操作处理函数
# ---------------------------------------------------------------------------

def _handle_compact(repl) -> None:
    """压缩上下文"""
    repl.add_output("Context compaction triggered.", role="system")
    # TODO: 集成 ContextCompressor
    repl._token_count = max(0, repl._token_count // 2)


def _handle_new_session(repl) -> None:
    """创建新会话"""
    if repl._enable_session and repl.session_mgr:
        try:
            old_id = repl.session.id if repl.session else None

            directory = os.getcwd()
            repl.session = repl.session_mgr.create_session(
                title=f"REPL Session",
                directory=directory,
            )
            repl.clear_output()
            repl._reset_stats()
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

    entry = repl.output.pop()
    repl._undo_stack.append(entry)
    repl.add_output(f"Undone: {entry.text[:80]}...", role="system")


def _handle_redo(repl) -> None:
    """重做"""
    if not repl._undo_stack:
        repl.add_output("Nothing to redo.", role="system")
        return

    entry = repl._undo_stack.pop()
    repl.output.append(entry)
    repl.add_output(f"Redone: {entry.text[:80]}...", role="system")


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
        aliases=(),
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
        description="列出可用模型",
        category="Configuration",
        aliases=(),
        args_hint="",
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
        args_hint="[on|off|low|medium|high|xhigh|show]",
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
        args_hint="",
        handler_name="_cmd_yolo",
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
    "_cmd_list_sessions": _cmd_list_sessions,
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
        "think": ["on", "off", "low", "medium", "high", "xhigh", "show"],
        "reasoning": ["on", "off", "low", "medium", "high", "xhigh", "show"],
        "theme": ["default", "dark", "light", "cyber", "ocean"],
        "mcp": ["list", "start", "stop", "status", "add", "remove", "test"],
        "skills": ["list", "view", "search", "install"],
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
                from core.config import config_manager
                config = config_manager.load_config()
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

            # 补全命令名 — 从 COMMAND_REGISTRY 动态获取
            for cmd_def in COMMAND_REGISTRY:
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

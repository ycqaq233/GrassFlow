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
        name="sessions",
        description="列出历史会话",
        category="Session",
        aliases=(),
        args_hint="",
        handler_name="_cmd_list_sessions",
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
    """斜杠命令 + 文件路径补全器"""

    # 所有可用的斜杠命令
    COMMANDS: Dict[str, str] = {
        "help": "显示帮助信息",
        "h": "显示帮助信息（别名）",
        "model": "切换模型  /model <name>",
        "models": "列出可用模型",
        "new": "创建新会话",
        "clear": "清空会话",
        "cls": "清屏",
        "compact": "手动压缩上下文",
        "sessions": "列出历史会话",
        "init": "分析项目创建 AGENTS.md",
        "undo": "撤销上次操作",
        "redo": "重做",
        "exit": "退出 REPL",
        "quit": "退出 REPL（别名）",
        "q": "退出 REPL（别名）",
        "theme": "切换主题  /theme <name>",
        "provider": "切换 provider  /provider <name>",
        "run": "执行工作流文件  /run <file>",
        "list": "列出已保存的工作流",
        "ls": "列出已保存的工作流（别名）",
        "history": "查看执行历史",
        "validate": "验证工作流文件",
        "templates": "列出可用模板",
        "config": "查看/修改配置",
        "stats": "显示上下文统计",
        "status": "显示当前会话状态",
    }

    def __init__(self):
        self._path_completer = PathCompleter(
            expanduser=True,
            file_filter=lambda f: not f.startswith("."),
        )

    def get_completions(self, document: Document, complete_event) -> List[Completion]:
        text = document.text_before_cursor

        # 斜杠命令补全
        if text.startswith("/"):
            cmd_part = text[1:]
            # 空格后走文件路径补全
            if " " in cmd_part:
                space_idx = cmd_part.index(" ")
                file_part = cmd_part[space_idx + 1:]
                file_doc = Document(file_part, len(file_part))
                for comp in self._path_completer.get_completions(file_doc, complete_event):
                    yield Completion(
                        text=comp.text,
                        start_position=comp.start_position,
                        display=comp.display,
                    )
                return

            # 补全命令名
            for cmd_name, desc in sorted(self.COMMANDS.items()):
                if cmd_name.startswith(cmd_part):
                    yield Completion(
                        text=cmd_name,
                        start_position=-len(cmd_part),
                        display=f"/{cmd_name}  —  {desc}",
                        display_meta=desc,
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

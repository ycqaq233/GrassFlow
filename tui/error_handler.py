"""GrassFlow TUI 错误处理模块

连接 core/error_classifier.py 的结构化错误分类与 TUI 显示层。
提供统一的错误格式化、显示和恢复建议。
"""

from typing import Optional, Dict, Any
import logging
import traceback

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from core.error_classifier import (
    ErrorClassifier,
    ErrorCategory,
    ErrorSeverity,
    ErrorContext,
    GrassFlowError,
    RateLimitError,
    AuthExpiredError,
    ContextOverflowError,
    ProviderError,
    NetworkError,
    ToolError,
    PermissionDeniedError,
    TimeoutError,
    ValidationError,
)

logger = logging.getLogger(__name__)


# -- Category display config -----------------------------------------------

_CATEGORY_DISPLAY: Dict[ErrorCategory, Dict[str, str]] = {
    ErrorCategory.RATE_LIMITED: {
        "icon": "⏱️", "color": "yellow", "label": "Rate Limited",
        "hint": "The API rate limit was exceeded. The system will retry with backoff. If persistent, consider using a different provider or waiting a few minutes.",
    },
    ErrorCategory.AUTH_EXPIRED: {
        "icon": "🔑", "color": "red", "label": "Authentication Error",
        "hint": "API key is invalid or expired. Run: grassflow config api-key <provider> <new-key>",
    },
    ErrorCategory.CONTEXT_OVERFLOW: {
        "icon": "📏", "color": "magenta", "label": "Context Overflow",
        "hint": "The conversation context exceeds the model's limit. Try /clear to reset, or use a model with a larger context window.",
    },
    ErrorCategory.PROVIDER_ERROR: {
        "icon": "☁️", "color": "red", "label": "Provider Error",
        "hint": "The LLM provider returned a server error. This is usually transient -- try again. If persistent, switch providers.",
    },
    ErrorCategory.NETWORK_ERROR: {
        "icon": "🌐", "color": "yellow", "label": "Network Error",
        "hint": "A network connection failed. Check your internet connection and proxy settings.",
    },
    ErrorCategory.TOOL_ERROR: {
        "icon": "🔧", "color": "yellow", "label": "Tool Error",
        "hint": "A tool execution failed. Check the tool's input parameters and permissions.",
    },
    ErrorCategory.PERMISSION_DENIED: {
        "icon": "🚫", "color": "red", "label": "Permission Denied",
        "hint": "Access was denied. Check your API key permissions and account plan.",
    },
    ErrorCategory.TIMEOUT: {
        "icon": "⏰", "color": "yellow", "label": "Timeout",
        "hint": "The operation timed out. The system will retry automatically. If persistent, check network stability.",
    },
    ErrorCategory.VALIDATION_ERROR: {
        "icon": "⚠️", "color": "yellow", "label": "Validation Error",
        "hint": "Input validation failed. Check your DSL syntax or workflow configuration.",
    },
    ErrorCategory.UNKNOWN: {
        "icon": "❓", "color": "dim", "label": "Unknown Error",
        "hint": "An unexpected error occurred. Check logs for details.",
    },
}


# -- Severity display -------------------------------------------------------

_SEVERITY_BADGE: Dict[ErrorSeverity, str] = {
    ErrorSeverity.LOW: "[dim]● LOW[/dim]",
    ErrorSeverity.MEDIUM: "[yellow]● MEDIUM[/yellow]",
    ErrorSeverity.HIGH: "[red]● HIGH[/red]",
    ErrorSeverity.CRITICAL: "[bold red]● CRITICAL[/bold red]",
}


class ErrorHandler:
    """TUI 错误处理器

    桥接 core/error_classifier.py 和 TUI 显示层。
    """

    def __init__(self, console: Optional[Any] = None):
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    def format_error(
        self,
        error: Exception,
        context: Optional[ErrorContext] = None,
        show_traceback: bool = False,
        show_hint: bool = True,
    ) -> None:
        """格式化并显示错误

        Args:
            error: 原始异常
            context: 错误上下文 (agent_name, workflow_id 等)
            show_traceback: 是否显示堆栈跟踪
            show_hint: 是否显示恢复建议
        """
        # 分类错误
        classified = ErrorClassifier.classify(error, context)

        if not HAS_RICH:
            self._format_plain(classified, show_traceback, show_hint)
            return

        self._format_rich(classified, show_traceback, show_hint)

    def _format_rich(
        self,
        error: GrassFlowError,
        show_traceback: bool,
        show_hint: bool,
    ) -> None:
        """Rich 格式化错误显示"""
        cat_display = _CATEGORY_DISPLAY.get(
            error.category, _CATEGORY_DISPLAY[ErrorCategory.UNKNOWN]
        )

        # 构建标题行
        title_text = Text()
        title_text.append(f" {cat_display['icon']} ", style="")
        title_text.append(cat_display["label"], style=f"bold {cat_display['color']}")
        severity_badge = _SEVERITY_BADGE.get(error.severity, "")
        if severity_badge:
            title_text.append(f"  {severity_badge}", style="")

        # 构建内容
        content = Text()
        content.append(error.message, style=cat_display["color"])

        # 上下文信息
        if error.context:
            ctx_parts = []
            if error.context.agent_name:
                ctx_parts.append(f"Agent: {error.context.agent_name}")
            if error.context.provider:
                ctx_parts.append(f"Provider: {error.context.provider}")
            if error.context.model:
                ctx_parts.append(f"Model: {error.context.model}")
            if error.context.workflow_id:
                ctx_parts.append(f"Workflow: {error.context.workflow_id}")
            if error.context.attempt > 1:
                ctx_parts.append(f"Attempt: {error.context.attempt}/{error.context.max_attempts}")
            if ctx_parts:
                content.append("\n\n")
                content.append(" | ".join(ctx_parts), style="dim")

        # 重试信息
        if error.is_retryable():
            content.append("\n")
            content.append(f"Retryable: yes (max {error.retry_policy.max_retries} attempts)", style="dim green")
        else:
            content.append("\n")
            content.append("Retryable: no", style="dim red")

        # 堆栈跟踪
        if show_traceback and error.original_error:
            tb = "".join(traceback.format_exception(
                type(error.original_error),
                error.original_error,
                error.original_error.__traceback__,
            ))
            content.append("\n\n")
            content.append(tb, style="dim")

        # 恢复建议
        if show_hint:
            hint = cat_display.get("hint", "")
            if hint:
                content.append("\n\n")
                content.append("→ ", style=f"bold {cat_display['color']}")
                content.append(hint, style="italic dim")

        # 渲染 Panel
        panel = Panel(
            content,
            title=title_text,
            border_style=cat_display["color"],
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self.console.print()
        self.console.print(panel)

    def _format_plain(
        self,
        error: GrassFlowError,
        show_traceback: bool,
        show_hint: bool,
    ) -> None:
        """纯文本错误显示 (无 Rich)"""
        cat_display = _CATEGORY_DISPLAY.get(
            error.category, _CATEGORY_DISPLAY[ErrorCategory.UNKNOWN]
        )
        label = cat_display["label"]

        print(f"\n[{label}] {error.message}")

        if error.context and error.context.agent_name:
            print(f"  Agent: {error.context.agent_name}")
        if error.is_retryable():
            print(f"  Retryable: yes (max {error.retry_policy.max_retries})")
        else:
            print("  Retryable: no")

        if show_traceback and error.original_error:
            print(f"\n{traceback.format_exception(type(error.original_error), error.original_error, error.original_error.__traceback__)}")

        if show_hint:
            hint = cat_display.get("hint", "")
            if hint:
                print(f"  -> {hint}")

    def get_recovery_hint(self, error: Exception) -> str:
        """获取错误的恢复建议文本"""
        classified = ErrorClassifier.classify(error)
        cat_display = _CATEGORY_DISPLAY.get(classified.category, {})
        return cat_display.get("hint", "An unexpected error occurred.")

    def get_category(self, error: Exception) -> ErrorCategory:
        """获取错误分类"""
        return ErrorClassifier.classify(error).category


# -- 便捷函数 ----------------------------------------------------------------

_error_handler: Optional[ErrorHandler] = None


def get_error_handler(console: Optional[Any] = None) -> ErrorHandler:
    """获取全局错误处理器实例 (单例)"""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler(console=console)
    return _error_handler


def handle_cli_error(
    error: Exception,
    context: Optional[ErrorContext] = None,
    show_traceback: bool = False,
) -> None:
    """处理 CLI 命令错误的便捷函数

    用于替代 cli.py 中所有 ad-hoc 的 display.print_error() 调用。

    Args:
        error: 捕获的异常
        context: 可选的错误上下文
        show_traceback: 是否显示堆栈 (默认否, 用户可通过 --verbose 启用)
    """
    handler = get_error_handler()
    handler.format_error(error, context=context, show_traceback=show_traceback)

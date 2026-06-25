# GrassFlow TUI
# 终端用户界面模块

from .dsl_parser import DSLParser, DSLError, parse_dsl, parse_file
from .display import Display, ProgressDisplay, display, progress_display


# ==================== 延迟导入（避免 prompt_toolkit 阻塞非 REPL 测试） ====================

def __getattr__(name: str):
    """延迟导入 REPL/安全/主题模块"""
    _LAZY_IMPORTS = {
        # REPL
        "GrassFlowREPL": ".repl",
        "AsyncGrassFlowREPL": ".repl",
        "REPLMode": ".repl",
        "REPLTheme": ".repl",
        "OutputEntry": ".repl",
        "SlashCommandCompleter": ".repl",
        "create_repl": ".repl",
        "run_repl": ".repl",
        # 安全系统
        "DangerousCommandDetector": ".dangerous_commands",
        "DANGEROUS_PATTERNS": ".dangerous_commands",
        "HARDLINE_PATTERNS": ".dangerous_commands",
        "detect_dangerous_command": ".dangerous_commands",
        "detect_hardline_command": ".dangerous_commands",
        # 审批系统
        "ApprovalMode": ".approval",
        "ApprovalHandler": ".approval",
        "get_default_handler": ".approval",
        "set_approval_mode": ".approval",
        # 主题系统
        "GrassFlowTheme": ".themes",
        "RichStyle": ".themes",
        "ThemeManager": ".themes",
        "BUILTIN_THEMES": ".themes",
        "get_theme_manager": ".themes",
        "get_active_theme": ".themes",
        "get_active_rich_style": ".themes",
        "set_theme": ".themes",
        "list_themes": ".themes",
    }

    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], package=__package__)
        obj = getattr(module, name)
        # 缓存到模块全局，下次直接访问
        globals()[name] = obj
        return obj

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # DSL
    "DSLParser",
    "DSLError",
    "parse_dsl",
    "parse_file",
    # Display
    "Display",
    "ProgressDisplay",
    "display",
    "progress_display",
    # REPL
    "GrassFlowREPL",
    "AsyncGrassFlowREPL",
    "REPLMode",
    "REPLTheme",
    "OutputEntry",
    "SlashCommandCompleter",
    "create_repl",
    "run_repl",
    # 安全系统
    "DangerousCommandDetector",
    "DANGEROUS_PATTERNS",
    "HARDLINE_PATTERNS",
    "detect_dangerous_command",
    "detect_hardline_command",
    "ApprovalMode",
    "ApprovalHandler",
    "get_default_handler",
    "set_approval_mode",
    # 主题系统
    "GrassFlowTheme",
    "RichStyle",
    "ThemeManager",
    "BUILTIN_THEMES",
    "get_theme_manager",
    "get_active_theme",
    "get_active_rich_style",
    "set_theme",
    "list_themes",
]

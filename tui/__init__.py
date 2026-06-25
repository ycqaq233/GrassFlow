# GrassFlow TUI
# 终端用户界面模块

from .dsl_parser import DSLParser, DSLError, parse_dsl, parse_file
from .display import Display, ProgressDisplay, display, progress_display
from .repl import (
    GrassFlowREPL,
    AsyncGrassFlowREPL,
    REPLMode,
    REPLTheme,
    OutputEntry,
    SlashCommandCompleter,
    create_repl,
    run_repl,
)
from .dangerous_commands import (
    DangerousCommandDetector,
    DANGEROUS_PATTERNS,
    HARDLINE_PATTERNS,
    detect_dangerous_command,
    detect_hardline_command,
)
from .approval import (
    ApprovalMode,
    ApprovalHandler,
    get_default_handler,
    set_approval_mode,
)
from .themes import (
    GrassFlowTheme,
    RichStyle,
    ThemeManager,
    BUILTIN_THEMES,
    get_theme_manager,
    get_active_theme,
    get_active_rich_style,
    set_theme,
    list_themes,
)

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

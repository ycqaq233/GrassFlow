"""
GrassFlow CLI 子命令模块

参考 hermes 的 hermes_cli/subcommands/ 结构，将 CLI 子命令拆分为独立模块：
- init_cmd: 项目初始化
- doctor_cmd: 系统健康检查
- model_cmd: 模型列表
- plugin_cmd: 插件管理
"""

from tui.commands.init_cmd import init_command
from tui.commands.doctor_cmd import doctor_command
from tui.commands.model_cmd import model_command
from tui.commands.plugin_cmd import plugin_command

__all__ = [
    "init_command",
    "doctor_command",
    "model_command",
    "plugin_command",
]

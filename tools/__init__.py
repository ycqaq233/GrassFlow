"""
GrassFlow 内置工具系统

提供统一的工具接口和内置工具实现：
- shell: 执行 shell 命令
- read: 读取文件
- write: 写入文件
- glob: 文件模式匹配
- grep: 内容搜索
- webfetch: 获取网页内容
"""

from .tool import Tool, ToolContext, ToolResult, ToolRegistry
from .bridge import LegacyToolAdapter
from .shell import ShellTool
from .read import ReadTool
from .write import WriteTool
from .glob import GlobTool
from .grep import GrepTool
from .webfetch import WebFetchTool

__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "LegacyToolAdapter",
    "ShellTool",
    "ReadTool",
    "WriteTool",
    "GlobTool",
    "GrepTool",
    "WebFetchTool",
]

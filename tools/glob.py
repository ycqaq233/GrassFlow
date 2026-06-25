"""
GrassFlow Glob 工具

文件模式匹配，参考 opencode 的 GlobTool 实现
"""

import os
import fnmatch
from pathlib import Path
from typing import Any, Dict, List
from .tool import Tool, ToolContext, ToolResult


# 默认结果限制
DEFAULT_LIMIT = 100


class GlobTool(Tool):
    """
    Glob 工具 - 文件模式匹配

    支持:
    - 标准 glob 模式匹配
    - 递归搜索
    - 结果限制
    """

    @property
    def id(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return """Find files matching a glob pattern.

Use this tool to:
- Search for files by name or extension
- Find files in specific directories
- Locate configuration files
- Discover project structure

Examples:
- "*.py" - Find all Python files
- "**/*.js" - Find all JavaScript files recursively
- "src/**/*.ts" - Find TypeScript files in src directory
- "**/config.json" - Find all config.json files

Important:
- If no path is specified, searches from the current working directory
- Results are limited to prevent context overflow
- Use more specific patterns for large codebases"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match files against"
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in. If not specified, the current working directory will be used."
                }
            },
            "required": ["pattern"]
        }

    def _glob_recursive(self, base_path: str, pattern: str, limit: int) -> List[str]:
        """
        递归执行 glob 匹配

        支持 ** 递归模式
        """
        results = []
        base = Path(base_path)

        # 处理 ** 模式
        if '**' in pattern:
            # 分割模式
            parts = pattern.split('**')
            if len(parts) == 2:
                prefix = parts[0].rstrip('/\\')
                suffix = parts[1].lstrip('/\\')

                # 如果有前缀，先匹配前缀目录
                if prefix:
                    search_base = base / prefix if prefix else base
                else:
                    search_base = base

                if not search_base.exists():
                    return results

                # 递归遍历
                for root, dirs, files in os.walk(search_base):
                    # 跳过隐藏目录
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                    for filename in files:
                        if len(results) >= limit:
                            return results

                        filepath = Path(root) / filename
                        relative = filepath.relative_to(base)

                        # 匹配后缀
                        if suffix:
                            if fnmatch.fnmatch(filename, suffix):
                                results.append(str(relative))
                        else:
                            results.append(str(relative))
            else:
                # 复杂 ** 模式，使用简单的递归匹配
                for root, dirs, files in os.walk(base):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for filename in files:
                        if len(results) >= limit:
                            return results
                        filepath = Path(root) / filename
                        relative = filepath.relative_to(base)
                        if fnmatch.fnmatch(str(relative), pattern):
                            results.append(str(relative))
        else:
            # 简单模式，不使用递归
            if not base.exists():
                return results

            for item in base.iterdir():
                if len(results) >= limit:
                    return results

                if item.is_file() and fnmatch.fnmatch(item.name, pattern):
                    results.append(item.name)
                elif item.is_dir() and fnmatch.fnmatch(item.name, pattern):
                    results.append(item.name + '/')

        return results

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行 glob 搜索"""
        pattern = params["pattern"]
        search_path = params.get("path", ctx.cwd)

        # 解析路径
        if not os.path.isabs(search_path):
            search_path = os.path.join(ctx.cwd, search_path)
        search_path = os.path.abspath(search_path)

        # 检查路径是否存在
        if not os.path.exists(search_path):
            return ToolResult(
                output=f"Error: Path does not exist: {search_path}",
                title=pattern,
                metadata={"error": "path_not_found"}
            )

        # 检查是否为目录
        if not os.path.isdir(search_path):
            return ToolResult(
                output=f"Error: Path is not a directory: {search_path}",
                title=pattern,
                metadata={"error": "not_directory"}
            )

        # 执行搜索
        try:
            files = self._glob_recursive(search_path, pattern, DEFAULT_LIMIT)
            truncated = len(files) >= DEFAULT_LIMIT

            if not files:
                output = "No files found"
            else:
                # 转换为绝对路径
                abs_files = [os.path.join(search_path, f) for f in files]
                output = "\n".join(abs_files)

                if truncated:
                    output += f"\n\n(Results are truncated: showing first {DEFAULT_LIMIT} results. Consider using a more specific path or pattern.)"

            return ToolResult(
                output=output,
                title=pattern,
                metadata={
                    "count": len(files),
                    "truncated": truncated,
                    "path": search_path,
                    "pattern": pattern,
                },
                truncated=truncated
            )
        except Exception as e:
            return ToolResult(
                output=f"Error executing glob: {str(e)}",
                title=pattern,
                metadata={"error": str(e)}
            )

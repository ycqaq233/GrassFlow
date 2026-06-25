"""
GrassFlow Grep 工具

内容搜索，参考 opencode 的 GrepTool 实现
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .tool import Tool, ToolContext, ToolResult


# 默认结果限制
DEFAULT_LIMIT = 100
# 最大匹配行长度
MAX_MATCH_LENGTH = 500


class GrepTool(Tool):
    """
    Grep 工具 - 文件内容搜索

    支持:
    - 正则表达式搜索
    - 文件类型过滤
    - 递归搜索
    - 结果限制
    """

    @property
    def id(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return """Search for a pattern in file contents using regex.

Use this tool to:
- Find code patterns
- Search for specific text
- Locate function definitions
- Find variable usage

Examples:
- "function.*main" - Find function definitions containing 'main'
- "import.*numpy" - Find numpy imports
- "TODO|FIXME" - Find TODO and FIXME comments
- "class.*Agent" - Find class definitions containing 'Agent'

Important:
- Uses Python regex syntax
- Case-sensitive by default
- Searches recursively in the specified directory
- Results are limited to prevent context overflow"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for in file contents"
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in. Defaults to the current working directory."
                },
                "include": {
                    "type": "string",
                    "description": 'File pattern to include in the search (e.g. "*.py", "*.{ts,tsx}")'
                }
            },
            "required": ["pattern"]
        }

    def _should_skip_file(self, filepath: str, include_pattern: Optional[str] = None) -> bool:
        """检查是否应该跳过该文件"""
        path = Path(filepath)

        # 跳过隐藏文件和目录
        if any(part.startswith('.') for part in path.parts):
            return True

        # 跳过常见的非代码目录
        skip_dirs = {
            'node_modules', '__pycache__', '.git', '.svn', '.hg',
            'venv', '.venv', 'env', '.env', 'dist', 'build',
            'target', 'bin', 'obj', '.idea', '.vscode',
        }
        if any(part in skip_dirs for part in path.parts):
            return True

        # 检查 include 模式
        if include_pattern:
            # 支持 *.{ts,tsx} 格式
            if include_pattern.startswith('*.') and ',' in include_pattern:
                # 解析多个扩展名
                ext_part = include_pattern[2:]  # 去掉 *.
                if ext_part.startswith('{') and ext_part.endswith('}'):
                    exts = ext_part[1:-1].split(',')
                    return not any(path.name.endswith(f'.{ext.strip()}') for ext in exts)
            else:
                return not fnmatch.fnmatch(path.name, include_pattern)

        # 跳过二进制文件扩展名
        binary_extensions = {
            '.zip', '.tar', '.gz', '.exe', '.dll', '.so', '.class',
            '.jar', '.war', '.7z', '.doc', '.docx', '.xls', '.xlsx',
            '.ppt', '.pptx', '.odt', '.ods', '.odp', '.bin', '.dat',
            '.obj', '.o', '.a', '.lib', '.wasm', '.pyc', '.pyo',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico',
            '.mp3', '.mp4', '.avi', '.mov', '.pdf', '.db', '.sqlite',
        }
        if path.suffix.lower() in binary_extensions:
            return True

        return False

    def _search_file(
        self,
        filepath: str,
        pattern: re.Pattern,
        max_matches: int
    ) -> List[Tuple[int, str]]:
        """
        在单个文件中搜索

        Returns:
            List of (line_number, line_text) tuples
        """
        matches = []
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                for line_num, line in enumerate(f, 1):
                    if len(matches) >= max_matches:
                        break

                    line = line.rstrip('\n')
                    if pattern.search(line):
                        # 截断过长的行
                        if len(line) > MAX_MATCH_LENGTH:
                            line = line[:MAX_MATCH_LENGTH] + "..."
                        matches.append((line_num, line))
        except (PermissionError, UnicodeDecodeError, OSError):
            pass

        return matches

    def _grep_recursive(
        self,
        base_path: str,
        pattern: re.Pattern,
        include_pattern: Optional[str],
        limit: int
    ) -> List[Tuple[str, int, str]]:
        """
        递归搜索文件

        Returns:
            List of (filepath, line_number, line_text) tuples
        """
        results = []
        base = Path(base_path)

        for root, dirs, files in os.walk(base):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                if len(results) >= limit:
                    return results

                filepath = os.path.join(root, filename)

                # 检查是否应该跳过
                if self._should_skip_file(filepath, include_pattern):
                    continue

                # 搜索文件
                matches = self._search_file(filepath, pattern, limit - len(results))
                for line_num, line_text in matches:
                    results.append((filepath, line_num, line_text))
                    if len(results) >= limit:
                        return results

        return results

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行 grep 搜索"""
        pattern_str = params["pattern"]
        search_path = params.get("path", ctx.cwd)
        include_pattern = params.get("include")

        # 验证 pattern
        if not pattern_str:
            return ToolResult(
                output="Error: pattern is required",
                title=pattern_str,
                metadata={"error": "empty_pattern"}
            )

        # 编译正则表达式
        try:
            pattern = re.compile(pattern_str)
        except re.error as e:
            return ToolResult(
                output=f"Error: Invalid regex pattern: {str(e)}",
                title=pattern_str,
                metadata={"error": "invalid_regex", "detail": str(e)}
            )

        # 解析路径
        if not os.path.isabs(search_path):
            search_path = os.path.join(ctx.cwd, search_path)
        search_path = os.path.abspath(search_path)

        # 检查路径是否存在
        if not os.path.exists(search_path):
            return ToolResult(
                output=f"Error: Path does not exist: {search_path}",
                title=pattern_str,
                metadata={"error": "path_not_found"}
            )

        # 执行搜索
        try:
            results = self._grep_recursive(search_path, pattern, include_pattern, DEFAULT_LIMIT)
            truncated = len(results) >= DEFAULT_LIMIT

            if not results:
                output = "No files found"
            else:
                # 格式化输出
                output_lines = [f"Found {len(results)} matches{' (more matches available)' if truncated else ''}"]
                output_lines.append("")

                current_file = ""
                for filepath, line_num, line_text in results:
                    if filepath != current_file:
                        current_file = filepath
                        output_lines.append(f"{filepath}:")
                    output_lines.append(f"  Line {line_num}: {line_text}")

                if truncated:
                    output_lines.append("")
                    output_lines.append("(Results truncated. Consider using a more specific path or pattern.)")

                output = "\n".join(output_lines)

            return ToolResult(
                output=output,
                title=pattern_str,
                metadata={
                    "matches": len(results),
                    "truncated": truncated,
                    "path": search_path,
                    "pattern": pattern_str,
                    "include": include_pattern,
                },
                truncated=truncated
            )
        except Exception as e:
            return ToolResult(
                output=f"Error executing grep: {str(e)}",
                title=pattern_str,
                metadata={"error": str(e)}
            )


# 导入 fnmatch（在 _should_skip_file 中使用）
import fnmatch

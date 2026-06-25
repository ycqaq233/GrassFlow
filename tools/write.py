"""
GrassFlow Write 工具

写入文件内容，参考 opencode 的 WriteTool 实现
"""

import os
from pathlib import Path
from typing import Any, Dict
from .tool import Tool, ToolContext, ToolResult


class WriteTool(Tool):
    """
    Write 工具 - 写入文件

    支持:
    - 创建新文件
    - 覆盖现有文件
    - 自动创建父目录
    """

    @property
    def id(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return """Write content to a file.

Use this tool to:
- Create new files
- Overwrite existing files
- Save generated content

Important:
- The file path must be absolute
- Parent directories will be created automatically if they don't exist
- Existing files will be overwritten without warning
- Use the 'read' tool first to check if a file exists before overwriting"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "The absolute path to the file to write (must be absolute, not relative)"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file"
                }
            },
            "required": ["filePath", "content"]
        }

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行文件写入"""
        filepath = params["filePath"]
        content = params["content"]

        # 解析路径
        if not os.path.isabs(filepath):
            filepath = os.path.join(ctx.cwd, filepath)
        filepath = os.path.abspath(filepath)

        # 检查是否已存在
        exists = os.path.exists(filepath)
        old_content = None
        if exists:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    old_content = f.read()
            except Exception:
                pass

        try:
            # 创建父目录
            parent_dir = os.path.dirname(filepath)
            os.makedirs(parent_dir, exist_ok=True)

            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            # 计算统计信息
            lines_written = content.count('\n') + 1
            bytes_written = len(content.encode('utf-8'))

            # 生成简单的 diff 摘要
            diff_summary = ""
            if old_content is not None:
                old_lines = old_content.count('\n') + 1
                new_lines = lines_written
                diff_summary = f"\n\nLines: {old_lines} -> {new_lines}"

            output = "Wrote file successfully."
            if diff_summary:
                output += diff_summary

            return ToolResult(
                output=output,
                title=str(Path(filepath).name),
                metadata={
                    "path": filepath,
                    "existed": exists,
                    "lines": lines_written,
                    "bytes": bytes_written,
                }
            )
        except PermissionError:
            return ToolResult(
                output=f"Error: Permission denied: {filepath}",
                title=str(Path(filepath).name),
                metadata={"error": "permission_denied"}
            )
        except Exception as e:
            return ToolResult(
                output=f"Error writing file: {str(e)}",
                title=str(Path(filepath).name),
                metadata={"error": str(e)}
            )

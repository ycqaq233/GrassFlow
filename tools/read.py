"""
GrassFlow Read 工具

读取文件内容，参考 opencode 的 ReadTool 实现
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from .tool import Tool, ToolContext, ToolResult


# 默认读取限制
DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_BYTES = 50 * 1024  # 50 KB


class ReadTool(Tool):
    """
    Read 工具 - 读取文件或目录

    支持:
    - 读取文件内容（带行号）
    - 读取目录列表
    - 分页读取（offset/limit）
    - 自动检测二进制文件
    """

    @property
    def id(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return """Read the contents of a file or list a directory.

Use this tool to:
- Read source code files
- View configuration files
- List directory contents
- Inspect file structure

Features:
- Shows line numbers for easy reference
- Supports pagination with offset/limit
- Automatically detects and skips binary files
- Truncates large files to prevent context overflow"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "The absolute path to the file or directory to read"
                },
                "offset": {
                    "type": "integer",
                    "description": "The line number to start reading from (1-indexed, optional)",
                    "minimum": 1
                },
                "limit": {
                    "type": "integer",
                    "description": "The maximum number of lines to read (optional, defaults to 2000)",
                    "minimum": 1
                }
            },
            "required": ["filePath"]
        }

    def _is_binary(self, filepath: str, sample_size: int = 8192) -> bool:
        """
        检测文件是否为二进制文件

        通过检查文件头部的 null 字节和不可打印字符来判断
        """
        # 已知的二进制扩展名
        binary_extensions = {
            '.zip', '.tar', '.gz', '.exe', '.dll', '.so', '.class',
            '.jar', '.war', '.7z', '.doc', '.docx', '.xls', '.xlsx',
            '.ppt', '.pptx', '.odt', '.ods', '.odp', '.bin', '.dat',
            '.obj', '.o', '.a', '.lib', '.wasm', '.pyc', '.pyo',
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.svg',
            '.mp3', '.mp4', '.avi', '.mov', '.pdf', '.db', '.sqlite',
        }

        ext = Path(filepath).suffix.lower()
        if ext in binary_extensions:
            return True

        try:
            with open(filepath, 'rb') as f:
                chunk = f.read(sample_size)
                if not chunk:
                    return False

                # 检查 null 字节
                if b'\x00' in chunk:
                    return True

                # 检查不可打印字符比例
                non_printable = sum(1 for b in chunk if b < 9 or (b > 13 and b < 32))
                if non_printable / len(chunk) > 0.3:
                    return True

                return False
        except Exception:
            return False

    def _read_directory(self, dirpath: str, offset: int, limit: int) -> ToolResult:
        """读取目录内容"""
        try:
            entries = sorted(os.listdir(dirpath))
            total = len(entries)

            # 分页
            start = offset - 1
            end = start + limit
            page = entries[start:end]
            truncated = end < total

            # 格式化输出
            lines = []
            for entry in page:
                full_path = os.path.join(dirpath, entry)
                if os.path.isdir(full_path):
                    lines.append(f"{entry}/")
                else:
                    lines.append(entry)

            output = f"<path>{dirpath}</path>\n"
            output += f"<type>directory</type>\n"
            output += f"<entries>\n"
            output += "\n".join(lines)
            if truncated:
                output += f"\n\n(Showing {len(page)} of {total} entries. Use 'offset' parameter to read beyond entry {end})"
            else:
                output += f"\n\n({total} entries)"
            output += "\n</entries>"

            return ToolResult(
                output=output,
                title=str(Path(dirpath).name),
                metadata={
                    "type": "directory",
                    "path": dirpath,
                    "total_entries": total,
                    "showing": len(page),
                    "truncated": truncated,
                }
            )
        except PermissionError:
            return ToolResult(
                output=f"Error: Permission denied: {dirpath}",
                title=str(Path(dirpath).name),
                metadata={"error": "permission_denied"}
            )
        except Exception as e:
            return ToolResult(
                output=f"Error reading directory: {str(e)}",
                title=str(Path(dirpath).name),
                metadata={"error": str(e)}
            )

    def _read_file(self, filepath: str, offset: int, limit: int) -> ToolResult:
        """读取文件内容"""
        try:
            # 检查是否为二进制文件
            if self._is_binary(filepath):
                return ToolResult(
                    output=f"Cannot read binary file: {filepath}",
                    title=str(Path(filepath).name),
                    metadata={"error": "binary_file"}
                )

            # 读取文件
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()

            total_lines = len(all_lines)

            # 检查 offset 是否超出范围
            if offset > total_lines and not (total_lines == 0 and offset == 1):
                return ToolResult(
                    output=f"Offset {offset} is out of range for this file ({total_lines} lines)",
                    title=str(Path(filepath).name),
                    metadata={"error": "offset_out_of_range", "total_lines": total_lines}
                )

            # 分页读取
            start = offset - 1
            end = start + limit
            page_lines = all_lines[start:end]

            # 截断长行
            truncated_lines = []
            bytes_count = 0
            cut = False
            for line in page_lines:
                line = line.rstrip('\n')
                if len(line) > MAX_LINE_LENGTH:
                    line = line[:MAX_LINE_LENGTH] + f"... (line truncated to {MAX_LINE_LENGTH} chars)"

                line_bytes = len(line.encode('utf-8')) + 1  # +1 for newline
                if bytes_count + line_bytes > MAX_BYTES:
                    cut = True
                    break

                truncated_lines.append(line)
                bytes_count += line_bytes

            # 格式化输出
            output = f"<path>{filepath}</path>\n"
            output += f"<type>file</type>\n"
            output += "<content>\n"

            for i, line in enumerate(truncated_lines):
                line_num = offset + i
                output += f"{line_num}: {line}\n"

            last_line = offset + len(truncated_lines) - 1
            next_line = last_line + 1
            truncated = cut or (end < total_lines)

            if cut:
                output += f"\n\n(Output capped at {MAX_BYTES // 1024} KB. Showing lines {offset}-{last_line}. Use offset={next_line} to continue.)"
            elif end < total_lines:
                output += f"\n\n(Showing lines {offset}-{last_line} of {total_lines}. Use offset={next_line} to continue.)"
            else:
                output += f"\n\n(End of file - total {total_lines} lines)"
            output += "\n</content>"

            return ToolResult(
                output=output,
                title=str(Path(filepath).name),
                metadata={
                    "type": "file",
                    "path": filepath,
                    "total_lines": total_lines,
                    "showing_lines": len(truncated_lines),
                    "offset": offset,
                    "truncated": truncated,
                },
                truncated=truncated
            )
        except UnicodeDecodeError:
            return ToolResult(
                output=f"Error: Unable to decode file as UTF-8: {filepath}",
                title=str(Path(filepath).name),
                metadata={"error": "encoding_error"}
            )
        except PermissionError:
            return ToolResult(
                output=f"Error: Permission denied: {filepath}",
                title=str(Path(filepath).name),
                metadata={"error": "permission_denied"}
            )
        except Exception as e:
            return ToolResult(
                output=f"Error reading file: {str(e)}",
                title=str(Path(filepath).name),
                metadata={"error": str(e)}
            )

    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行文件读取"""
        filepath = params["filePath"]
        offset = params.get("offset", 1)
        limit = params.get("limit", DEFAULT_READ_LIMIT)

        # 解析路径
        if not os.path.isabs(filepath):
            filepath = os.path.join(ctx.cwd, filepath)
        filepath = os.path.abspath(filepath)

        # 检查路径是否存在
        if not os.path.exists(filepath):
            # 尝试查找相似文件
            parent = os.path.dirname(filepath)
            basename = os.path.basename(filepath)
            if os.path.isdir(parent):
                similar = [
                    os.path.join(parent, f)
                    for f in os.listdir(parent)
                    if basename.lower() in f.lower() or f.lower() in basename.lower()
                ][:3]
                if similar:
                    return ToolResult(
                        output=f"File not found: {filepath}\n\nDid you mean one of these?\n" + "\n".join(similar),
                        title=basename,
                        metadata={"error": "not_found", "suggestions": similar}
                    )
            return ToolResult(
                output=f"File not found: {filepath}",
                title=basename,
                metadata={"error": "not_found"}
            )

        # 根据类型分发
        if os.path.isdir(filepath):
            return self._read_directory(filepath, offset, limit)
        else:
            return self._read_file(filepath, offset, limit)

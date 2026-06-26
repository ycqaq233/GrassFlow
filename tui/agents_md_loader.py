"""
GrassFlow 上下文文件加载器

参考 hermes 的 agent/prompt_builder.py:build_context_files_prompt()，
为 GrassFlow 提供项目上下文文件的发现和加载功能。

上下文文件优先级（第一个匹配的胜出）：
1. .grassflow.md / GRASSFLOW.md - 向上查找到 git root
2. AGENTS.md / agents.md - 仅当前目录
3. CLAUDE.md / claude.md - 仅当前目录
4. .cursorrules - 仅当前目录

目录结构示例::

    my-project/
    ├── .git/
    ├── .grassflow.md          # 项目级上下文（向上查找到 git root）
    ├── AGENTS.md              # Agent 指令
    ├── CLAUDE.md              # Claude 指令
    └── .cursorrules           # Cursor 规则
"""

from __future__ import annotations

import logging
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ==================== 配置常量 ====================

# 上下文文件候选列表：(文件名, 搜索模式)
# 搜索模式：
#   "here" - 仅在 start 目录查找
#   "up"   - 向上查找到 git root
CONTEXT_FILE_CANDIDATES: List[Tuple[str, str]] = [
    (".grassflow.md", "up"),
    ("GRASSFLOW.md", "up"),
    ("AGENTS.md", "here"),
    ("agents.md", "here"),
    ("CLAUDE.md", "here"),
    ("claude.md", "here"),
    (".cursorrules", "here"),
]

# 默认最大文件大小（字符数）
DEFAULT_MAX_SIZE = 50_000

# 截断时保留头部的比例
TRUNCATE_HEAD_RATIO = 0.7

# 截断时保留尾部的比例
TRUNCATE_TAIL_RATIO = 0.2


# ==================== Git 工具 ====================


@lru_cache(maxsize=64)
def get_git_root(start_dir: Path) -> Optional[Path]:
    """获取 git 仓库根目录。

    通过检查 .git 目录向上查找，或使用 git rev-parse --show-toplevel。

    Args:
        start_dir: 起始目录

    Returns:
        git 仓库根目录，不是 git 仓库返回 None
    """
    # 方法 1：直接查找 .git（文件或目录均可，worktree 场景 .git 是文件）
    current = start_dir.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent

    # 方法 2：使用 git 命令
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_root = result.stdout.strip()
            if git_root:
                return Path(git_root)
    except (
        FileNotFoundError,  # git 未安装
        subprocess.TimeoutExpired,
        OSError,
    ):
        pass

    return None


# ==================== 文件查找 ====================


def find_context_file(
    start_dir: Path,
    git_root: Optional[Path] = None,
) -> Tuple[Optional[Path], Optional[str]]:
    """查找上下文文件。

    按照 CONTEXT_FILE_CANDIDATES 的优先级查找，第一个匹配的胜出。

    Args:
        start_dir: 起始目录
        git_root: 预计算的 git 根目录，避免重复查找

    Returns:
        (文件路径, 文件名) 元组，未找到返回 (None, None)
    """
    start = start_dir.resolve()
    if git_root is None:
        git_root = get_git_root(start)

    for filename, search_mode in CONTEXT_FILE_CANDIDATES:
        if search_mode == "here":
            # 仅在当前目录查找
            candidate = start / filename
            if candidate.is_file():
                return candidate, filename

        elif search_mode == "up":
            # 向上查找到 git root
            stop_at = git_root
            for directory in [start, *start.parents]:
                candidate = directory / filename
                if candidate.is_file():
                    return candidate, filename
                # 到达 git root 或文件系统根目录时停止
                if stop_at and directory == stop_at:
                    break

    return None, None


def load_context_file(
    start_dir: Path,
    max_size: int = DEFAULT_MAX_SIZE,
) -> Tuple[str, Optional[str]]:
    """加载上下文文件内容。

    Args:
        start_dir: 起始目录
        max_size: 最大内容大小（字符数），超过则截断

    Returns:
        (文件内容, 文件名) 元组，未找到返回 ("", None)
    """
    file_path, filename = find_context_file(start_dir)

    if file_path is None or filename is None:
        return "", None

    try:
        content = file_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to read context file %s: %s", file_path, e)
        return "", None

    if not content:
        return "", None

    # 截断过长的内容
    if len(content) > max_size:
        content = _truncate_content(content, filename, max_size)

    return content, filename


def _truncate_content(content: str, filename: str, max_size: int) -> str:
    """截断过长的内容，保留头部和尾部。

    Args:
        content: 原始内容
        filename: 文件名（用于提示信息）
        max_size: 最大字符数

    Returns:
        截断后的内容
    """
    if len(content) <= max_size:
        return content

    # 先构建 marker 获取其实际长度，再动态分配 head/tail
    placeholder_marker = (
        f"\n\n[...truncated {filename}: kept X+Y of "
        f"{len(content)} chars. The middle is omitted.]\n\n"
    )
    marker_len = len(placeholder_marker)

    available = max_size - marker_len
    head_chars = int(available * TRUNCATE_HEAD_RATIO)
    tail_chars = available - head_chars

    head = content[:head_chars]
    tail = content[-tail_chars:] if tail_chars > 0 else ""

    marker = (
        f"\n\n[...truncated {filename}: kept {head_chars}+{tail_chars} of "
        f"{len(content)} chars. The middle is omitted.]\n\n"
    )

    logger.warning(
        "Context file %s truncated: %d chars exceeds limit of %d",
        filename,
        len(content),
        max_size,
    )

    return head + marker + tail


# ==================== 提示词构建 ====================


def build_context_prompt(start_dir: Path) -> str:
    """构建格式化的上下文提示词。

    查找并加载上下文文件，返回可用于系统提示词的格式化字符串。

    Args:
        start_dir: 起始目录

    Returns:
        格式化的上下文提示词，没有上下文文件时返回空字符串
    """
    content, filename = load_context_file(start_dir)

    if not content or not filename:
        return ""

    return (
        "# Project Context\n\n"
        f"The following project context file ({filename}) has been loaded "
        "and should be followed:\n\n"
        f"## {filename}\n\n"
        f"{content}"
    )


def list_context_files(start_dir: Path) -> str:
    """列出所有发现的上下文文件（调试用）。

    检查所有候选文件是否存在，返回发现的文件列表。

    Args:
        start_dir: 起始目录

    Returns:
        格式化的文件列表字符串
    """
    start = start_dir.resolve()
    git_root = get_git_root(start)

    lines = [
        f"Context file search from: {start}",
        f"Git root: {git_root or '(not in a git repo)'}",
        "",
        "Candidate files:",
    ]

    found_any = False
    for filename, search_mode in CONTEXT_FILE_CANDIDATES:
        if search_mode == "here":
            candidate = start / filename
            if candidate.is_file():
                size = candidate.stat().st_size
                lines.append(f"  [FOUND] {filename} ({size} bytes) - {candidate}")
                found_any = True
            else:
                lines.append(f"  [----] {filename} (search: here)")

        elif search_mode == "up":
            found = False
            stop_at = git_root
            for directory in [start, *start.parents]:
                candidate = directory / filename
                if candidate.is_file():
                    size = candidate.stat().st_size
                    lines.append(f"  [FOUND] {filename} ({size} bytes) - {candidate}")
                    found = True
                    found_any = True
                    break
                if stop_at and directory == stop_at:
                    break
            if not found:
                lines.append(f"  [----] {filename} (search: up to git root)")

    if not found_any:
        lines.append("  (none found)")

    return "\n".join(lines)


# ==================== 便捷函数 ====================


def get_context_file_info(start_dir: Optional[Path] = None) -> dict:
    """获取上下文文件信息（用于状态显示）。

    Args:
        start_dir: 起始目录，默认为当前工作目录

    Returns:
        包含上下文文件信息的字典
    """
    if start_dir is None:
        start_dir = Path.cwd()

    git_root = get_git_root(start_dir)
    file_path, filename = find_context_file(start_dir, git_root=git_root)

    return {
        "found": file_path is not None,
        "filename": filename,
        "path": str(file_path) if file_path else None,
        "search_dir": str(start_dir),
        "git_root": str(git_root) if git_root else None,
    }

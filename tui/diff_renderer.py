"""
GrassFlow Diff 渲染器

参考 hermes agent/display.py render_inline_diff 模式
使用 Rich text 渲染文件差异
"""

import difflib
from typing import Optional, List, Tuple, Any
from enum import Enum

try:
    from rich.console import Console
    from rich.text import Text
    from rich.syntax import Syntax
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class DiffStyle(Enum):
    """Diff 渲染风格"""
    UNIFIED = "unified"      # 统一 diff 格式
    SPLIT = "split"           # 分栏 diff 格式
    INLINE = "inline"         # 内联 diff
    MINIMAL = "minimal"       # 极简模式 (只显示变化行)


class DiffRenderer:
    """
    文件差异渲染器

    支持多种渲染模式:
    - unified: 标准统一 diff
    - split: 左右分栏
    - inline: 内联高亮
    - minimal: 极简变化列表

    使用示例:
        renderer = DiffRenderer()
        result = renderer.render_unified(
            before="old content",
            after="new content",
            path="src/main.py",
        )
        console.print(result)
    """

    # 配色方案
    COLORS = {
        "add": "green",
        "add_bg": "on dark_green",
        "remove": "red",
        "remove_bg": "on dark_red",
        "hunk": "cyan",
        "header": "bold white",
        "path": "bold yellow",
        "context": "dim",
        "stats": "dim",
        "info": "blue",
    }

    def __init__(self, console: Optional[Any] = None, context_lines: int = 3):
        """
        初始化 Diff 渲染器

        Args:
            console: Rich Console 实例
            context_lines: 上下文行数
        """
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None
        self.context_lines = context_lines

    def render_unified(
        self,
        before: str,
        after: str,
        path: str = "",
        language: str = "",
    ) -> Any:
        """
        渲染统一 diff 格式

        Args:
            before: 修改前内容
            after: 修改后内容
            path: 文件路径
            language: 编程语言 (用于语法高亮)

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            return self._render_unified_plain(before, after, path)

        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)

        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}" if path else "a/original",
            tofile=f"b/{path}" if path else "b/modified",
        )

        text = Text()

        # 添加 diff 头部
        if path:
            text.append(f"--- a/{path}\n", style=self.COLORS["remove"])
            text.append(f"+++ b/{path}\n", style=self.COLORS["add"])

        add_count = 0
        remove_count = 0

        for line in diff:
            stripped = line.rstrip("\n")

            if line.startswith("+++") or line.startswith("---"):
                continue  # 已在头部处理
            elif line.startswith("@@"):
                text.append(f"{stripped}\n", style=self.COLORS["hunk"])
            elif line.startswith("+"):
                text.append(f"{stripped}\n", style=self.COLORS["add"])
                add_count += 1
            elif line.startswith("-"):
                text.append(f"{stripped}\n", style=self.COLORS["remove"])
                remove_count += 1
            else:
                text.append(f"{stripped}\n", style=self.COLORS["context"])

        # 添加统计信息
        stats = Text(f"\n{add_count} additions, {remove_count} deletions", style=self.COLORS["stats"])
        text.append(stats)

        # 用 Panel 包裹
        return Panel(
            text,
            title=f"[bold]Diff: {path}[/bold]" if path else "[bold]Diff[/bold]",
            border_style="dim",
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def render_split(
        self,
        before: str,
        after: str,
        path: str = "",
        max_width: int = 120,
    ) -> Any:
        """
        渲染分栏 diff

        Args:
            before: 修改前内容
            after: 修改后内容
            path: 文件路径
            max_width: 最大宽度

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            return self._render_unified_plain(before, after, path)

        before_lines = before.splitlines()
        after_lines = after.splitlines()

        # 使用 SequenceMatcher 获取对齐的行
        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
        opcodes = matcher.get_opcodes()

        table = Table(
            show_header=True,
            header_style="bold",
            box=box.SIMPLE,
            show_lines=False,
            padding=(0, 1),
            width=max_width,
        )
        table.add_column("Before", style=self.COLORS["remove"], ratio=1)
        table.add_column("After", style=self.COLORS["add"], ratio=1)

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                for k in range(i1, i2):
                    table.add_row(
                        Text(before_lines[k], style=self.COLORS["context"]),
                        Text(after_lines[j1 + k - i1], style=self.COLORS["context"]),
                    )
            elif tag == "replace":
                # 显示替换的行
                max_len = max(i2 - i1, j2 - j1)
                for k in range(max_len):
                    before_text = Text(before_lines[i1 + k], style=self.COLORS["remove"]) if i1 + k < i2 else Text("")
                    after_text = Text(after_lines[j1 + k], style=self.COLORS["add"]) if j1 + k < j2 else Text("")
                    table.add_row(before_text, after_text)
            elif tag == "delete":
                for k in range(i1, i2):
                    table.add_row(
                        Text(before_lines[k], style=self.COLORS["remove"]),
                        Text(""),
                    )
            elif tag == "insert":
                for k in range(j1, j2):
                    table.add_row(
                        Text(""),
                        Text(after_lines[k], style=self.COLORS["add"]),
                    )

        title = f"[bold]Diff: {path}[/bold]" if path else "[bold]Split Diff[/bold]"
        return Panel(table, title=title, border_style="dim", box=box.ROUNDED)

    def render_inline(
        self,
        before: str,
        after: str,
        path: str = "",
    ) -> Any:
        """
        渲染内联 diff (高亮变化字符)

        Args:
            before: 修改前内容
            after: 修改后内容
            path: 文件路径

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            return self._render_unified_plain(before, after, path)

        before_lines = before.splitlines()
        after_lines = after.splitlines()

        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
        opcodes = matcher.get_opcodes()

        result = Text()

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                for k in range(i1, i2):
                    result.append(f"  {before_lines[k]}\n", style=self.COLORS["context"])
            elif tag == "replace":
                # 显示被替换的行，带字符级高亮
                for k in range(max(i2 - i1, j2 - j1)):
                    old = before_lines[i1 + k] if i1 + k < i2 else ""
                    new = after_lines[j1 + k] if j1 + k < j2 else ""

                    if old:
                        result.append("- ", style=self.COLORS["remove"])
                        result.append(self._inline_char_diff(old, new), style=self.COLORS["remove"])
                        result.append("\n")
                    if new:
                        result.append("+ ", style=self.COLORS["add"])
                        result.append(self._inline_char_diff(new, old, is_add=True), style=self.COLORS["add"])
                        result.append("\n")
            elif tag == "delete":
                for k in range(i1, i2):
                    result.append(f"- {before_lines[k]}\n", style=self.COLORS["remove"])
            elif tag == "insert":
                for k in range(j1, j2):
                    result.append(f"+ {after_lines[k]}\n", style=self.COLORS["add"])

        title = f"[bold]Inline Diff: {path}[/bold]" if path else "[bold]Inline Diff[/bold]"
        return Panel(result, title=title, border_style="dim", box=box.ROUNDED)

    def render_minimal(
        self,
        before: str,
        after: str,
        path: str = "",
    ) -> Any:
        """
        渲染极简 diff (只显示变化行)

        Args:
            before: 修改前内容
            after: 修改后内容
            path: 文件路径

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            return self._render_unified_plain(before, after, path)

        before_lines = before.splitlines()
        after_lines = after.splitlines()

        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
        opcodes = matcher.get_opcodes()

        result = Text()
        add_count = 0
        remove_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                continue  # 极简模式跳过相同行

            # 显示上下文行
            for k in range(max(0, i1 - self.context_lines), i1):
                if k >= 0:
                    result.append(f"  {before_lines[k]}\n", style=self.COLORS["context"])

            if tag == "replace":
                for k in range(i1, i2):
                    result.append(f"- {before_lines[k]}\n", style=self.COLORS["remove"])
                    remove_count += 1
                for k in range(j1, j2):
                    result.append(f"+ {after_lines[k]}\n", style=self.COLORS["add"])
                    add_count += 1
            elif tag == "delete":
                for k in range(i1, i2):
                    result.append(f"- {before_lines[k]}\n", style=self.COLORS["remove"])
                    remove_count += 1
            elif tag == "insert":
                for k in range(j1, j2):
                    result.append(f"+ {after_lines[k]}\n", style=self.COLORS["add"])
                    add_count += 1

            # 显示后文行
            for k in range(i2, min(i2 + self.context_lines, len(before_lines))):
                result.append(f"  {before_lines[k]}\n", style=self.COLORS["context"])

        # 统计信息
        stats = f"\n{add_count}+ {remove_count}-"
        result.append(stats, style=self.COLORS["stats"])

        title = f"[bold]Changes: {path}[/bold]" if path else "[bold]Changes[/bold]"
        return Panel(result, title=title, border_style="dim", box=box.ROUNDED)

    def render_stats(
        self,
        before: str,
        after: str,
        path: str = "",
    ) -> Any:
        """
        渲染 diff 统计信息 (类似 git diff --stat)

        Args:
            before: 修改前内容
            after: 修改后内容
            path: 文件路径

        Returns:
            Rich renderable 对象
        """
        before_lines = before.splitlines()
        after_lines = after.splitlines()

        matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
        opcodes = matcher.get_opcodes()

        add_count = 0
        remove_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "replace":
                add_count += j2 - j1
                remove_count += i2 - i1
            elif tag == "insert":
                add_count += j2 - j1
            elif tag == "delete":
                remove_count += i2 - i1

        if not HAS_RICH:
            plus = "+" * min(add_count, 20)
            minus = "-" * min(remove_count, 20)
            return f" {path} | {add_count + remove_count} {plus}{minus}"

        # 构建小进度条
        total = add_count + remove_count
        if total == 0:
            bar = Text("unchanged", style="dim")
        else:
            bar_width = max(1, min(20, total))
            add_width = max(0, int(add_count / total * bar_width)) if total > 0 else 0
            remove_width = bar_width - add_width

            bar = Text()
            bar.append("+" * add_width, style=self.COLORS["add"])
            bar.append("-" * remove_width, style=self.COLORS["remove"])

        display_name = path if path else "file"
        stat_text = Text()
        stat_text.append(f" {display_name} ", style=self.COLORS["path"])
        stat_text.append("│ ", style="dim")
        stat_text.append(f"{add_count}+ {remove_count}- ", style=self.COLORS["info"])
        stat_text.append(bar)

        return stat_text

    def _inline_char_diff(self, text: str, other: str, is_add: bool = False) -> Text:
        """
        字符级内联差异高亮

        Args:
            text: 要高亮的文本
            other: 对比文本
            is_add: 是否为新增行

        Returns:
            Rich Text 对象
        """
        result = Text()

        if not other:
            result.append(text)
            return result

        matcher = difflib.SequenceMatcher(None, text, other)
        opcodes = matcher.get_opcodes()

        highlight_style = self.COLORS["add_bg"] if is_add else self.COLORS["remove_bg"]

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                result.append(text[i1:i2])
            elif tag in ("replace", "delete" if is_add else "insert"):
                # 高亮变化的字符
                result.append(text[i1:i2], style=highlight_style)

        return result

    def _render_unified_plain(self, before: str, after: str, path: str = "") -> str:
        """纯文本渲染"""
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)

        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}" if path else "a/original",
            tofile=f"b/{path}" if path else "b/modified",
        )

        return "\n".join(line.rstrip("\n") for line in diff)

    def render_changes_list(self, changes: List[Tuple[str, str, str]]) -> Any:
        """
        渲染多个文件的变化列表

        Args:
            changes: [(path, before_content, after_content), ...] 列表

        Returns:
            Rich renderable 对象
        """
        if not HAS_RICH:
            output = []
            for path, before, after in changes:
                output.append(self._render_unified_plain(before, after, path))
                output.append("")
            return "\n".join(output)

        panels = []
        for path, before, after in changes:
            panels.append(self.render_minimal(before, after, path))

        if not panels:
            return Text("No changes", style="dim")

        from rich.columns import Columns
        if len(panels) == 1:
            return panels[0]

        return Columns(panels)


# 便捷函数
_diff_renderer = DiffRenderer()


def render_diff(
    before: str,
    after: str,
    path: str = "",
    style: DiffStyle = DiffStyle.UNIFIED,
) -> Any:
    """
    便捷的 diff 渲染函数

    Args:
        before: 修改前内容
        after: 修改后内容
        path: 文件路径
        style: 渲染风格

    Returns:
        渲染结果 (Rich renderable 或字符串)
    """
    if style == DiffStyle.UNIFIED:
        return _diff_renderer.render_unified(before, after, path)
    elif style == DiffStyle.SPLIT:
        return _diff_renderer.render_split(before, after, path)
    elif style == DiffStyle.INLINE:
        return _diff_renderer.render_inline(before, after, path)
    elif style == DiffStyle.MINIMAL:
        return _diff_renderer.render_minimal(before, after, path)
    else:
        return _diff_renderer.render_unified(before, after, path)

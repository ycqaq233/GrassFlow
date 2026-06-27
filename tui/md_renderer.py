"""
GrassFlow Markdown Renderer — terminal markdown rendering using Rich

Converts markdown text to ANSI-colored terminal output using Rich's built-in
Markdown renderer. Used to render assistant responses in the REPL.

Key design:
- Raw markdown is kept in _conversation_history (for LLM context)
- Rendered ANSI output is displayed in terminal via cprint()
- Uses Rich's Markdown class for full GFM support (headers, bold, italic,
  code blocks, lists, blockquotes, links, tables, etc.)
"""

from __future__ import annotations

import re
import shutil
from typing import Optional


# ANSI escape pattern for stripping
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


def render_markdown_to_ansi(
    text: str,
    width: Optional[int] = None,
    indent: int = 0,
) -> str:
    """Render markdown text to ANSI-colored terminal string using Rich.

    Args:
        text: Raw markdown text to render.
        width: Terminal width for wrapping. Auto-detected if None.
        indent: Number of spaces to prepend to each output line.

    Returns:
        ANSI-colored string suitable for cprint() output.
        Returns raw text if Rich is not available.
    """
    if not text or not text.strip():
        return text

    try:
        from io import StringIO
        from rich.console import Console
        from rich.markdown import Markdown

        if width is None:
            width = shutil.get_terminal_size((80, 24)).columns
            # Account for the 4-space indent used in assistant output
            width = max(width - 4 - indent, 40)

        buf = StringIO()
        console = Console(
            file=buf,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
            width=width,
        )
        console.print(Markdown(text))
        output = buf.getvalue()
        # Strip trailing newlines from Rich output
        output = output.rstrip("\n")

        # Apply indent if requested
        if indent > 0:
            prefix = " " * indent
            lines = output.split("\n")
            output = "\n".join(prefix + line for line in lines)

        return output
    except ImportError:
        # Rich not available, return raw text
        return text
    except Exception:
        # Any rendering error, return raw text
        return text

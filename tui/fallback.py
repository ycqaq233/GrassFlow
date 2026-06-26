"""
GrassFlow 降级 REPL 模式

当 prompt_toolkit Application 无法创建时（如 Windows Git Bash / mintty / 非全屏终端），
使用 input() + Rich Console 实现简单的交互式 REPL。

从 tui/repl.py 的 GrassFlowREPL._run_fallback() 方法提取而来。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional

from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel

# ==================== 常量 ====================

PROMPT = "❯ "

BANNER = r"""
  ____                 _     _____ _
 / ___|_ __ __ _  ___ | |__ |  ___| | _____      __
| |  _| '__/ _` |/ __|| '_ \| |_  | |/ _ \ \ /\ / /
| |_| | | | (_| |\__ \| | | |  _| | | (_) \ V  V /
 \____|_|  \__,_||___/|_| |_|_|   |_|\___/ \_/\_/
"""


def _setup_utf8_encoding() -> None:
    """修复 Windows 终端编码问题，确保 UTF-8 输出正常"""
    if sys.platform == "win32":
        try:
            # 设置 stdout/stderr 为 UTF-8
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        # 设置环境变量（子进程也会继承）
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _get_help_text() -> str:
    """获取降级模式的命令帮助文本"""
    lines = [
        "Available commands:",
        "",
        "  /help       - Show this help",
        "  /clear      - Clear screen",
        "  /exit       - Exit REPL",
        "  /quit       - Exit REPL (alias)",
        "  /q          - Exit REPL (alias)",
    ]
    return "\n".join(lines)


async def _consume_agent_stream(
    agent_loop: Any,
    user_input: str,
    console: RichConsole,
) -> None:
    """消费 Agent Loop 的流式输出，使用 Rich Console 渲染

    Args:
        agent_loop: AgentLoop 实例，提供 process_streaming() 方法
        user_input: 用户输入文本
        console: Rich Console 实例
    """
    full_text = ""
    thinking_shown = False

    async for event in agent_loop.process_streaming(user_input):
        etype = event.type
        edata = event.data

        if etype in ("text_delta",):
            token = edata.get("text", "")
            full_text += token
            console.print(token, end="", highlight=False)

        elif etype == "thinking_delta":
            token = edata.get("text", "")
            if not full_text and not thinking_shown:
                console.print("  [dim italic]思考中...[/dim italic]")
                thinking_shown = True

        elif etype == "tool_call_start":
            name = edata.get("name", "?")
            args = edata.get("args", {})
            args_str = json.dumps(args, ensure_ascii=False)[:200] if args else ""
            console.print(
                f"\n  [bold yellow][tool] Calling {name}[/bold yellow]",
                highlight=False,
            )
            if args_str:
                console.print(
                    f"  [dim]  args: {args_str}[/dim]",
                    highlight=False,
                )

        elif etype == "tool_result":
            result = edata.get("result", edata.get("output", ""))
            is_err = edata.get("is_error", edata.get("success", True) is False)
            style = "bold red" if is_err else "dim"
            result_preview = str(result)[:500]
            console.print(
                f"  [{style}][tool result] {result_preview}[/{style}]",
                highlight=False,
            )

        elif etype == "error":
            msg = edata.get("message", str(edata))
            console.print(
                f"\n  [bold red][error] {msg}[/bold red]",
                highlight=False,
            )

        elif etype == "interrupted":
            console.print(
                "\n  [yellow]Interrupted.[/yellow]",
                highlight=False,
            )


def run_fallback_mode(
    agent_integration: Any = None,
    session_manager: Any = None,
    theme: Any = None,
    notice: str = "",
) -> None:
    """运行降级 REPL 模式

    当 prompt_toolkit 的 Application 无法创建时（Windows Git Bash / mintty / 非全屏终端），
    使用 input() + Rich Console 实现简单的交互式 REPL。

    Args:
        agent_integration: AgentLoop 实例，提供 process_streaming() 方法。
                           如果为 None，则进入回显模式。
        session_manager: 会话管理器（当前未使用，预留接口）。
        theme: REPLTheme 实例（当前未使用，预留接口）。
        notice: 显示给用户的通知信息。
    """
    # 修复 Windows 编码
    _setup_utf8_encoding()

    # 使用 Rich Console 渲染
    console = RichConsole(highlight=False)

    # 显示 banner 和通知
    console.print(Panel.fit(BANNER.strip(), style="bold cyan", title="GrassFlow REPL"))
    if notice:
        console.print(f"  [dim yellow]{notice}[/dim yellow]")
    console.print("  [dim]Type /help for commands, /exit to quit.[/dim]")
    console.print()

    # 主循环
    running = True
    while running:
        try:
            user_input = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("\n  Goodbye!")
            break

        stripped = user_input.strip()
        if not stripped:
            continue

        # 处理退出命令
        if stripped in ("/exit", "/quit", "/q"):
            console.print("  Goodbye!")
            break

        # 处理清屏命令
        if stripped in ("/clear", "/cls"):
            console.clear()
            continue

        # 处理帮助命令
        if stripped == "/help":
            console.print(Markdown(_get_help_text()))
            continue

        # 流式调用 Agent Loop
        console.print()
        console.print(f"[bold blue]{PROMPT}[/bold blue]{stripped}")

        if agent_integration:
            try:
                asyncio.run(_consume_agent_stream(agent_integration, stripped, console))
                console.print()  # 换行
            except KeyboardInterrupt:
                console.print("\n  [yellow]Interrupted.[/yellow]")
            except Exception as e:
                console.print(f"\n[bold red]Error: {e}[/bold red]")
        else:
            # 无 Agent Loop，回显模式
            console.print(f"  {stripped}")

        console.print()

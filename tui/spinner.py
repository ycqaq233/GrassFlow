"""
GrassFlow 加载动画组件

参考 hermes KawaiiSpinner 设计，支持多种动画风格
- dots: 点状动画 "..."
- line: 线状扫动 "▁▂▃▄▅▆▇█"
- pulse: 脉冲动画 "█▓▒░"
- bounce: 弹跳球动画
- braille: Braille 字符旋转动画
- clock: 时钟动画
- moon: 月相动画
- arrow: 箭头旋转
"""

import time
import asyncio
from typing import Optional, List, Any, Iterator
from enum import Enum

try:
    from rich.console import Console
    from rich.text import Text
    from rich.live import Live
    from rich.spinner import Spinner as RichSpinner
    from rich.panel import Panel
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class SpinnerStyle(Enum):
    """加载动画风格"""
    DOTS = "dots"              # . .. ...
    LINE = "line"              # ▁▂▃▄▅▆▇█
    PULSE = "pulse"            # █▓▒░
    BOUNCE = "bounce"          # 弹跳球
    BRAILLE = "braille"        # Braille spinner
    CLOCK = "clock"            # 时钟
    MOON = "moon"              # 月相
    ARROW = "arrow"            # 箭头旋转
    SIMPLE = "simple"          # 简单 |
    DOTS2 = "dots2"            # ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏
    DOTS3 = "dots3"            # ⣾⣽⣻⢿⡿⣟⣯⣷
    DOTS4 = "dots4"            # ◐◓◑◒
    DOTS5 = "dots5"            # ◴◷◶◵
    DOTS6 = "dots6"            # ◡◡⊙⊙◠◠
    GROW = "grow"              # ▏▎▍▌▋▊▉█▉▊▋▌▍▎▏
    SHRINK = "shrink"          # █▉▊▋▌▍▎▏▎▍▌▋▊▉█


class GrassSpinner:
    """
    终端加载动画

    多风格支持：
    - dots: 经典点状 "...", "..", ".", ""
    - line: 水平扫描线
    - pulse: 脉冲心跳
    - bounce: 弹跳小球
    - braille: Braille 字符旋转 (rich 风格)
    - moon: 月相变化
    - arrow: 旋转箭头

    使用示例:
        spinner = GrassSpinner(style=SpinnerStyle.DOTS)
        for frame in spinner.animate("Thinking..."):
            print(f"\r{frame}", end="", flush=True)
            time.sleep(0.1)

    异步使用:
        spinner = GrassSpinner(style=SpinnerStyle.PULSE)
        async for frame in spinner.animate_async("Loading..."):
            sys.stdout.write(f"\r{frame}")
            sys.stdout.flush()
            await asyncio.sleep(0.1)
    """

    # 动画帧定义
    FRAMES = {
        SpinnerStyle.DOTS: ["   ", ".  ", ".. ", "..."],
        SpinnerStyle.DOTS2: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        SpinnerStyle.DOTS3: ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"],
        SpinnerStyle.DOTS4: ["◐", "◓", "◑", "◒"],
        SpinnerStyle.DOTS5: ["◴", "◷", "◶", "◵"],
        SpinnerStyle.DOTS6: ["◡", "⊙", "◠"],
        SpinnerStyle.LINE: ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"],
        SpinnerStyle.PULSE: ["█", "▓", "▒", "░", "▒", "▓"],
        SpinnerStyle.BRAILLE: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        SpinnerStyle.ARROW: ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
        SpinnerStyle.CLOCK: ["🕛", "🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚"],
        SpinnerStyle.SIMPLE: ["|", "/", "-", "\\"],
        SpinnerStyle.GROW: ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█", "▉", "▊", "▋", "▌", "▍", "▎", "▏"],
        SpinnerStyle.SHRINK: ["█", "▉", "▊", "▋", "▌", "▍", "▎", "▏", "▎", "▍", "▌", "▋", "▊", "▉"],
    }

    # 月相帧
    MOON_FRAMES = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]

    # 弹跳球帧
    BOUNCE_FRAMES: List[str] = []
    for _bounce_height in [0, 1, 2, 3, 2, 1, 0]:
        _frame = " " * _bounce_height + "●"
        BOUNCE_FRAMES.append(_frame)

    FRAMES[SpinnerStyle.MOON] = MOON_FRAMES
    FRAMES[SpinnerStyle.BOUNCE] = BOUNCE_FRAMES

    # 颜色方案
    COLORS = {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "thinking": "magenta",
        "loading": "blue",
        "processing": "cyan",
    }

    def __init__(
        self,
        style: SpinnerStyle = SpinnerStyle.DOTS,
        color: str = "cyan",
        interval: float = 0.1,
    ):
        """
        初始化加载动画

        Args:
            style: 动画风格
            color: 颜色 (rich 颜色名)
            interval: 帧间隔 (秒)
        """
        self.style = style
        self.color = color
        self.interval = interval
        self._index = 0
        self._start_time = 0.0

    @property
    def frames(self) -> List[str]:
        """获取当前风格的帧列表"""
        return self.FRAMES.get(self.style, self.FRAMES[SpinnerStyle.DOTS])

    def reset(self) -> None:
        """重置动画状态"""
        self._index = 0
        self._start_time = time.time()

    def next_frame(self) -> str:
        """
        获取下一帧

        Returns:
            下一帧字符
        """
        frames = self.frames
        frame = frames[self._index % len(frames)]
        self._index += 1
        return frame

    def current_frame(self) -> str:
        """获取当前帧 (不前进)"""
        frames = self.frames
        return frames[self._index % len(frames)]

    def animate(self, text: str = "", prefix: str = "", suffix: str = "") -> Iterator[str]:
        """
        同步动画迭代器

        Args:
            text: 伴随文本
            prefix: 前缀
            suffix: 后缀

        Yields:
            每帧的完整渲染字符串
        """
        self.reset()
        while True:
            frame = self.next_frame()

            parts = []
            if prefix:
                parts.append(prefix)
            parts.append(frame)
            if text:
                parts.append(f" {text}")
            if suffix:
                parts.append(suffix)

            yield "".join(parts)

    async def animate_async(
        self,
        text: str = "",
        prefix: str = "",
        suffix: str = "",
    ):
        """
        异步动画迭代器

        Args:
            text: 伴随文本
            prefix: 前缀
            suffix: 后缀

        Yields:
            每帧的完整渲染字符串
        """
        self.reset()
        while True:
            frame = self.next_frame()

            parts = []
            if prefix:
                parts.append(prefix)
            parts.append(frame)
            if text:
                parts.append(f" {text}")
            if suffix:
                parts.append(suffix)

            yield "".join(parts)
            await asyncio.sleep(self.interval)

    def render_frame(self, text: str = "") -> Text:
        """
        渲染 Rich Text 帧

        Args:
            text: 伴随文本

        Returns:
            Rich Text 对象
        """
        if not HAS_RICH:
            frame = self.next_frame()
            return Text(f"{frame} {text}" if text else frame)

        frame = self.next_frame()
        color = self.COLORS.get(self.color, self.color)

        result = Text()
        result.append(frame, style=color)
        if text:
            result.append(f" {text}", style="dim")
        return result


class SpinnerManager:
    """
    加载动画管理器

    支持 Live 刷新，可以动态更新文本

    使用示例:
        manager = SpinnerManager(style=SpinnerStyle.PULSE)
        with manager.live("Processing..."):
            # 做一些工作
            manager.update_text("Almost done...")
            time.sleep(1)
            manager.update_text("Done!", color="green")
    """

    def __init__(
        self,
        style: SpinnerStyle = SpinnerStyle.BRAILLE,
        console: Optional[Any] = None,
        color: str = "cyan",
        interval: float = 0.08,
    ):
        """
        初始化加载动画管理器

        Args:
            style: 动画风格
            console: Rich Console 实例
            color: 颜色
            interval: 帧间隔
        """
        self.spinner = GrassSpinner(style=style, color=color, interval=interval)
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None
        self._text = ""
        self._live: Optional[Any] = None
        self._running = False

    def update_text(self, text: str, color: Optional[str] = None) -> None:
        """
        更新显示文本

        Args:
            text: 新文本
            color: 颜色覆盖
        """
        self._text = text
        if color:
            self.spinner.color = color

    def _render(self) -> Any:
        """渲染当前帧 (供 Live 使用)"""
        return self.spinner.render_frame(self._text)

    def live(self, text: str = ""):
        """
        创建 Live 上下文管理器

        Args:
            text: 初始文本

        Yields:
            Live 实例
        """
        self._text = text

        if HAS_RICH:
            from rich.live import Live as RichLive

            def render():
                return self.spinner.render_frame(self._text)

            with RichLive(render(), console=self.console, refresh_per_second=10) as live:
                self._live = live
                self._running = True
                yield self
                self._running = False
        else:
            self._running = True
            yield self
            self._running = False

    def stop(self, final_text: str = "", color: str = "green") -> None:
        """
        停止动画并显示最终文本

        Args:
            final_text: 最终文本
            color: 最终颜色
        """
        self._running = False
        if final_text and self.console and HAS_RICH:
            self.console.print(Text(final_text, style=self.COLORS.get(color, color)))


class KawaiiSpinner(GrassSpinner):
    """
    Kawaii 风格加载动画 (致敬 hermes)

    使用日式颜文字作为加载动画
    """

    KAWAII_FACES = [
        "(・∀・)",
        "(◕‿◕)",
        "(◕ᴗ◕✿)",
        "(◠‿◠)",
        "(｡♥‿♥｡)",
        "(◡ ω ◡)",
        "(✿◕‿◕)",
        "(◍•ᴗ•◍)",
        "(✧ω✧)",
        "(◕‿◕✿)",
        "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
        "(づ｡◕‿‿◕｡)づ",
        "☆*:.｡.o(≧▽≦)o.｡.:*☆",
    ]

    def __init__(self, interval: float = 0.3):
        super().__init__(style=SpinnerStyle.DOTS, color="magenta", interval=interval)
        self._faces = self.KAWAAI_FACES

    @property
    def frames(self) -> List[str]:
        return self._faces

    def set_mood(self, mood: str = "happy") -> None:
        """
        设置表情心情

        Args:
            mood: 心情 (happy, excited, love, shy, default)
        """
        mood_faces = {
            "happy": ["(・∀・)", "(◕‿◕)", "(◠‿◠)", "(◡ ω ◡)"],
            "excited": ["☆*:.｡.o(≧▽≦)o.｡.:*☆", "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", "(✧ω✧)"],
            "love": ["(｡♥‿♥｡)", "(◕ᴗ◕✿)", "(✿◕‿◕)", "(◍•ᴗ•◍)"],
            "shy": ["(〃ω〃)", "(⁄ ⁄>⁄ ▽ ⁄<⁄ ⁄)", "(´｡• ᵕ •｡`)"],
            "thinking": ["(￣～￣)", "(´-ω-`)", "(￣ω￣)", "(・_・;)"],
        }
        self._faces = mood_faces.get(mood, self.KAWAAI_FACES)
        self._index = 0


class MultiSpinner:
    """
    多行加载动画

    同时显示多个进度条/动画，适用于并行 agent 执行场景

    使用示例:
        multi = MultiSpinner()
        multi.add("agent_1", "research", SpinnerStyle.DOTS)
        multi.add("agent_2", "analyze", SpinnerStyle.PULSE)

        for frame in multi.animate():
            print(frame)
            time.sleep(0.1)
    """

    def __init__(self, max_columns: int = 80):
        self.max_columns = max_columns
        self._spinners: dict = {}
        self._texts: dict = {}
        self._statuses: dict = {}
        self._colors: dict = {}

    def add(
        self,
        name: str,
        text: str = "",
        style: SpinnerStyle = SpinnerStyle.DOTS,
        color: str = "cyan",
    ) -> None:
        """
        添加一个动画项

        Args:
            name: 项名称
            text: 显示文本
            style: 动画风格
            color: 颜色
        """
        self._spinners[name] = GrassSpinner(style=style, color=color)
        self._texts[name] = text
        self._statuses[name] = "running"
        self._colors[name] = color

    def update(self, name: str, text: str = "", status: Optional[str] = None) -> None:
        """
        更新一个动画项

        Args:
            name: 项名称
            text: 新文本
            status: 新状态 (running, done, error, skipped)
        """
        if name in self._texts:
            self._texts[name] = text
        if status and name in self._statuses:
            self._statuses[name] = status

    def remove(self, name: str) -> None:
        """移除一个动画项"""
        self._spinners.pop(name, None)
        self._texts.pop(name, None)
        self._statuses.pop(name, None)
        self._colors.pop(name, None)

    def animate(self) -> Iterator[str]:
        """
        多行动画迭代器

        Yields:
            渲染字符串
        """
        status_icons = {
            "running": "",
            "done": "[green]✓[/green]",
            "error": "[red]✗[/red]",
            "skipped": "[dim]○[/dim]",
        }

        while True:
            lines = []
            for name in list(self._spinners.keys()):
                spinner = self._spinners[name]
                text = self._texts.get(name, "")
                status = self._statuses.get(name, "running")
                color = self._colors.get(name, "cyan")

                # 根据状态选择帧
                if status == "running":
                    frame = spinner.next_frame()
                    icon = f"[{color}]{frame}[/{color}]"
                else:
                    icon = status_icons.get(status, "")

                line = f"  {icon} {name}"
                if text:
                    line += f": {text}"
                lines.append(line)

            yield "\n".join(lines)


# 便捷的上下文管理器
class SpinnerContext:
    """
    Spinner 上下文管理器，用于 with 语句

    with SpinnerContext("Processing...", style=SpinnerStyle.PULSE):
        do_work()

    自动处理开始/停止，支持异常显示
    """

    def __init__(
        self,
        text: str = "Working...",
        style: SpinnerStyle = SpinnerStyle.BRAILLE,
        color: str = "cyan",
        success_text: str = "Done!",
        error_text: str = "Failed!",
        console: Optional[Any] = None,
    ):
        self.text = text
        self.style = style
        self.color = color
        self.success_text = success_text
        self.error_text = error_text
        self.manager = SpinnerManager(style=style, color=color, console=console)
        self._exc_type = None

    def __enter__(self):
        self.manager.live(self.text).__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.manager.stop(f"[{self.manager.spinner.color}]{self.error_text}: {exc_val}[/{self.manager.spinner.color}]", self.manager.spinner.color)
        else:
            self.manager.stop(f"[green]{self.success_text}[/green]", "green")
        self.manager._live.__exit__(exc_type, exc_val, exc_tb)
        return False

    def update(self, text: str) -> None:
        """更新显示文本"""
        self.manager.update_text(text)


# 便捷函数
def create_spinner(style: str = "braille", color: str = "cyan") -> GrassSpinner:
    """
    创建加载动画的便捷函数

    Args:
        style: 风格名称 ("dots", "line", "pulse", "bounce", "braille", "moon", "arrow" 等)
        color: 颜色

    Returns:
        GrassSpinner 实例
    """
    style_map = {
        s.value: s for s in SpinnerStyle
    }
    spinner_style = style_map.get(style, SpinnerStyle.DOTS)
    return GrassSpinner(style=spinner_style, color=color)

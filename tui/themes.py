"""
GrassFlow 主题/皮肤系统

参考 Hermes ``hermes_cli/skin_engine.py`` 实现，适配为 GrassFlow 的风格。
使用 Rich 的 Style 类格式化输出，支持内置主题和用户自定义主题。

设计原则：
- 数据驱动：主题是纯数据，不需要修改代码
- 可扩展：支持用户自定义主题文件（YAML/JSON）
- Rich 集成：样式直接映射到 Rich 的 Style 字符串
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 主题数据结构
# =============================================================================

@dataclass
class GrassFlowTheme:
    """主题配置

    参考 Hermes SkinConfig，简化为 GrassFlow 需要的字段。
    所有颜色使用 hex 格式（#RRGGBB），与 Rich 兼容。
    """
    name: str
    description: str = ""

    # 颜色
    primary: str = "#FFBF00"        # 主色
    success: str = "#4caf50"        # 成功
    error: str = "#ef5350"          # 错误
    warning: str = "#ff9800"        # 警告
    info: str = "#2196f3"           # 信息
    dim: str = "#666666"            # 暗淡/次要文本

    # 额外颜色（用于更丰富的 UI）
    accent: str = "#FFBF00"         # 强调色
    title: str = "#FFD700"          # 标题色
    text: str = "#c9d1d9"           # 正文色
    border: str = "#CD7F32"         # 边框色
    label: str = "#DAA520"          # 标签色

    # UI 元素
    code_theme: str = "monokai"        # Rich Syntax 高亮主题
    prompt_symbol: str = "❯"
    spinner_style: str = "dots"
    tool_prefix: str = "┊"

    # 状态栏
    status_bg: str = "#1a1a2e"
    status_text: str = "#C0C0C0"
    status_strong: str = "#FFD700"
    status_dim: str = "#8B8682"
    status_good: str = "#8FBC8F"
    status_warn: str = "#FFD700"
    status_bad: str = "#FF8C00"
    status_critical: str = "#FF6B6B"

    def get_color(self, key: str, fallback: str = "") -> str:
        """获取颜色值，支持 fallback"""
        return getattr(self, key, fallback) if hasattr(self, key) else fallback

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "colors": {
                "primary": self.primary,
                "success": self.success,
                "error": self.error,
                "warning": self.warning,
                "info": self.info,
                "dim": self.dim,
                "accent": self.accent,
                "title": self.title,
                "text": self.text,
                "border": self.border,
                "label": self.label,
                "status_bg": self.status_bg,
                "status_text": self.status_text,
                "status_strong": self.status_strong,
                "status_dim": self.status_dim,
                "status_good": self.status_good,
                "status_warn": self.status_warn,
                "status_bad": self.status_bad,
                "status_critical": self.status_critical,
            },
            "ui": {
                "code_theme": self.code_theme,
                "prompt_symbol": self.prompt_symbol,
                "spinner_style": self.spinner_style,
                "tool_prefix": self.tool_prefix,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GrassFlowTheme":
        """从字典反序列化"""
        colors = data.get("colors", {})
        ui = data.get("ui", {})
        return cls(
            name=data.get("name", "unknown"),
            description=data.get("description", ""),
            primary=colors.get("primary", "#FFBF00"),
            success=colors.get("success", "#4caf50"),
            error=colors.get("error", "#ef5350"),
            warning=colors.get("warning", "#ff9800"),
            info=colors.get("info", "#2196f3"),
            dim=colors.get("dim", "#666666"),
            accent=colors.get("accent", "#FFBF00"),
            title=colors.get("title", "#FFD700"),
            text=colors.get("text", "#c9d1d9"),
            border=colors.get("border", "#CD7F32"),
            label=colors.get("label", "#DAA520"),
            code_theme=ui.get("code_theme", "monokai"),
            prompt_symbol=ui.get("prompt_symbol", "❯"),
            spinner_style=ui.get("spinner_style", "dots"),
            tool_prefix=ui.get("tool_prefix", "┊"),
            status_bg=colors.get("status_bg", "#1a1a2e"),
            status_text=colors.get("status_text", "#C0C0C0"),
            status_strong=colors.get("status_strong", "#FFD700"),
            status_dim=colors.get("status_dim", "#8B8682"),
            status_good=colors.get("status_good", "#8FBC8F"),
            status_warn=colors.get("status_warn", "#FFD700"),
            status_bad=colors.get("status_bad", "#FF8C00"),
            status_critical=colors.get("status_critical", "#FF6B6B"),
        )

    def get_rich_style(self) -> "RichStyle":
        """生成 Rich Style 对象"""
        from rich.style import Style
        return RichStyle(self)


# =============================================================================
# Rich 样式包装
# =============================================================================

class RichStyle:
    """Rich Style 包装器

    将 GrassFlowTheme 的颜色映射为 Rich 的 Style 字符串格式。
    """

    def __init__(self, theme: GrassFlowTheme):
        self._theme = theme

    def primary(self, bold: bool = False) -> str:
        return self._build_style(self._theme.primary, bold)

    def success(self, bold: bool = False) -> str:
        return self._build_style(self._theme.success, bold)

    def error(self, bold: bool = False) -> str:
        return self._build_style(self._theme.error, bold)

    def warning(self, bold: bool = False) -> str:
        return self._build_style(self._theme.warning, bold)

    def info(self, bold: bool = False) -> str:
        return self._build_style(self._theme.info, bold)

    def dim(self, italic: bool = True) -> str:
        style = self._theme.dim
        if italic:
            style += " italic"
        return style

    def text(self) -> str:
        return self._theme.text

    def title(self, bold: bool = True) -> str:
        return self._build_style(self._theme.title, bold)

    def accent(self, bold: bool = True) -> str:
        return self._build_style(self._theme.accent, bold)

    def border(self) -> str:
        return self._theme.border

    def label(self) -> str:
        return self._build_style(self._theme.label, True)

    def status(self) -> str:
        return f"{self._theme.status_text} on {self._theme.status_bg}"

    def status_strong(self) -> str:
        return f"bold {self._theme.status_strong} on {self._theme.status_bg}"

    def status_dim(self) -> str:
        return f"{self._theme.status_dim} on {self._theme.status_bg}"

    def status_good(self) -> str:
        return f"bold {self._theme.status_good} on {self._theme.status_bg}"

    def status_warn(self) -> str:
        return f"bold {self._theme.status_warn} on {self._theme.status_bg}"

    def status_bad(self) -> str:
        return f"bold {self._theme.status_bad} on {self._theme.status_bg}"

    def status_critical(self) -> str:
        return f"bold {self._theme.status_critical} on {self._theme.status_bg}"

    def _build_style(self, color: str, bold: bool) -> str:
        style = color
        if bold:
            style = f"bold {style}"
        return style

    def to_rich_theme(self) -> Dict[str, str]:
        """导出为 Rich Theme 可用的样式字典"""
        return {
            "grassflow.primary": self.primary(True),
            "grassflow.success": self.success(),
            "grassflow.error": self.error(True),
            "grassflow.warning": self.warning(),
            "grassflow.info": self.info(),
            "grassflow.dim": self.dim(),
            "grassflow.text": self.text(),
            "grassflow.title": self.title(),
            "grassflow.accent": self.accent(),
            "grassflow.border": self.border(),
            "grassflow.label": self.label(),
        }


# =============================================================================
# 内置主题
# =============================================================================

BUILTIN_THEMES: Dict[str, GrassFlowTheme] = {
    "default": GrassFlowTheme(
        name="default",
        description="GrassFlow 默认主题 — 金色和暗色",
        primary="#FFBF00",
        success="#4caf50",
        error="#ef5350",
        warning="#ff9800",
        info="#2196f3",
        dim="#666666",
        accent="#FFBF00",
        title="#FFD700",
        text="#FFF8DC",
        border="#CD7F32",
        label="#DAA520",
        prompt_symbol="❯",
        spinner_style="dots",
        tool_prefix="┊",
        status_bg="#1a1a2e",
        status_text="#C0C0C0",
        status_strong="#FFD700",
        status_dim="#8B8682",
        status_good="#8FBC8F",
        status_warn="#FFD700",
        status_bad="#FF8C00",
        status_critical="#FF6B6B",
    ),
    "dark": GrassFlowTheme(
        name="dark",
        description="暗色主题 — 青色强调",
        primary="#64ffda",
        success="#69f0ae",
        error="#ff5252",
        warning="#ffd740",
        info="#40c4ff",
        dim="#616161",
        accent="#64ffda",
        title="#e6edf3",
        text="#c9d1d9",
        border="#424242",
        label="#80cbc4",
        prompt_symbol="❯",
        spinner_style="dots",
        tool_prefix="┊",
        status_bg="#121212",
        status_text="#bdbdbd",
        status_strong="#64ffda",
        status_dim="#616161",
        status_good="#69f0ae",
        status_warn="#ffd740",
        status_bad="#ff6e40",
        status_critical="#ff5252",
    ),
    "mono": GrassFlowTheme(
        name="mono",
        description="单色主题 — 简洁灰度",
        primary="#ffffff",
        success="#aaaaaa",
        error="#dddddd",
        warning="#bbbbbb",
        info="#999999",
        dim="#444444",
        accent="#cccccc",
        title="#e6edf3",
        text="#c9d1d9",
        border="#555555",
        label="#888888",
        prompt_symbol="❯",
        spinner_style="dots",
        tool_prefix="┊",
        status_bg="#1F1F1F",
        status_text="#C9D1D9",
        status_strong="#E6EDF3",
        status_dim="#777777",
        status_good="#B5B5B5",
        status_warn="#AAAAAA",
        status_bad="#D0D0D0",
        status_critical="#F0F0F0",
    ),
    "ocean": GrassFlowTheme(
        name="ocean",
        description="海洋主题 — 深蓝和碧绿",
        primary="#00bcd4",
        success="#4db6ac",
        error="#e57373",
        warning="#ffb74d",
        info="#4fc3f7",
        dim="#546e7a",
        accent="#00bcd4",
        title="#b2ebf2",
        text="#e0f7fa",
        border="#006064",
        label="#4dd0e1",
        prompt_symbol="Ψ",
        spinner_style="dots",
        tool_prefix="│",
        status_bg="#0F2440",
        status_text="#e0f7fa",
        status_strong="#b2ebf2",
        status_dim="#496884",
        status_good="#4db6ac",
        status_warn="#ffb74d",
        status_bad="#e57373",
        status_critical="#ef5350",
    ),
    "forest": GrassFlowTheme(
        name="forest",
        description="森林主题 — 绿色和大地色",
        primary="#66bb6a",
        success="#81c784",
        error="#e57373",
        warning="#ffb74d",
        info="#42a5f5",
        dim="#5d4037",
        accent="#66bb6a",
        title="#a5d6a7",
        text="#e8f5e9",
        border="#2e7d32",
        label="#81c784",
        prompt_symbol="❯",
        spinner_style="dots",
        tool_prefix="┊",
        status_bg="#1b2e1b",
        status_text="#e8f5e9",
        status_strong="#a5d6a7",
        status_dim="#5d4037",
        status_good="#81c784",
        status_warn="#ffb74d",
        status_bad="#e57373",
        status_critical="#ef5350",
    ),
    "sunset": GrassFlowTheme(
        name="sunset",
        description="日落主题 — 暖色渐变",
        primary="#ff7043",
        success="#aed581",
        error="#ef5350",
        warning="#ffb74d",
        info="#4fc3f7",
        dim="#6d4c41",
        accent="#ff7043",
        title="#ffab91",
        text="#fbe9e7",
        border="#bf360c",
        label="#ff8a65",
        prompt_symbol="❯",
        spinner_style="dots",
        tool_prefix="┊",
        status_bg="#2b1610",
        status_text="#fbe9e7",
        status_strong="#ffab91",
        status_dim="#6d4c41",
        status_good="#aed581",
        status_warn="#ffb74d",
        status_bad="#ff7043",
        status_critical="#ef5350",
    ),
}


# =============================================================================
# 主题管理器
# =============================================================================

class ThemeManager:
    """主题管理器

    参考 Hermes skin_engine.py 的 SkinConfig 管理系统，
    管理 GrassFlow 的主题注册、切换和持久化。
    """

    def __init__(self):
        self._themes: Dict[str, GrassFlowTheme] = dict(BUILTIN_THEMES)
        self._active_theme_name: str = "default"
        self._user_themes_dir: Optional[Path] = None

    def set_user_themes_dir(self, path: Path) -> None:
        """设置用户主题目录"""
        self._user_themes_dir = path

    def list_themes(self) -> List[Dict[str, str]]:
        """列出所有可用主题

        Returns:
            主题列表，每个元素包含 name、description 和 source
        """
        result = []
        for name, theme in self._themes.items():
            source = "user" if name not in BUILTIN_THEMES else "builtin"
            result.append({
                "name": name,
                "description": theme.description,
                "source": source,
            })
        return result

    def get_theme(self, name: str) -> GrassFlowTheme:
        """获取主题

        如果不存在则回退到 default。
        """
        if name in self._themes:
            return self._themes[name]
        logger.warning("Theme '%s' not found, using default", name)
        return self._themes["default"]

    def register_theme(self, theme: GrassFlowTheme) -> None:
        """注册自定义主题"""
        self._themes[theme.name] = theme

    def unregister_theme(self, name: str) -> None:
        """取消注册主题（不能删除内置主题）"""
        if name in BUILTIN_THEMES:
            logger.warning("Cannot unregister built-in theme '%s'", name)
            return
        self._themes.pop(name, None)

    @property
    def active_theme_name(self) -> str:
        """当前活动主题名称"""
        return self._active_theme_name

    @active_theme_name.setter
    def active_theme_name(self, name: str) -> None:
        """切换活动主题"""
        if name in self._themes:
            self._active_theme_name = name
        else:
            logger.warning("Theme '%s' not found, keeping current", name)

    @property
    def active_theme(self) -> GrassFlowTheme:
        """当前活动主题"""
        return self.get_theme(self._active_theme_name)

    def get_rich_style(self, theme_name: Optional[str] = None) -> RichStyle:
        """获取 Rich 样式

        Args:
            theme_name: 主题名称，默认使用当前活动主题

        Returns:
            RichStyle 实例
        """
        theme = self.get_theme(theme_name or self._active_theme_name)
        return RichStyle(theme)

    def load_user_themes(self) -> int:
        """加载用户自定义主题

        从 user_themes_dir 中加载所有 .json 文件。

        Returns:
            加载的主题数量
        """
        if not self._user_themes_dir or not self._user_themes_dir.is_dir():
            return 0

        count = 0
        for file in sorted(self._user_themes_dir.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "name" in data:
                    theme = GrassFlowTheme.from_dict(data)
                    self.register_theme(theme)
                    count += 1
            except Exception as e:
                logger.debug("Failed to load theme from %s: %s", file, e)

        return count

    def save_theme(self, theme: GrassFlowTheme) -> bool:
        """保存主题到用户主题目录

        Args:
            theme: 要保存的主题

        Returns:
            是否保存成功
        """
        if not self._user_themes_dir:
            logger.warning("No user themes directory configured")
            return False

        self._user_themes_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._user_themes_dir / f"{theme.name}.json"

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(theme.to_dict(), f, indent=2, ensure_ascii=False)
            self.register_theme(theme)
            return True
        except Exception as e:
            logger.error("Failed to save theme: %s", e)
            return False

    def reset_to_default(self) -> GrassFlowTheme:
        """重置为默认主题"""
        self._active_theme_name = "default"
        return self._themes["default"]


# =============================================================================
# 全局主题管理器
# =============================================================================

_theme_manager = ThemeManager()


def get_theme_manager() -> ThemeManager:
    """获取全局主题管理器"""
    return _theme_manager


def get_active_theme() -> GrassFlowTheme:
    """获取当前活动主题"""
    return _theme_manager.active_theme


def get_active_rich_style() -> RichStyle:
    """获取当前活动主题的 Rich 样式"""
    return _theme_manager.get_rich_style()


def set_theme(name: str) -> GrassFlowTheme:
    """切换主题"""
    _theme_manager.active_theme_name = name
    return _theme_manager.active_theme


def list_themes() -> List[Dict[str, str]]:
    """列出所有可用主题"""
    return _theme_manager.list_themes()

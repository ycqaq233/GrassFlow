"""
GrassFlow Skills System

参考 hermes 的 skills 实现，为 GrassFlow 提供技能管理功能：
- SKILL.md 格式解析（YAML frontmatter + Markdown 内容）
- 技能目录扫描与缓存
- 平台过滤
- 技能索引注入到系统提示词

SKILL.md 格式示例::

    ---
    name: skill-name
    description: Brief description
    version: 1.0.0
    platforms: [windows, linux, macos]
    prerequisites:
      env_vars: [API_KEY]
      commands: [curl, jq]
    metadata:
      tags: [coding, research]
    ---

    # Skill Title

    Full instructions and content here...

目录结构::

    ~/.Grass/skills/
    ├── my-skill/
    │   ├── SKILL.md           # 主指令文件（必需）
    │   └── references/        # 可选的辅助文档
    └── category/
        └── another-skill/
            └── SKILL.md
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ==================== 平台映射 ====================

PLATFORM_MAP: Dict[str, str] = {
    "macos": "darwin",
    "linux": "linux",
    "windows": "win32",
}

# 排除的目录名（扫描时跳过）
EXCLUDED_SKILL_DIRS: frozenset[str] = frozenset((
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
))

# 技能支持子目录（不是独立技能）
SKILL_SUPPORT_DIRS: frozenset[str] = frozenset((
    "references",
    "templates",
    "assets",
    "scripts",
))


# ==================== 数据模型 ====================


@dataclass
class Skill:
    """技能数据模型"""

    name: str
    """技能名称"""

    description: str = ""
    """技能描述"""

    version: str = "1.0.0"
    """技能版本"""

    platforms: List[str] = field(default_factory=list)
    """限制的平台列表，空列表表示所有平台"""

    prerequisites: Dict[str, List[str]] = field(default_factory=dict)
    """前置条件，如 {"env_vars": ["API_KEY"], "commands": ["curl"]}"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """任意元数据"""

    content: str = ""
    """Markdown 正文内容（不含 frontmatter）"""

    path: Optional[Path] = None
    """SKILL.md 文件路径"""

    enabled: bool = True
    """是否启用"""


# ==================== Frontmatter 解析 ====================


def _split_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """分离 YAML frontmatter 和 Markdown 正文。

    不依赖 yaml 库，使用简单的逐行解析。

    支持的格式::

        ---
        key: value
        list_key: [a, b, c]
        nested:
          subkey: subvalue
        ---

        # Body content

    Args:
        content: 完整的 SKILL.md 文件内容

    Returns:
        (frontmatter_dict, body_str) 元组
    """
    frontmatter: Dict[str, Any] = {}
    body = content

    if not content.startswith("---"):
        return frontmatter, body

    # 查找结束的 ---
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return frontmatter, body

    yaml_content = content[3 : end_match.start() + 3]
    body = content[end_match.end() + 3 :]

    # 优先使用 PyYAML（支持完整 YAML 语法）
    try:
        import yaml
        loader = getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader
        parsed = yaml.load(yaml_content, Loader=loader)
        if isinstance(parsed, dict):
            return parsed, body
    except Exception:
        pass

    # 降级到简单解析器
    frontmatter = _parse_yaml_simple(yaml_content)

    return frontmatter, body


def _parse_yaml_simple(yaml_str: str) -> Dict[str, Any]:
    """简单的 YAML 解析器，不依赖 yaml 库。

    支持的特性：
    - key: value 标量
    - key: [item1, item2] 内联列表（带类型转换）
    - 嵌套 key（任意缩进深度）

    不支持的特性（使用 PyYAML 处理）：
    - 多行字符串（|, >）
    - 锚点和引用
    - 多文档流

    Args:
        yaml_str: YAML 格式的字符串

    Returns:
        解析后的字典
    """
    result: Dict[str, Any] = {}
    lines = yaml_str.split("\n")
    current_key: Optional[str] = None

    for line in lines:
        # 跳过空行
        if not line.strip():
            continue

        # 跳过注释
        if line.strip().startswith("#"):
            continue

        # 顶级 key: value
        if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            if not key:
                continue

            current_key = key

            if not value:
                # 空值：可能是嵌套 dict 的开始，保持 current_key
                # 等待后续的缩进行
                continue

            # 内联列表: [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1]
                result[key] = [
                    _coerce_scalar(item.strip())
                    for item in items.split(",")
                    if item.strip()
                ]
            # 布尔值
            elif value.lower() in ("true", "yes", "on"):
                result[key] = True
            elif value.lower() in ("false", "no", "off"):
                result[key] = False
            # 数字
            elif re.fullmatch(r"-?\d+", value):
                result[key] = int(value)
            elif _is_float(value):
                result[key] = float(value)
            # 字符串
            else:
                result[key] = value.strip("\"'")

        # 嵌套 key（任意缩进深度）
        elif current_key:
            stripped_line = line.lstrip()
            indent = len(line) - len(stripped_line)

            if indent <= 0 or ":" not in stripped_line:
                continue

            nested_key, _, nested_value = stripped_line.partition(":")
            nested_key = nested_key.strip()
            nested_value = nested_value.strip()

            if not nested_key:
                continue

            # 确保父 key 是字典
            if not isinstance(result.get(current_key), dict):
                result[current_key] = {}

            if nested_value:
                # 内联列表
                if nested_value.startswith("[") and nested_value.endswith("]"):
                    items = nested_value[1:-1]
                    result[current_key][nested_key] = [
                        _coerce_scalar(item.strip())
                        for item in items.split(",")
                        if item.strip()
                    ]
                elif nested_value.lower() in ("true", "yes", "on"):
                    result[current_key][nested_key] = True
                elif nested_value.lower() in ("false", "no", "off"):
                    result[current_key][nested_key] = False
                elif re.fullmatch(r"-?\d+", nested_value):
                    result[current_key][nested_key] = int(nested_value)
                elif _is_float(nested_value):
                    result[current_key][nested_key] = float(nested_value)
                else:
                    result[current_key][nested_key] = nested_value.strip("\"'")
            else:
                result[current_key][nested_key] = ""

    return result


def _is_float(value: str) -> bool:
    """检查字符串是否是浮点数"""
    try:
        float(value)
        return "." in value
    except ValueError:
        return False


def _coerce_scalar(value: str) -> Any:
    """将字符串标量转换为适当的 Python 类型。

    用于内联列表项的类型转换：
    - true/yes/on -> True
    - false/no/off -> False
    - 整数字符串 -> int
    - 浮点字符串 -> float
    - 其他 -> 去除引号的字符串
    """
    if not value:
        return ""
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if _is_float(value):
        return float(value)
    return value.strip('"').strip("'")


# ==================== 平台检查 ====================


def _check_platform(platforms: List[str]) -> bool:
    """检查当前平台是否在允许的平台列表中。

    Args:
        platforms: 平台列表（如 ["windows", "linux"]），空列表表示所有平台

    Returns:
        True 表示当前平台被允许
    """
    if not platforms:
        return True

    current_platform = sys.platform

    for platform in platforms:
        normalized = str(platform).lower().strip()
        mapped = PLATFORM_MAP.get(normalized, normalized)
        if current_platform.startswith(mapped):
            return True

    return False


# ==================== SkillsManager ====================


class SkillsManager:
    """技能管理器

    负责扫描、解析和管理 SKILL.md 技能文件。

    使用方式::

        manager = SkillsManager()
        skills = manager.scan()
        for skill in skills:
            print(f"{skill.name}: {skill.description}")
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        """
        初始化技能管理器

        Args:
            skills_dir: 技能目录路径，默认 ~/.Grass/skills/
        """
        if skills_dir is None:
            grass_home = Path(os.path.expanduser("~")) / ".Grass"
            skills_dir = grass_home / "skills"

        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, Skill] = {}
        self._scanned = False

    def scan(self) -> List[Skill]:
        """扫描技能目录，发现所有 SKILL.md 文件。

        Returns:
            发现的技能列表
        """
        self._skills.clear()
        self._scanned = True

        if not self.skills_dir.exists():
            logger.debug("Skills directory does not exist: %s", self.skills_dir)
            return []

        for skill_md in self._iter_skill_files():
            skill = self._parse_skill_file(skill_md)
            if skill is not None:
                # 名称去重，先发现的优先
                if skill.name not in self._skills:
                    self._skills[skill.name] = skill

        return list(self._skills.values())

    def _iter_skill_files(self) -> List[Path]:
        """遍历技能目录，收集所有 SKILL.md 文件路径。

        Returns:
            排序后的 SKILL.md 路径列表
        """
        matches: List[Path] = []

        for root, dirs, files in os.walk(self.skills_dir, followlinks=True):
            # 排除不需要的目录
            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDED_SKILL_DIRS
                and not (d in SKILL_SUPPORT_DIRS and "SKILL.md" in files)
            ]

            if "SKILL.md" in files:
                matches.append(Path(root) / "SKILL.md")

        # 按相对路径排序，保证扫描顺序一致
        matches.sort(key=lambda p: str(p.relative_to(self.skills_dir)))
        return matches

    def _parse_skill_file(self, path: Path) -> Optional[Skill]:
        """解析单个 SKILL.md 文件。

        Args:
            path: SKILL.md 文件路径

        Returns:
            解析后的 Skill 对象，解析失败返回 None
        """
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError) as e:
            logger.warning("Failed to read skill file %s: %s", path, e)
            return None

        frontmatter, body = _split_frontmatter(content)

        # 提取字段
        name = str(frontmatter.get("name", "")).strip()
        if not name:
            # 从路径推断名称
            name = path.parent.name

        description = str(frontmatter.get("description", "")).strip()

        # 如果 description 为空，从正文提取第一行非标题文字
        if not description:
            for line in body.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:200]
                    break

        version = str(frontmatter.get("version", "1.0.0")).strip()

        # 平台列表
        platforms_raw = frontmatter.get("platforms", [])
        if isinstance(platforms_raw, str):
            platforms = [p.strip() for p in platforms_raw.split(",") if p.strip()]
        elif isinstance(platforms_raw, list):
            platforms = [str(p).strip() for p in platforms_raw if p]
        else:
            platforms = []

        # 前置条件
        prerequisites_raw = frontmatter.get("prerequisites", {})
        if isinstance(prerequisites_raw, dict):
            prerequisites: Dict[str, List[str]] = {}
            for k, v in prerequisites_raw.items():
                if isinstance(v, list):
                    prerequisites[str(k)] = [str(item) for item in v]
                elif isinstance(v, str):
                    prerequisites[str(k)] = [v]
                else:
                    prerequisites[str(k)] = [str(v)]
        else:
            prerequisites = {}

        # 元数据
        metadata_raw = frontmatter.get("metadata", {})
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}

        # 平台过滤
        if not _check_platform(platforms):
            logger.debug("Skill '%s' not compatible with current platform, skipping", name)
            return None

        return Skill(
            name=name,
            description=description,
            version=version,
            platforms=platforms,
            prerequisites=prerequisites,
            metadata=metadata,
            content=body.strip(),
            path=path,
            enabled=True,
        )

    def get_skill(self, name: str) -> Optional[Skill]:
        """根据名称获取技能。

        如果尚未扫描，会先触发扫描。

        Args:
            name: 技能名称

        Returns:
            技能对象，不存在返回 None
        """
        if not self._scanned:
            self.scan()
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        """列出所有已发现的技能。

        如果尚未扫描，会先触发扫描。

        Returns:
            技能列表
        """
        if not self._scanned:
            self.scan()
        return list(self._skills.values())

    def build_skills_prompt(self) -> str:
        """构建技能索引提示词，用于注入到系统提示词中。

        Returns:
            格式化的技能索引字符串，没有技能时返回空字符串
        """
        skills = self.list_skills()

        if not skills:
            return ""

        # 按名称排序
        skills_sorted = sorted(skills, key=lambda s: s.name)

        lines = [
            "## Available Skills",
            "",
            "The following skills are available. Use a skill when it is relevant to the task.",
            "",
        ]

        for skill in skills_sorted:
            if skill.description:
                lines.append(f"- **{skill.name}**: {skill.description}")
            else:
                lines.append(f"- **{skill.name}**")

        lines.append("")
        lines.append(
            "To use a skill, the user will type /skill-name. "
            "When a skill is loaded, follow its instructions."
        )

        return "\n".join(lines)

    def get_skills_summary(self) -> str:
        """获取技能摘要，用于 /skills 命令显示。

        Returns:
            格式化的技能摘要字符串
        """
        skills = self.list_skills()

        if not skills:
            return f"No skills found in {self.skills_dir}"

        skills_sorted = sorted(skills, key=lambda s: s.name)

        lines = [
            f"Skills directory: {self.skills_dir}",
            f"Total skills: {len(skills_sorted)}",
            "",
        ]

        for skill in skills_sorted:
            platform_str = ""
            if skill.platforms:
                platform_str = f" [{', '.join(skill.platforms)}]"

            version_str = f" v{skill.version}" if skill.version != "1.0.0" else ""

            lines.append(f"  {skill.name}{version_str}{platform_str}")
            if skill.description:
                # 截断过长的描述
                desc = skill.description
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                lines.append(f"    {desc}")

            # 显示前置条件
            if skill.prerequisites:
                for key, values in skill.prerequisites.items():
                    lines.append(f"    {key}: {', '.join(values)}")

        return "\n".join(lines)


# ==================== 全局实例 ====================

_skills_manager: Optional[SkillsManager] = None


def get_skills_manager(skills_dir: Optional[Path] = None) -> SkillsManager:
    """获取全局技能管理器实例。

    Args:
        skills_dir: 技能目录路径，仅在首次调用时生效

    Returns:
        SkillsManager 实例
    """
    global _skills_manager
    if _skills_manager is None:
        _skills_manager = SkillsManager(skills_dir)
    return _skills_manager


def reset_skills_manager() -> None:
    """重置全局技能管理器（用于测试）"""
    global _skills_manager
    _skills_manager = None

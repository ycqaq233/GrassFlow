"""
GrassFlow Skills 管理器

参考 opencode 的 Skills 系统，实现：
- YAML + Markdown 格式解析（SKILL.md 文件）
- 多目录发现机制（当前目录 → 项目目录 → 全局目录）
- 渐进式披露三层架构（列表 → 详情 → 文件）

SKILL.md 文件格式：
    ---
    name: skill-name
    description: 技能描述
    slash: true
    tags: [tag1, tag2]
    version: "1.0"
    ---
    # 技能内容

渐进式披露三层架构（参考 Hermes / OpenCode）：
- Level 1: 列表（name + description + tags）- 最小 token 消耗
- Level 2: 详情（完整结构化内容）- 中等 token 消耗
- Level 3: 文件（按需加载原始 SKILL.md）- 按需
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────────────────

SKILL_FILENAME = "SKILL.md"
# 目录发现顺序：当前目录 → 项目目录 → 全局目录
# 同名 Skill 后发现的覆盖先发现的（与 opencode 行为一致）
DEFAULT_SEARCH_DIRS = [
    Path.cwd() / ".grass",
    Path.home() / ".Grass",
]
# 子目录模式：在每个搜索目录下查找 skills/**/SKILL.md
SKILL_SUBDIR = "skills"


# ── 异常 ──────────────────────────────────────────────────────────────────────


class SkillError(Exception):
    """Skills 系统基础异常"""


class SkillNotFoundError(SkillError):
    """Skill 未找到"""

    def __init__(self, name: str, available: List[str]):
        self.name = name
        self.available = available
        super().__init__(
            f'Skill "{name}" not found. '
            f'Available skills: {", ".join(available) or "none"}'
        )


class SkillParseError(SkillError):
    """Skill 文件解析失败"""

    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(f"Failed to parse skill {path}: {message}")


class SkillFrontmatterError(SkillParseError):
    """YAML frontmatter 解析失败"""


class SkillNameMismatchError(SkillError):
    """Skill name 与文件路径不匹配"""

    def __init__(self, path: str, expected: str, actual: str):
        self.path = path
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Skill name mismatch in {path}: expected '{expected}', got '{actual}'"
        )


# ── 数据模型 ──────────────────────────────────────────────────────────────────


@dataclass
class SkillInfo:
    """Skill 信息

    Attributes:
        name: Skill 名称（来自 frontmatter）
        description: Skill 描述（来自 frontmatter，可选）
        slash: 是否注册为斜杠命令（来自 frontmatter）
        location: SKILL.md 文件的绝对路径
        content: Markdown 正文内容（frontmatter 之后的部分）
        metadata: frontmatter 中的其他字段
        tags: 标签列表（来自 frontmatter）
        version: 版本号（来自 frontmatter）
    """

    name: str
    description: Optional[str] = None
    slash: bool = False
    location: str = ""
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    version: Optional[str] = None

    # ── 渐进式披露 Level 1：列表 ──────────────────────────────────────────

    def to_list_line(self) -> str:
        """渐进式披露 Level 1：一行摘要（Markdown 格式）"""
        desc = f": {self.description}" if self.description else ""
        tags_str = f" [{', '.join(self.tags)}]" if self.tags else ""
        return f"- **{self.name}**{desc}{tags_str}"

    def to_list_summary(self) -> Dict[str, Any]:
        """渐进式披露 Level 1：结构化摘要（用于 API/JSON）"""
        return {
            "name": self.name,
            "description": self.description,
            "slash": self.slash,
            "tags": self.tags,
            "version": self.version,
            "location": self.location,
        }

    # ── 渐进式披露 Level 2：详情 ──────────────────────────────────────────

    def to_detail(self) -> str:
        """渐进式披露 Level 2：结构化详情（Markdown 格式）"""
        lines = [f"## {self.name}", ""]
        if self.description:
            lines.append(f"**Description:** {self.description}")
            lines.append("")
        if self.tags:
            lines.append(f"**Tags:** {', '.join(self.tags)}")
            lines.append("")
        if self.version:
            lines.append(f"**Version:** {self.version}")
            lines.append("")
        if self.slash:
            lines.append("**Slash command:** yes")
            lines.append("")
        lines.append(f"**Location:** `{self.location}`")
        lines.append("")
        if self.metadata:
            lines.append("**Metadata:**")
            for key, value in self.metadata.items():
                if key not in ("tags", "version"):
                    lines.append(f"  - {key}: {value}")
            lines.append("")
        if self.content:
            lines.append("**Content:**")
            lines.append("")
            lines.append(self.content)
        return "\n".join(lines)

    def to_detail_dict(self) -> Dict[str, Any]:
        """渐进式披露 Level 2：结构化详情（用于 API/JSON）"""
        return {
            "name": self.name,
            "description": self.description,
            "slash": self.slash,
            "tags": self.tags,
            "version": self.version,
            "location": self.location,
            "content": self.content,
            "metadata": self.metadata,
        }

    # ── 渐进式披露 Level 3：文件 ──────────────────────────────────────────

    def to_full(self) -> str:
        """渐进式披露 Level 3：完整文件内容（含 frontmatter，Markdown 格式）"""
        parts = ["---"]
        parts.append(f"name: {self.name}")
        if self.description:
            parts.append(f"description: {self.description}")
        if self.slash:
            parts.append("slash: true")
        if self.tags:
            parts.append(f"tags: [{', '.join(self.tags)}]")
        if self.version:
            parts.append(f"version: {self.version}")
        for key, value in self.metadata.items():
            if key not in ("tags", "version"):
                parts.append(f"{key}: {value}")
        parts.append("---")
        parts.append("")
        parts.append(self.content)
        return "\n".join(parts)

    def to_full_dict(self) -> Dict[str, Any]:
        """渐进式披露 Level 3：完整数据（用于 API/JSON）"""
        return {
            "name": self.name,
            "description": self.description,
            "slash": self.slash,
            "tags": self.tags,
            "version": self.version,
            "location": self.location,
            "content": self.content,
            "metadata": self.metadata,
            "raw_content": self.to_full(),
        }

    # ── 过滤匹配 ──────────────────────────────────────────────────────────

    def matches_filter(
        self,
        tags: Optional[List[str]] = None,
        slash_only: bool = False,
        search_term: Optional[str] = None,
    ) -> bool:
        """检查 Skill 是否匹配过滤条件

        Args:
            tags: 标签过滤列表（任一匹配即可）
            slash_only: 是否只返回 slash 命令
            search_term: 搜索词（匹配名称、描述或内容）

        Returns:
            是否匹配
        """
        if slash_only and not self.slash:
            return False

        if tags:
            if not any(tag in self.tags for tag in tags):
                return False

        if search_term:
            term = search_term.lower()
            name_match = term in self.name.lower()
            desc_match = self.description is not None and term in self.description.lower()
            content_match = term in self.content.lower()
            if not (name_match or desc_match or content_match):
                return False

        return True


# ── Frontmatter 解析 ─────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n?---\s*\n?", re.DOTALL)


def _parse_yaml_simple(text: str) -> Dict[str, Any]:
    """简单的 YAML 子集解析器

    支持 YAML frontmatter 中常见的简单键值对格式：
    - key: value
    - key: "quoted value"
    - key: 'quoted value'
    - key: true / false
    - key: 123
    - key: |-
        多行文本
    - 以 # 开头的注释行

    这是一个轻量实现，避免引入 PyYAML 依赖。
    如果项目后续已经安装了 PyYAML，可以切换到 yaml.safe_load。
    """
    result: Dict[str, Any] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        # 跳过空行和注释
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        # 键值对
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:\s*(.*)$", line)
        if not match:
            i += 1
            continue
        key = match.group(1)
        raw_value = match.group(2).strip()
        # 处理 block scalar (|-, |, >-, >)
        if raw_value in ("|-", "|", ">-", ">"):
            # 收集缩进行作为多行值
            block_lines: List[str] = []
            i += 1
            indent = None
            while i < len(lines):
                bline = lines[i]
                if bline.strip() == "":
                    block_lines.append("")
                    i += 1
                    continue
                # 检测缩进
                current_indent = len(bline) - len(bline.lstrip())
                if indent is None:
                    indent = current_indent
                if current_indent >= indent:
                    block_lines.append(bline[indent:] if indent else bline)
                    i += 1
                else:
                    break
            value = "\n".join(block_lines).rstrip("\n")
        else:
            value = _coerce_value(raw_value)
            i += 1
        result[key] = value
    return result


def _coerce_value(raw: str) -> Any:
    """将原始字符串值转换为合适的 Python 类型"""
    if not raw:
        return ""
    # 去除引号
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    # 布尔值
    if raw.lower() in ("true", "yes", "on"):
        return True
    if raw.lower() in ("false", "no", "off"):
        return False
    # null
    if raw.lower() in ("null", "~", ""):
        return None
    # 数字
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    # 原始字符串
    return raw


def parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """解析 YAML frontmatter 和 Markdown 正文

    使用简单的内置解析器。如果安装了 PyYAML，会自动使用它来获得更好的兼容性。

    Args:
        content: SKILL.md 文件的完整文本内容

    Returns:
        (metadata_dict, markdown_body) 元组

    Raises:
        SkillFrontmatterError: frontmatter 格式无效
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise SkillFrontmatterError(
            "<input>",
            "No YAML frontmatter found. File must start with '---'",
        )

    yaml_str = match.group(1)
    body = content[match.end() :]

    # 尝试使用 PyYAML（如果可用）
    try:
        import yaml

        metadata = yaml.safe_load(yaml_str)
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise SkillFrontmatterError(
                "<input>",
                f"Frontmatter must be a mapping, got {type(metadata).__name__}",
            )
        return metadata, body
    except ImportError:
        pass

    # 回退到简单解析器
    try:
        metadata = _parse_yaml_simple(yaml_str)
        return metadata, body
    except Exception as e:
        raise SkillFrontmatterError("<input>", str(e))


# ── 文件发现 ──────────────────────────────────────────────────────────────────


def _scan_skill_files(root: Path) -> List[Path]:
    """在指定目录下扫描所有 SKILL.md 文件

    扫描 root/skills/**/SKILL.md 模式。

    Args:
        root: 搜索根目录（例如 .grass/ 或 ~/.Grass/）

    Returns:
        找到的 SKILL.md 文件绝对路径列表
    """
    skills_dir = root / SKILL_SUBDIR
    if not skills_dir.is_dir():
        return []
    return sorted(skills_dir.rglob(SKILL_FILENAME))


def discover_skill_files(
    search_dirs: Optional[List[Path]] = None,
) -> List[Path]:
    """多目录发现 Skill 文件

    按顺序扫描多个目录，返回所有找到的 SKILL.md 文件。
    同名文件后扫描到的会覆盖先扫描到的（在 load 阶段处理）。

    Args:
        search_dirs: 搜索目录列表，默认为 [CWD/.grass, ~/.Grass]

    Returns:
        去重后的 SKILL.md 文件路径列表
    """
    if search_dirs is None:
        search_dirs = DEFAULT_SEARCH_DIRS

    seen: set = set()
    all_files: List[Path] = []

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            logger.debug("Search directory not found: %s", search_dir)
            continue
        for skill_file in _scan_skill_files(search_dir):
            resolved = skill_file.resolve()
            if resolved not in seen:
                seen.add(resolved)
                all_files.append(skill_file)
            else:
                logger.debug("Duplicate skill file skipped: %s", skill_file)

    return all_files


# ── Skill 加载 ────────────────────────────────────────────────────────────────


def load_skill_file(path: Path) -> SkillInfo:
    """从单个 SKILL.md 文件加载 Skill 信息

    Args:
        path: SKILL.md 文件路径

    Returns:
        SkillInfo 实例

    Raises:
        SkillParseError: 文件读取或解析失败
        SkillFrontmatterError: frontmatter 格式无效
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillParseError(str(path), f"Cannot read file: {e}")

    try:
        metadata, body = parse_frontmatter(content)
    except SkillFrontmatterError as e:
        raise SkillFrontmatterError(str(path), e.args[0] if e.args else str(e))

    # 提取必填字段
    name = metadata.pop("name", None)
    if not name or not isinstance(name, str):
        raise SkillParseError(
            str(path),
            "Missing or invalid 'name' field in frontmatter",
        )

    # 提取已知字段
    description = metadata.pop("description", None)
    slash = metadata.pop("slash", False)
    tags = metadata.pop("tags", [])
    version = metadata.pop("version", None)

    # 处理 tags：可能是字符串或列表
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, list):
        tags = []

    # 处理 version：转为字符串
    if version is not None:
        version = str(version)

    # 剩余字段作为 metadata
    return SkillInfo(
        name=name,
        description=description,
        slash=bool(slash),
        location=str(path.resolve()),
        content=body.strip(),
        metadata=metadata,
        tags=tags,
        version=version,
    )


def load_skills(
    search_dirs: Optional[List[Path]] = None,
) -> Dict[str, SkillInfo]:
    """发现并加载所有 Skill

    多目录发现 → 逐文件解析 → 返回 name -> SkillInfo 字典。
    同名 Skill 后发现的覆盖先发现的。

    Args:
        search_dirs: 搜索目录列表

    Returns:
        {skill_name: SkillInfo} 字典
    """
    files = discover_skill_files(search_dirs)
    skills: Dict[str, SkillInfo] = {}

    for skill_file in files:
        try:
            info = load_skill_file(skill_file)
            if info.name in skills:
                logger.warning(
                    "Duplicate skill name '%s': overwriting %s with %s",
                    info.name,
                    skills[info.name].location,
                    info.location,
                )
            skills[info.name] = info
        except SkillError as e:
            logger.error("Failed to load skill %s: %s", skill_file, e)
        except Exception as e:
            logger.error("Unexpected error loading skill %s: %s", skill_file, e)

    logger.info("Loaded %d skill(s)", len(skills))
    return skills


# ── Skill 管理器 ──────────────────────────────────────────────────────────────


class SkillManager:
    """Skills 管理器

    提供 Skill 的发现、加载、查询和格式化功能。
    支持渐进式披露三层架构：列表 → 详情 → 文件。

    渐进式披露设计（参考 Hermes / OpenCode）：
    - Level 1: 列表（name + description + tags）- 最小 token 消耗
    - Level 2: 详情（完整结构化内容）- 中等 token 消耗
    - Level 3: 文件（按需加载原始 SKILL.md）- 按需

    用法：
        manager = SkillManager()
        # 或指定搜索目录
        manager = SkillManager(search_dirs=[Path("/my/skills")])

        # 列出所有 Skills（Level 1）
        skills = manager.list()
        print(manager.format_list())

        # 过滤查询
        filtered = manager.filter(tags=["code"], slash_only=True)

        # 获取单个 Skill 详情（Level 2）
        print(manager.format_detail("xxx"))

        # 获取完整文件内容（Level 3）
        print(manager.format_full("xxx"))

        # 获取统计信息
        stats = manager.get_stats()
    """

    def __init__(self, search_dirs: Optional[List[Path]] = None):
        """初始化 SkillManager

        Args:
            search_dirs: Skill 搜索目录列表。
                         默认搜索 CWD/.grass 和 ~/.Grass。
        """
        self._search_dirs = search_dirs
        self._skills: Optional[Dict[str, SkillInfo]] = None

    @property
    def skills(self) -> Dict[str, SkillInfo]:
        """懒加载 Skill 字典"""
        if self._skills is None:
            self._skills = load_skills(self._search_dirs)
        return self._skills

    def reload(self) -> None:
        """强制重新加载所有 Skills"""
        self._skills = None
        _ = self.skills

    def list(self) -> List[SkillInfo]:
        """获取所有 Skill 列表（按名称排序）

        Returns:
            SkillInfo 列表
        """
        return sorted(self.skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Optional[SkillInfo]:
        """按名称获取 Skill

        Args:
            name: Skill 名称

        Returns:
            SkillInfo 或 None
        """
        return self.skills.get(name)

    def require(self, name: str) -> SkillInfo:
        """按名称获取 Skill，不存在则抛异常

        Args:
            name: Skill 名称

        Returns:
            SkillInfo

        Raises:
            SkillNotFoundError: Skill 不存在
        """
        info = self.skills.get(name)
        if info is None:
            raise SkillNotFoundError(name, sorted(self.skills.keys()))
        return info

    def has(self, name: str) -> bool:
        """检查 Skill 是否存在

        Args:
            name: Skill 名称

        Returns:
            是否存在
        """
        return name in self.skills

    @property
    def slash_skills(self) -> List[SkillInfo]:
        """获取所有标记为 slash 命令的 Skills"""
        return [s for s in self.list() if s.slash]

    @property
    def count(self) -> int:
        """Skill 总数"""
        return len(self.skills)

    @property
    def directories(self) -> List[str]:
        """返回包含 Skill 的目录列表"""
        dirs: set = set()
        for skill in self.skills.values():
            parent = str(Path(skill.location).parent)
            dirs.add(parent)
        return sorted(dirs)

    @property
    def all_tags(self) -> List[str]:
        """获取所有标签（去重、排序）"""
        tags: Set[str] = set()
        for skill in self.skills.values():
            tags.update(skill.tags)
        return sorted(tags)

    # ── 过滤查询 ──────────────────────────────────────────────────────────

    def filter(
        self,
        tags: Optional[List[str]] = None,
        slash_only: bool = False,
        search_term: Optional[str] = None,
    ) -> List[SkillInfo]:
        """过滤 Skills

        Args:
            tags: 标签过滤列表（任一匹配即可）
            slash_only: 是否只返回 slash 命令
            search_term: 搜索词（匹配名称、描述或内容）

        Returns:
            过滤后的 SkillInfo 列表（按名称排序）
        """
        return sorted(
            [
                skill
                for skill in self.skills.values()
                if skill.matches_filter(
                    tags=tags, slash_only=slash_only, search_term=search_term
                )
            ],
            key=lambda s: s.name,
        )

    # ── 渐进式披露格式化 ──────────────────────────────────────────────────

    def format_list(
        self,
        tags: Optional[List[str]] = None,
        slash_only: bool = False,
        search_term: Optional[str] = None,
    ) -> str:
        """渐进式披露 Level 1：名称 + 描述列表

        Args:
            tags: 标签过滤
            slash_only: 是否只返回 slash 命令
            search_term: 搜索词

        Returns:
            格式化的 Markdown 列表
        """
        skills = self.filter(tags=tags, slash_only=slash_only, search_term=search_term)
        if not skills:
            return "No skills are currently available."
        lines = ["## Available Skills", ""]
        for skill in skills:
            lines.append(skill.to_list_line())
        return "\n".join(lines)

    def format_list_json(
        self,
        tags: Optional[List[str]] = None,
        slash_only: bool = False,
        search_term: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """渐进式披露 Level 1：结构化摘要列表（用于 API/JSON）

        Args:
            tags: 标签过滤
            slash_only: 是否只返回 slash 命令
            search_term: 搜索词

        Returns:
            结构化摘要列表
        """
        skills = self.filter(tags=tags, slash_only=slash_only, search_term=search_term)
        return [skill.to_list_summary() for skill in skills]

    def format_detail(self, name: str) -> str:
        """渐进式披露 Level 2：单个 Skill 的结构化详情

        Args:
            name: Skill 名称

        Returns:
            格式化的详情文本

        Raises:
            SkillNotFoundError: Skill 不存在
        """
        skill = self.require(name)
        return skill.to_detail()

    def format_detail_json(self, name: str) -> Dict[str, Any]:
        """渐进式披露 Level 2：单个 Skill 的结构化详情（用于 API/JSON）

        Args:
            name: Skill 名称

        Returns:
            结构化详情字典

        Raises:
            SkillNotFoundError: Skill 不存在
        """
        skill = self.require(name)
        return skill.to_detail_dict()

    def format_full(self, name: str) -> str:
        """渐进式披露 Level 3：完整文件内容

        Args:
            name: Skill 名称

        Returns:
            完整的 SKILL.md 内容

        Raises:
            SkillNotFoundError: Skill 不存在
        """
        skill = self.require(name)
        return skill.to_full()

    def format_full_json(self, name: str) -> Dict[str, Any]:
        """渐进式披露 Level 3：完整数据（用于 API/JSON）

        Args:
            name: Skill 名称

        Returns:
            完整数据字典

        Raises:
            SkillNotFoundError: Skill 不存在
        """
        skill = self.require(name)
        return skill.to_full_dict()

    def format_for_agent(
        self,
        verbose: bool = False,
        tags: Optional[List[str]] = None,
        slash_only: bool = False,
        search_term: Optional[str] = None,
    ) -> str:
        """为 Agent 生成 Skill 列表格式

        参考 opencode 的 fmt 函数，提供两种输出格式。

        Args:
            verbose: True 返回 XML 格式，False 返回 Markdown 格式
            tags: 标签过滤
            slash_only: 是否只返回 slash 命令
            search_term: 搜索词

        Returns:
            格式化的 Skill 列表
        """
        skills = self.filter(tags=tags, slash_only=slash_only, search_term=search_term)
        skills = [s for s in skills if s.description]
        if not skills:
            return "No skills are currently available."

        if verbose:
            lines = ["<available_skills>"]
            for skill in skills:
                lines.append("  <skill>")
                lines.append(f"    <name>{skill.name}</name>")
                lines.append(f"    <description>{skill.description}</description>")
                if skill.tags:
                    lines.append(f"    <tags>{', '.join(skill.tags)}</tags>")
                lines.append(f"    <location>{skill.location}</location>")
                lines.append("  </skill>")
            lines.append("</available_skills>")
            return "\n".join(lines)

        lines = ["## Available Skills"]
        for skill in skills:
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            lines.append(f"- **{skill.name}**{tags_str}: {skill.description}")
        return "\n".join(lines)

    # ── 统计 ──────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取 Skill 统计信息

        Returns:
            统计信息字典
        """
        skills = self.list()
        tags_count: Dict[str, int] = {}
        for skill in skills:
            for tag in skill.tags:
                tags_count[tag] = tags_count.get(tag, 0) + 1

        return {
            "total": len(skills),
            "slash_commands": len(self.slash_skills),
            "tags": tags_count,
            "directories": self.directories,
        }

    # ── 批量操作 ──────────────────────────────────────────────────────────

    def get_skills_by_tags(self, tags: List[str]) -> Dict[str, List[SkillInfo]]:
        """按标签分组获取 Skills

        Args:
            tags: 标签列表

        Returns:
            {tag: [SkillInfo, ...]} 字典
        """
        result: Dict[str, List[SkillInfo]] = {tag: [] for tag in tags}
        for skill in self.list():
            for tag in skill.tags:
                if tag in result:
                    result[tag].append(skill)
        return result

    def search(self, query: str) -> List[SkillInfo]:
        """搜索 Skills（匹配名称、描述或内容）

        Args:
            query: 搜索词

        Returns:
            匹配的 SkillInfo 列表
        """
        return self.filter(search_term=query)

    def get_related_skills(self, name: str) -> List[SkillInfo]:
        """获取与指定 Skill 相关的 Skills（基于标签）

        Args:
            name: Skill 名称

        Returns:
            相关的 SkillInfo 列表
        """
        skill = self.get(name)
        if not skill or not skill.tags:
            return []

        related = []
        for other in self.list():
            if other.name == name:
                continue
            if any(tag in other.tags for tag in skill.tags):
                related.append(other)
        return related

    # ── 导出功能 ──────────────────────────────────────────────────────────

    def export_list_markdown(self, output_path: Optional[str] = None) -> str:
        """导出 Skills 列表为 Markdown 文件

        Args:
            output_path: 输出文件路径（可选）

        Returns:
            Markdown 内容
        """
        content = self.format_list()
        if output_path:
            Path(output_path).write_text(content, encoding="utf-8")
        return content

    def export_detail_markdown(self, name: str, output_path: Optional[str] = None) -> str:
        """导出单个 Skill 详情为 Markdown 文件

        Args:
            name: Skill 名称
            output_path: 输出文件路径（可选）

        Returns:
            Markdown 内容
        """
        content = self.format_detail(name)
        if output_path:
            Path(output_path).write_text(content, encoding="utf-8")
        return content

    # ── 缓存管理 ──────────────────────────────────────────────────────────

    def clear_cache(self) -> None:
        """清除缓存，强制下次访问时重新加载"""
        self._skills = None

    @property
    def is_loaded(self) -> bool:
        """检查是否已加载 Skills"""
        return self._skills is not None

    def __repr__(self) -> str:
        return f"SkillManager(count={self.count}, dirs={self._search_dirs})"

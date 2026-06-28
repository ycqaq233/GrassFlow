"""
GrassFlow 组件注册表

提供组件的发现、注册、查询和加载功能。

参考 DSL v2 规范中的组件发现章节（就近优先发现）：
    1. 当前文件内的 component 定义
    2. 当前目录的 .grass/components/
    3. 项目根目录的 .grass/components/
    4. 全局 ~/.Grass/components/
    5. 远程注册表（未来扩展）

设计原则：
    - 统一的 ComponentEntry 接口
    - 文件系统扫描 + DSL v2 解析器复用
    - 就近优先的发现机制
    - 支持 CLI 管理命令（list / show / search）
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.models import Component, ParseResult
from tui.dsl_parser_v2 import DSLv2Parser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  组件来源
# ---------------------------------------------------------------------------


class ComponentSource:
    """组件来源信息"""

    # 来源类型常量
    FILE_INLINE = "file_inline"  # 文件内定义（当前文件中）
    LOCAL = "local"  # 当前目录 .grass/components/
    PROJECT = "project"  # 项目根目录 .grass/components/
    GLOBAL = "global"  # 全局 ~/.Grass/components/
    PROGRAMMATIC = "programmatic"  # 程序代码直接注册

    # 发现路径优先级（越小越优先）
    PRIORITY_ORDER: Dict[str, int] = {
        FILE_INLINE: 0,
        LOCAL: 1,
        PROJECT: 2,
        GLOBAL: 3,
        PROGRAMMATIC: 4,
    }

    def __init__(self, source_type: str, path: Optional[str] = None):
        self.source_type = source_type
        self.path = path  # 文件路径（file_inline / local / project / global 时有值）
        self.priority = self.PRIORITY_ORDER.get(source_type, 99)

    def __repr__(self) -> str:
        if self.path:
            return f"ComponentSource({self.source_type}, {self.path})"
        return f"ComponentSource({self.source_type})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ComponentSource):
            return NotImplemented
        return self.source_type == other.source_type and self.path == other.path

    def __hash__(self) -> int:
        return hash((self.source_type, self.path))


# ---------------------------------------------------------------------------
#  组件注册条目
# ---------------------------------------------------------------------------


@dataclass
class ComponentEntry:
    """组件注册条目

    包含组件的完整定义和来源信息。
    """

    component: Component  # 组件定义（AST 节点）
    source: ComponentSource  # 组件来源
    discovered_at: float = field(default_factory=time.time)  # 发现时间戳

    @property
    def name(self) -> str:
        """组件名称"""
        return self.component.name

    @property
    def description(self) -> Optional[str]:
        """组件描述"""
        return self.component.description

    @property
    def version(self) -> Optional[str]:
        """组件版本"""
        return self.component.version

    def input_ports(self) -> List[str]:
        """获取所有输入端口名"""
        return [p.name for p in self.component.ports if p.direction == "input"]

    def output_ports(self) -> List[str]:
        """获取所有输出端口名"""
        return [p.name for p in self.component.ports if p.direction == "output"]

    def summary(self) -> Dict[str, Any]:
        """返回组件摘要"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_ports": self.input_ports(),
            "output_ports": self.output_ports(),
            "mcp_servers": [m.server_name for m in self.component.mcp],
            "model": self.component.model.default,
            "source": self.source.source_type,
            "source_path": self.source.path,
        }

    def __repr__(self) -> str:
        return (
            f"ComponentEntry(name={self.name!r}, "
            f"version={self.version!r}, "
            f"source={self.source!r})"
        )


# ---------------------------------------------------------------------------
#  错误类型
# ---------------------------------------------------------------------------


class ComponentRegistryError(Exception):
    """组件注册表相关错误基类"""

    pass


class ComponentNotFoundError(ComponentRegistryError):
    """请求的组件不存在"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Component not found: {name}")


class ComponentDuplicateError(ComponentRegistryError):
    """组件重复注册"""

    def __init__(self, name: str, existing_source: ComponentSource):
        self.name = name
        self.existing_source = existing_source
        super().__init__(
            f"Component '{name}' already registered "
            f"(source={existing_source.source_type}, path={existing_source.path})"
        )


class ComponentLoadError(ComponentRegistryError):
    """组件加载失败"""

    def __init__(self, path: str, detail: str):
        self.path = path
        self.detail = detail
        super().__init__(f"Failed to load component from '{path}': {detail}")


# ---------------------------------------------------------------------------
#  组件注册表
# ---------------------------------------------------------------------------


class ComponentRegistry:
    """组件注册表

    管理所有组件的发现、注册、查询和加载。

    使用方式::

        registry = ComponentRegistry(project_dir="/path/to/project")

        # 扫描并加载所有组件
        registry.discover()

        # 查询组件
        entry = registry.get("code-reviewer")
        components = registry.search("review")

        # 列出所有组件
        for entry in registry.all():
            print(entry.name)

        # 手动注册组件
        registry.register(component, ComponentSource.PROGRAMMATIC)
    """

    def __init__(
        self,
        project_dir: Optional[str] = None,
        global_dir: Optional[str] = None,
        auto_create_dirs: bool = False,
    ):
        """
        Args:
            project_dir: 项目根目录，用于确定 .grass/components/ 路径。
                         默认使用当前工作目录。
            global_dir: 全局组件目录，默认使用 ~/.Grass/components/。
            auto_create_dirs: 是否自动创建不存在的组件目录。
        """
        # 项目根目录
        self._project_dir = Path(project_dir) if project_dir else Path.cwd()

        # 全局组件目录
        if global_dir:
            self._global_dir = Path(global_dir)
        else:
            self._global_dir = Path.home() / ".Grass" / "components"

        self._auto_create_dirs = auto_create_dirs

        # 注册表：组件名 -> ComponentEntry
        self._entries: Dict[str, ComponentEntry] = {}

        # DSL 解析器（复用）
        self._parser = DSLv2Parser()

        # 发现记录：记录每个组件来自哪些路径（用于检测同名冲突警告）
        self._discovered_paths: Dict[str, List[str]] = {}

    # -------------------------------------------------------------------
    #  发现路径
    # -------------------------------------------------------------------

    @property
    def local_components_dir(self) -> Path:
        """当前目录的 .grass/components/"""
        return Path.cwd() / ".grass" / "components"

    @property
    def project_components_dir(self) -> Path:
        """项目根目录的 .grass/components/"""
        return self._project_dir / ".grass" / "components"

    @property
    def global_components_dir(self) -> Path:
        """全局 ~/.Grass/components/"""
        return self._global_dir

    def get_search_paths(self) -> List[Tuple[Path, str]]:
        """返回组件搜索路径列表（按优先级排序）

        Returns:
            (路径, 来源类型) 的列表
        """
        paths = []

        # 当前目录 .grass/components/
        paths.append((self.local_components_dir, ComponentSource.LOCAL))

        # 项目根目录 .grass/components/（可能与 local 相同）
        project_dir = self.project_components_dir
        if project_dir.resolve() != self.local_components_dir.resolve():
            paths.append((project_dir, ComponentSource.PROJECT))
        elif not paths:
            # 如果列表为空（不应发生），也加上
            paths.append((project_dir, ComponentSource.PROJECT))

        # 全局 ~/.Grass/components/
        global_dir = self.global_components_dir
        if global_dir.resolve() not in {p.resolve() for p, _ in paths}:
            paths.append((global_dir, ComponentSource.GLOBAL))

        return paths

    # -------------------------------------------------------------------
    #  发现
    # -------------------------------------------------------------------

    def discover(self) -> int:
        """扫描所有搜索路径并加载组件

        按优先级扫描：
        1. 当前目录 .grass/components/
        2. 项目根目录 .grass/components/
        3. 全局 ~/.Grass/components/

        同名组件冲突时打印警告，优先级高的保留。

        Returns:
            加载的组件数量
        """
        total_loaded = 0
        self._discovered_paths.clear()

        for dir_path, source_type in self.get_search_paths():
            if not dir_path.is_dir():
                if self._auto_create_dirs:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    logger.info("Created component directory: %s", dir_path)
                else:
                    logger.debug("Component directory not found, skipping: %s", dir_path)
                    continue

            count = self._load_from_directory(dir_path, source_type)
            total_loaded += count

        # 检查同名冲突
        self._warn_duplicate_names()

        logger.info("Discovered %d components total", len(self._entries))
        return total_loaded

    def _load_from_directory(self, directory: Path, source_type: str) -> int:
        """从目录加载所有 .gf 文件中的组件

        Args:
            directory: 组件目录路径
            source_type: 来源类型

        Returns:
            加载的组件数量
        """
        count = 0

        # 扫描 .gf 文件（递归）
        gf_files = sorted(directory.rglob("*.gf"))
        logger.debug(
            "Found %d .gf files in %s", len(gf_files), directory
        )

        for gf_file in gf_files:
            try:
                components = self._load_from_file(gf_file, source_type)
                count += len(components)
            except Exception as e:
                logger.warning(
                    "Failed to load components from %s: %s", gf_file, e
                )

        return count

    def _load_from_file(
        self, file_path: Union[str, Path], source_type: str
    ) -> List[Component]:
        """从 .gf 文件加载组件

        Args:
            file_path: .gf 文件路径
            source_type: 来源类型

        Returns:
            加载的组件列表
        """
        file_path = Path(file_path)
        if not file_path.is_file():
            logger.warning("File not found: %s", file_path)
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read file %s: %s", file_path, e)
            return []

        try:
            parse_result = self._parser.parse(content)
        except Exception as e:
            logger.error("Failed to parse file %s: %s", file_path, e)
            return []

        loaded_components: List[Component] = []
        source = ComponentSource(source_type, str(file_path))

        for comp in parse_result.components:
            registered = self._register_if_higher_priority(comp, source)
            if registered:
                loaded_components.append(comp)

            # 记录发现路径（无论是否实际注册，用于冲突警告）
            self._discovered_paths.setdefault(comp.name, []).append(str(file_path))

        return loaded_components

    def _warn_duplicate_names(self) -> None:
        """对在多个路径发现的同名组件打印警告"""
        for name, paths in self._discovered_paths.items():
            if len(paths) > 1:
                logger.warning(
                    "Component '%s' found in multiple locations: %s. "
                    "Using the one with highest priority.",
                    name,
                    paths,
                )

    # -------------------------------------------------------------------
    #  注册
    # -------------------------------------------------------------------

    def register(
        self,
        component: Component,
        source: Optional[ComponentSource] = None,
        overwrite: bool = False,
    ) -> None:
        """手动注册组件

        Args:
            component: 组件定义
            source: 组件来源，默认为 PROGRAMMATIC
            overwrite: 是否覆盖已存在的同名组件

        Raises:
            ComponentDuplicateError: 组件已存在且 overwrite=False
        """
        if source is None:
            source = ComponentSource(ComponentSource.PROGRAMMATIC)

        existing = self._entries.get(component.name)
        if existing is not None and not overwrite:
            raise ComponentDuplicateError(component.name, existing.source)

        entry = ComponentEntry(component=component, source=source)
        self._entries[component.name] = entry
        logger.debug("Registered component '%s' (source=%s)", component.name, source)

    def register_all(
        self,
        components: List[Component],
        source: Optional[ComponentSource] = None,
        overwrite: bool = False,
    ) -> int:
        """批量注册组件

        Args:
            components: 组件定义列表
            source: 组件来源，默认为 PROGRAMMATIC
            overwrite: 是否覆盖已存在的同名组件

        Returns:
            成功注册的组件数量
        """
        count = 0
        for comp in components:
            try:
                self.register(comp, source=source, overwrite=overwrite)
                count += 1
            except ComponentDuplicateError:
                logger.warning(
                    "Skipping duplicate component '%s' during batch registration",
                    comp.name,
                )
        return count

    def _register_if_higher_priority(
        self,
        component: Component,
        source: ComponentSource,
    ) -> bool:
        """仅当来源优先级高于已注册组件时才注册（用于发现机制）

        Args:
            component: 组件定义
            source: 组件来源

        Returns:
            是否成功注册（新注册或替换了已有组件）
        """
        existing = self._entries.get(component.name)
        if existing is None:
            entry = ComponentEntry(component=component, source=source)
            self._entries[component.name] = entry
            logger.debug(
                "Loaded component '%s' from %s", component.name, source.path
            )
            return True

        if source.priority < existing.source.priority:
            entry = ComponentEntry(component=component, source=source)
            self._entries[component.name] = entry
            logger.info(
                "Replaced component '%s': %s (priority %d) -> %s (priority %d)",
                component.name,
                existing.source.source_type,
                existing.source.priority,
                source.source_type,
                source.priority,
            )
            return True

        logger.debug(
            "Skipping duplicate component '%s' from %s "
            "(existing source '%s' has higher priority)",
            component.name,
            source.path,
            existing.source.source_type,
        )
        return False

    def unregister(self, name: str) -> bool:
        """注销组件

        Args:
            name: 组件名称

        Returns:
            是否成功注销
        """
        if name in self._entries:
            del self._entries[name]
            logger.debug("Unregistered component: %s", name)
            return True
        return False

    def clear(self) -> int:
        """清空所有注册的组件

        Returns:
            被清空的组件数量
        """
        count = len(self._entries)
        self._entries.clear()
        self._discovered_paths.clear()
        return count

    # -------------------------------------------------------------------
    #  查询
    # -------------------------------------------------------------------

    def get(self, name: str) -> Optional[ComponentEntry]:
        """根据名称获取组件条目

        Args:
            name: 组件名称

        Returns:
            ComponentEntry 或 None
        """
        return self._entries.get(name)

    def has(self, name: str) -> bool:
        """检查组件是否已注册"""
        return name in self._entries

    def all(self) -> List[ComponentEntry]:
        """返回所有组件条目（按注册顺序）"""
        return list(self._entries.values())

    def names(self) -> List[str]:
        """返回所有组件名称（按注册顺序）"""
        return list(self._entries.keys())

    def search(self, query: str) -> List[ComponentEntry]:
        """搜索组件

        在组件名称和描述中搜索关键词（不区分大小写）。

        Args:
            query: 搜索关键词

        Returns:
            匹配的组件列表
        """
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            if self._matches_query(entry, query_lower):
                results.append(entry)
        return results

    def _matches_query(self, entry: ComponentEntry, query_lower: str) -> bool:
        """检查组件是否匹配搜索查询"""
        # 检查名称
        if query_lower in entry.name.lower():
            return True

        # 检查描述
        if entry.description and query_lower in entry.description.lower():
            return True

        # 检查端口名
        for port in entry.component.ports:
            if query_lower in port.name.lower():
                return True

        # 检查 MCP 服务器名
        for mcp in entry.component.mcp:
            if query_lower in mcp.server_name.lower():
                return True

        return False

    def filter_by_source(self, source_type: str) -> List[ComponentEntry]:
        """按来源类型过滤组件"""
        return [
            e for e in self._entries.values()
            if e.source.source_type == source_type
        ]

    def filter_by_model(self, model: str) -> List[ComponentEntry]:
        """按模型过滤组件"""
        return [
            e for e in self._entries.values()
            if e.component.model.default == model
        ]

    def filter_by_mcp(self, server_name: str) -> List[ComponentEntry]:
        """按 MCP 服务器过滤组件"""
        return [
            e for e in self._entries.values()
            if any(m.server_name == server_name for m in e.component.mcp)
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __iter__(self):
        return iter(self._entries.values())

    # -------------------------------------------------------------------
    #  导入 / 导出
    # -------------------------------------------------------------------

    def import_from_file(self, file_path: Union[str, Path]) -> List[Component]:
        """从 .gf 文件导入组件（注册到 registry）

        Args:
            file_path: .gf 文件路径

        Returns:
            导入的组件列表

        Raises:
            ComponentLoadError: 文件加载失败
        """
        file_path = Path(file_path)
        if not file_path.is_file():
            raise ComponentLoadError(str(file_path), "File not found")

        try:
            content = file_path.read_text(encoding="utf-8")
            parse_result = self._parser.parse(content)
        except Exception as e:
            raise ComponentLoadError(str(file_path), str(e))

        imported = []
        source = ComponentSource(ComponentSource.PROGRAMMATIC, str(file_path))

        for comp in parse_result.components:
            entry = ComponentEntry(component=comp, source=source)
            self._entries[comp.name] = entry
            imported.append(comp)

        return imported

    def load_from_string(
        self,
        dsl_text: str,
        source: Optional[ComponentSource] = None,
    ) -> List[Component]:
        """从 DSL 文本加载组件

        用于从当前文件中提取组件定义（发现路径第 1 层）。
        不会进行优先级冲突检查，直接注册（同名覆盖）。

        Args:
            dsl_text: DSL 文本内容
            source: 组件来源，默认为 FILE_INLINE

        Returns:
            加载的组件列表
        """
        if source is None:
            source = ComponentSource(ComponentSource.FILE_INLINE)

        try:
            parse_result = self._parser.parse(dsl_text)
        except Exception as e:
            logger.error("Failed to parse DSL text: %s", e)
            return []

        loaded = []
        for comp in parse_result.components:
            entry = ComponentEntry(component=comp, source=source)
            self._entries[comp.name] = entry
            loaded.append(comp)
            logger.debug("Loaded component '%s' from DSL text", comp.name)

        return loaded

    def export_component(
        self, name: str, output_path: Union[str, Path]
    ) -> None:
        """将组件导出为独立 .gf 文件

        Args:
            name: 组件名称
            output_path: 输出文件路径

        Raises:
            ComponentNotFoundError: 组件不存在
        """
        entry = self.get(name)
        if entry is None:
            raise ComponentNotFoundError(name)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = self._component_to_dsl(entry.component)
        output_path.write_text(content, encoding="utf-8")
        logger.info("Exported component '%s' to %s", name, output_path)

    def _component_to_dsl(self, comp: Component) -> str:
        """将组件定义转换为 DSL 文本

        Args:
            comp: 组件定义

        Returns:
            DSL 文本
        """
        lines = [f"component {comp.name} {{"]
        lines.append("")

        # 元信息
        if comp.description:
            lines.append(f'    description: "{comp.description}"')
        if comp.version:
            lines.append(f'    version: "{comp.version}"')

        # 提示词
        if comp.system_prompt:
            if "\n" in comp.system_prompt:
                lines.append(f'    system_prompt: """')
                lines.append(f"        {comp.system_prompt}")
                lines.append(f'    """')
            else:
                lines.append(f'    system_prompt: "{comp.system_prompt}"')

        lines.append("")

        # 端口
        for port in comp.ports:
            desc = f' "{port.description}"' if port.description else ""
            lines.append(f"    port {port.direction} {port.name}: {port.type}{desc}")

        if comp.ports:
            lines.append("")

        # MCP
        for mcp in comp.mcp:
            tools_str = ", ".join(mcp.tools)
            lines.append(f"    mcp {mcp.server_name} {{")
            lines.append(f"        tools: [{tools_str}]")
            lines.append(f"    }}")

        if comp.mcp:
            lines.append("")

        # 模型
        if comp.model.default:
            lines.append(f'    model default: "{comp.model.default}"')
        if comp.model.fallback:
            lines.append(f'    model fallback: "{comp.model.fallback}"')
        if comp.model.temperature is not None:
            lines.append(f"    model temperature: {comp.model.temperature}")
        if comp.model.max_tokens is not None:
            lines.append(f"    model max_tokens: {comp.model.max_tokens}")

        if comp.model.default or comp.model.fallback or comp.model.temperature or comp.model.max_tokens:
            lines.append("")

        # 权限
        if comp.permission.allow:
            allow_str = ", ".join(comp.permission.allow)
            lines.append(f"    permission allow: [{allow_str}]")
        if comp.permission.deny:
            deny_str = ", ".join(comp.permission.deny)
            lines.append(f"    permission deny: [{deny_str}]")
        if comp.permission.ask:
            ask_str = ", ".join(comp.permission.ask)
            lines.append(f"    permission ask: [{ask_str}]")

        if comp.permission.allow or comp.permission.deny or comp.permission.ask:
            lines.append("")

        # 执行模式
        if comp.mode != "batch":
            lines.append(f'    mode: "{comp.mode}"')
        if comp.context != "shared":
            lines.append(f'    context: "{comp.context}"')

        # 失败策略
        if comp.on_fail != "stop":
            lines.append(f'    on_fail: "{comp.on_fail}"')
        if comp.on_fail == "retry":
            lines.append(f"    retry_count: {comp.retry_count}")

        lines.append("}")
        lines.append("")

        return "\n".join(lines)

    # -------------------------------------------------------------------
    #  统计 / 摘要
    # -------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """返回注册表摘要信息"""
        by_source: Dict[str, int] = {}
        for entry in self._entries.values():
            src = entry.source.source_type
            by_source[src] = by_source.get(src, 0) + 1

        return {
            "total": len(self._entries),
            "by_source": by_source,
            "names": self.names(),
            "search_paths": [
                str(p) for p, _ in self.get_search_paths()
            ],
        }

    def list_table(self) -> List[Dict[str, str]]:
        """返回适合 CLI 展示的组件列表

        Returns:
            包含 name, description, version, source, ports 列表
        """
        rows = []
        for entry in self._entries.values():
            rows.append({
                "name": entry.name,
                "description": entry.description or "",
                "version": entry.version or "",
                "source": entry.source.source_type,
                "input_ports": ", ".join(entry.input_ports()),
                "output_ports": ", ".join(entry.output_ports()),
            })
        return rows

    def detail(self, name: str) -> Optional[Dict[str, Any]]:
        """返回组件的详细信息

        Args:
            name: 组件名称

        Returns:
            组件详情字典，不存在时返回 None
        """
        entry = self.get(name)
        if entry is None:
            return None

        comp = entry.component
        return {
            "name": comp.name,
            "description": comp.description,
            "version": comp.version,
            "system_prompt": comp.system_prompt,
            "ports": [
                {
                    "name": p.name,
                    "direction": p.direction,
                    "type": p.type,
                    "description": p.description,
                    "sync": p.sync,
                }
                for p in comp.ports
            ],
            "mcp": [
                {
                    "server_name": m.server_name,
                    "tools": m.tools,
                }
                for m in comp.mcp
            ],
            "model": {
                "default": comp.model.default,
                "fallback": comp.model.fallback,
                "temperature": comp.model.temperature,
                "max_tokens": comp.model.max_tokens,
            },
            "permission": {
                "allow": comp.permission.allow,
                "deny": comp.permission.deny,
                "ask": comp.permission.ask,
            },
            "mode": comp.mode,
            "context": comp.context,
            "on_fail": comp.on_fail,
            "retry_count": comp.retry_count,
            "source": {
                "type": entry.source.source_type,
                "path": entry.source.path,
            },
        }

    def get_component(self, name: str) -> Optional[Component]:
        """获取组件的 AST 定义（快捷方法）

        Args:
            name: 组件名称

        Returns:
            Component 或 None
        """
        entry = self.get(name)
        return entry.component if entry else None


# ---------------------------------------------------------------------------
#  默认全局组件注册表（单例）
# ---------------------------------------------------------------------------

_default_registry: Optional[ComponentRegistry] = None


def get_default_component_registry(
    project_dir: Optional[str] = None,
) -> ComponentRegistry:
    """获取默认全局组件注册表（懒初始化单例）

    Args:
        project_dir: 项目根目录，首次创建时使用。
                     后续调用忽略此参数，返回已有的单例。

    Returns:
        ComponentRegistry 实例
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ComponentRegistry(project_dir=project_dir)
    return _default_registry


def reset_default_component_registry() -> ComponentRegistry:
    """重置默认全局组件注册表（主要用于测试）

    Returns:
        新的空 ComponentRegistry 实例
    """
    global _default_registry
    _default_registry = ComponentRegistry()
    return _default_registry

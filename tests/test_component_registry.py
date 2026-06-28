"""
GrassFlow 组件注册表测试

测试组件发现、注册、查询、加载和导出功能。
"""

import os
import pytest
import tempfile
from pathlib import Path

try:
    from core.models import Component, Port, ModelConfig, MCPConfig, PermissionConfig
except ImportError:
    from core.models import Component, Port, ModelConfig, MCPConfig, PermissionConfig
from core.component_registry import (
    ComponentDuplicateError,
    ComponentEntry,
    ComponentLoadError,
    ComponentNotFoundError,
    ComponentRegistry,
    ComponentRegistryError,
    ComponentSource,
    get_default_component_registry,
    reset_default_component_registry,
)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------


def make_reviewer_component() -> Component:
    """代码审查组件"""
    return Component(
        name="code-reviewer",
        description="代码审查专家",
        version="1.0.0",
        system_prompt="审查代码: {code}",
        ports=[
            Port(name="code", direction="input", type="string"),
            Port(name="context", direction="input", type="object"),
            Port(name="issues", direction="output", type="array"),
            Port(name="score", direction="output", type="number"),
        ],
        mcp=[MCPConfig(server_name="github", tools=["add_comment", "create_issue"])],
        model=ModelConfig(default="gpt-4", fallback="gpt-3.5-turbo", temperature=0.3),
        permission=PermissionConfig(
            allow=["github.add_comment"],
            deny=["github.delete_repo"],
            ask=["github.create_issue"],
        ),
    )


def make_classifier_component() -> Component:
    """工单分类组件"""
    return Component(
        name="ticket-classifier",
        description="工单分类器",
        ports=[
            Port(name="ticket", direction="input", type="object"),
            Port(name="category", direction="output", type="string"),
        ],
        model=ModelConfig(default="gpt-4"),
        system_prompt="分类工单: {ticket}",
    )


def make_simple_component() -> Component:
    """简单文本处理组件"""
    return Component(
        name="text-processor",
        description="文本处理器",
        ports=[
            Port(name="text", direction="input", type="string"),
            Port(name="result", direction="output", type="string"),
        ],
        model=ModelConfig(default="gpt-3.5-turbo"),
    )


SAMPLE_GF_CONTENT = """\
component code-reviewer {
    description: "代码审查专家"
    version: "1.0.0"
    system_prompt: "审查代码: {code}"

    port input code: string "待审查的代码"
    port input context: object "上下文信息"
    port output issues: array "问题列表"
    port output score: number "评分"

    model default: "gpt-4"
    model temperature: 0.3

    mcp github {
        tools: [add_comment, create_issue]
    }

    permission allow: [github.add_comment]
    permission deny: [github.delete_repo]
}

component text-processor {
    description: "文本处理器"
    port input text: string
    port output result: string
    model default: "gpt-3.5-turbo"
}
"""

SIMPLE_GF_CONTENT = """\
component my-helper {
    description: "辅助组件"
    port input data: object
    port output output: object
}
"""


# ===========================================================================
#  TestSuite 1: ComponentSource
# ===========================================================================


class TestComponentSource:
    """ComponentSource 测试"""

    def test_source_types(self):
        """所有来源类型常量"""
        assert ComponentSource.FILE_INLINE == "file_inline"
        assert ComponentSource.LOCAL == "local"
        assert ComponentSource.PROJECT == "project"
        assert ComponentSource.GLOBAL == "global"
        assert ComponentSource.PROGRAMMATIC == "programmatic"

    def test_priority_order(self):
        """优先级：file_inline > local > project > global > programmatic"""
        sources = [
            ComponentSource(ComponentSource.PROGRAMMATIC),
            ComponentSource(ComponentSource.GLOBAL),
            ComponentSource(ComponentSource.PROJECT),
            ComponentSource(ComponentSource.LOCAL),
            ComponentSource(ComponentSource.FILE_INLINE),
        ]
        priorities = [s.priority for s in sources]
        # 数值越小优先级越高：file_inline(0) < local(1) < project(2) < global(3) < programmatic(4)
        assert priorities == sorted(priorities, reverse=True)
        assert priorities[0] > priorities[-1]  # programmatic > file_inline

    def test_source_with_path(self):
        """带路径的来源"""
        src = ComponentSource(ComponentSource.LOCAL, "/path/to/file.gf")
        assert src.source_type == "local"
        assert src.path == "/path/to/file.gf"

    def test_source_repr(self):
        """来源的字符串表示"""
        src = ComponentSource(ComponentSource.LOCAL, "/path/file.gf")
        assert "local" in repr(src)
        assert "/path/file.gf" in repr(src)

    def test_source_repr_no_path(self):
        """无路径来源的字符串表示"""
        src = ComponentSource(ComponentSource.PROGRAMMATIC)
        assert "programmatic" in repr(src)

    def test_source_equality(self):
        """来源相等性"""
        src1 = ComponentSource(ComponentSource.LOCAL, "/a.gf")
        src2 = ComponentSource(ComponentSource.LOCAL, "/a.gf")
        src3 = ComponentSource(ComponentSource.LOCAL, "/b.gf")
        assert src1 == src2
        assert src1 != src3

    def test_source_hash(self):
        """来源可哈希"""
        src1 = ComponentSource(ComponentSource.LOCAL, "/a.gf")
        src2 = ComponentSource(ComponentSource.LOCAL, "/a.gf")
        assert hash(src1) == hash(src2)
        # 可以放入 set
        s = {src1, src2}
        assert len(s) == 1


# ===========================================================================
#  TestSuite 2: ComponentEntry
# ===========================================================================


class TestComponentEntry:
    """ComponentEntry 测试"""

    def test_entry_properties(self):
        """条目属性"""
        comp = make_reviewer_component()
        source = ComponentSource(ComponentSource.LOCAL, "/test.gf")
        entry = ComponentEntry(component=comp, source=source)

        assert entry.name == "code-reviewer"
        assert entry.description == "代码审查专家"
        assert entry.version == "1.0.0"

    def test_entry_ports(self):
        """条目端口列表"""
        comp = make_reviewer_component()
        entry = ComponentEntry(
            component=comp,
            source=ComponentSource(ComponentSource.PROGRAMMATIC),
        )

        assert entry.input_ports() == ["code", "context"]
        assert entry.output_ports() == ["issues", "score"]

    def test_entry_summary(self):
        """条目摘要"""
        comp = make_reviewer_component()
        source = ComponentSource(ComponentSource.LOCAL, "/test.gf")
        entry = ComponentEntry(component=comp, source=source)

        summary = entry.summary()
        assert summary["name"] == "code-reviewer"
        assert summary["description"] == "代码审查专家"
        assert summary["version"] == "1.0.0"
        assert summary["input_ports"] == ["code", "context"]
        assert summary["output_ports"] == ["issues", "score"]
        assert summary["mcp_servers"] == ["github"]
        assert summary["model"] == "gpt-4"
        assert summary["source"] == "local"

    def test_entry_repr(self):
        """条目字符串表示"""
        comp = make_reviewer_component()
        entry = ComponentEntry(
            component=comp,
            source=ComponentSource(ComponentSource.LOCAL, "/test.gf"),
        )
        r = repr(entry)
        assert "code-reviewer" in r
        assert "1.0.0" in r

    def test_entry_discovered_at(self):
        """发现时间戳自动设置"""
        comp = Component(name="test")
        entry = ComponentEntry(
            component=comp,
            source=ComponentSource(ComponentSource.PROGRAMMATIC),
        )
        assert entry.discovered_at > 0


# ===========================================================================
#  TestSuite 3: 注册
# ===========================================================================


class TestRegistration:
    """组件注册测试"""

    def test_register_component(self):
        """注册单个组件"""
        registry = ComponentRegistry()
        comp = make_reviewer_component()
        registry.register(comp)

        assert registry.has("code-reviewer")
        assert len(registry) == 1

    def test_register_with_source(self):
        """注册时指定来源"""
        registry = ComponentRegistry()
        comp = make_reviewer_component()
        source = ComponentSource(ComponentSource.LOCAL, "/test.gf")
        registry.register(comp, source=source)

        entry = registry.get("code-reviewer")
        assert entry.source.source_type == "local"

    def test_register_default_source_is_programmatic(self):
        """默认来源为 programmatic"""
        registry = ComponentRegistry()
        comp = make_reviewer_component()
        registry.register(comp)

        entry = registry.get("code-reviewer")
        assert entry.source.source_type == "programmatic"

    def test_register_duplicate_raises(self):
        """重复注册抛异常"""
        registry = ComponentRegistry()
        comp = make_reviewer_component()
        registry.register(comp)

        with pytest.raises(ComponentDuplicateError, match="already registered"):
            registry.register(comp)

    def test_register_duplicate_with_overwrite(self):
        """覆盖注册"""
        registry = ComponentRegistry()
        comp1 = Component(name="x", description="v1")
        comp2 = Component(name="x", description="v2")

        registry.register(comp1)
        registry.register(comp2, overwrite=True)

        assert registry.get("x").description == "v2"

    def test_register_all(self):
        """批量注册"""
        registry = ComponentRegistry()
        comps = [make_reviewer_component(), make_simple_component()]
        count = registry.register_all(comps)

        assert count == 2
        assert registry.has("code-reviewer")
        assert registry.has("text-processor")

    def test_register_all_skips_duplicates(self):
        """批量注册跳过重复"""
        registry = ComponentRegistry()
        comps = [
            make_reviewer_component(),
            make_reviewer_component(),
            make_simple_component(),
        ]
        count = registry.register_all(comps)

        assert count == 2  # 第二个 reviewer 被跳过

    def test_unregister(self):
        """注销组件"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        assert registry.unregister("code-reviewer") is True
        assert not registry.has("code-reviewer")
        assert len(registry) == 0

    def test_unregister_nonexistent(self):
        """注销不存在的组件"""
        registry = ComponentRegistry()
        assert registry.unregister("nonexistent") is False

    def test_clear(self):
        """清空注册表"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        count = registry.clear()
        assert count == 2
        assert len(registry) == 0


# ===========================================================================
#  TestSuite 4: 查询
# ===========================================================================


class TestQuerying:
    """组件查询测试"""

    def test_get_existing(self):
        """获取已注册组件"""
        registry = ComponentRegistry()
        comp = make_reviewer_component()
        registry.register(comp)

        entry = registry.get("code-reviewer")
        assert entry is not None
        assert entry.name == "code-reviewer"

    def test_get_nonexistent(self):
        """获取不存在的组件返回 None"""
        registry = ComponentRegistry()
        assert registry.get("nonexistent") is None

    def test_has(self):
        """检查组件是否存在"""
        registry = ComponentRegistry()
        assert not registry.has("code-reviewer")

        registry.register(make_reviewer_component())
        assert registry.has("code-reviewer")

    def test_all(self):
        """获取所有组件"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        entries = registry.all()
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert names == {"code-reviewer", "text-processor"}

    def test_names(self):
        """获取所有组件名"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        names = registry.names()
        assert "code-reviewer" in names
        assert "text-processor" in names

    def test_search_by_name(self):
        """按名称搜索"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        results = registry.search("reviewer")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    def test_search_by_description(self):
        """按描述搜索"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        results = registry.search("文本")
        assert len(results) == 1
        assert results[0].name == "text-processor"

    def test_search_case_insensitive(self):
        """搜索不区分大小写"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        results = registry.search("CODE")
        assert len(results) == 1

    def test_search_by_port_name(self):
        """按端口名搜索"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        results = registry.search("issues")
        assert len(results) == 1

    def test_search_by_mcp_server(self):
        """按 MCP 服务器名搜索"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        results = registry.search("github")
        assert len(results) == 1

    def test_search_no_match(self):
        """搜索无匹配"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        results = registry.search("nonexistent")
        assert len(results) == 0

    def test_filter_by_source(self):
        """按来源过滤"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(
            make_simple_component(),
            source=ComponentSource(ComponentSource.LOCAL, "/test.gf"),
        )

        programmatic = registry.filter_by_source("programmatic")
        assert len(programmatic) == 1
        assert programmatic[0].name == "code-reviewer"

        local = registry.filter_by_source("local")
        assert len(local) == 1
        assert local[0].name == "text-processor"

    def test_filter_by_model(self):
        """按模型过滤"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())  # gpt-4
        registry.register(make_simple_component())  # gpt-3.5-turbo

        gpt4 = registry.filter_by_model("gpt-4")
        assert len(gpt4) == 1
        assert gpt4[0].name == "code-reviewer"

    def test_filter_by_mcp(self):
        """按 MCP 服务器过滤"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())  # has github MCP
        registry.register(make_simple_component())  # no MCP

        github = registry.filter_by_mcp("github")
        assert len(github) == 1
        assert github[0].name == "code-reviewer"

    def test_get_component_shortcut(self):
        """get_component 快捷方法"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        comp = registry.get_component("code-reviewer")
        assert comp is not None
        assert isinstance(comp, Component)
        assert comp.name == "code-reviewer"

    def test_get_component_nonexistent(self):
        """get_component 不存在时返回 None"""
        registry = ComponentRegistry()
        assert registry.get_component("nonexistent") is None

    def test_contains(self):
        """in 运算符"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        assert "code-reviewer" in registry
        assert "nonexistent" not in registry

    def test_iter(self):
        """迭代注册表"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        names = [e.name for e in registry]
        assert len(names) == 2

    def test_len(self):
        """注册表长度"""
        registry = ComponentRegistry()
        assert len(registry) == 0

        registry.register(make_reviewer_component())
        assert len(registry) == 1


# ===========================================================================
#  TestSuite 5: 详情与展示
# ===========================================================================


class TestDetailAndDisplay:
    """组件详情与展示测试"""

    def test_detail(self):
        """获取组件详情"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        detail = registry.detail("code-reviewer")
        assert detail is not None
        assert detail["name"] == "code-reviewer"
        assert detail["description"] == "代码审查专家"
        assert detail["version"] == "1.0.0"
        assert len(detail["ports"]) == 4
        assert detail["model"]["default"] == "gpt-4"
        assert detail["mcp"][0]["server_name"] == "github"

    def test_detail_nonexistent(self):
        """不存在组件的详情"""
        registry = ComponentRegistry()
        assert registry.detail("nonexistent") is None

    def test_list_table(self):
        """列表展示"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())
        registry.register(make_simple_component())

        table = registry.list_table()
        assert len(table) == 2
        names = {r["name"] for r in table}
        assert names == {"code-reviewer", "text-processor"}

    def test_summary(self):
        """注册表摘要"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        s = registry.summary()
        assert s["total"] == 1
        assert "programmatic" in s["by_source"]
        assert "code-reviewer" in s["names"]


# ===========================================================================
#  TestSuite 6: 文件加载
# ===========================================================================


class TestFileLoading:
    """文件加载测试"""

    def test_load_from_file(self):
        """从 .gf 文件加载组件"""
        registry = ComponentRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            gf_file = Path(tmpdir) / "test.gf"
            gf_file.write_text(SAMPLE_GF_CONTENT, encoding="utf-8")

            components = registry.import_from_file(gf_file)
            assert len(components) == 2

            names = {c.name for c in components}
            assert names == {"code-reviewer", "text-processor"}

    def test_load_from_file_verifies_content(self):
        """加载的组件内容正确"""
        registry = ComponentRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            gf_file = Path(tmpdir) / "test.gf"
            gf_file.write_text(SAMPLE_GF_CONTENT, encoding="utf-8")

            registry.import_from_file(gf_file)

            entry = registry.get("code-reviewer")
            assert entry is not None
            assert entry.description == "代码审查专家"
            assert entry.version == "1.0.0"
            assert len(entry.component.ports) == 4
            assert entry.component.model.default == "gpt-4"

    def test_load_nonexistent_file(self):
        """加载不存在的文件"""
        registry = ComponentRegistry()
        with pytest.raises(ComponentLoadError, match="File not found"):
            registry.import_from_file("/nonexistent/path.gf")

    def test_load_from_string(self):
        """从 DSL 文本加载"""
        registry = ComponentRegistry()
        components = registry.load_from_string(SAMPLE_GF_CONTENT)

        assert len(components) == 2
        assert registry.has("code-reviewer")
        assert registry.has("text-processor")

    def test_load_from_string_with_source(self):
        """从 DSL 文本加载并指定来源"""
        registry = ComponentRegistry()
        source = ComponentSource(ComponentSource.FILE_INLINE)
        components = registry.load_from_string(SAMPLE_GF_CONTENT, source=source)

        entry = registry.get("code-reviewer")
        assert entry.source.source_type == "file_inline"

    def test_load_from_string_default_source(self):
        """从 DSL 文本加载默认来源为 file_inline"""
        registry = ComponentRegistry()
        registry.load_from_string(SAMPLE_GF_CONTENT)

        entry = registry.get("code-reviewer")
        assert entry.source.source_type == "file_inline"

    def test_load_from_string_overwrites(self):
        """从 DSL 文本加载会覆盖同名组件"""
        registry = ComponentRegistry()
        registry.register(Component(name="code-reviewer", description="old"))

        registry.load_from_string(SAMPLE_GF_CONTENT)
        entry = registry.get("code-reviewer")
        assert entry.description == "代码审查专家"


# ===========================================================================
#  TestSuite 7: 文件系统发现
# ===========================================================================


class TestDiscovery:
    """文件系统发现测试"""

    def test_discover_local_components(self):
        """发现当前目录 .grass/components/ 中的组件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 .grass/components/ 目录
            components_dir = Path(tmpdir) / ".grass" / "components"
            components_dir.mkdir(parents=True)

            # 写入 .gf 文件
            gf_file = components_dir / "reviewer.gf"
            gf_file.write_text(SIMPLE_GF_CONTENT, encoding="utf-8")

            # 使用 tmpdir 作为 cwd
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                registry = ComponentRegistry(project_dir=tmpdir)
                count = registry.discover()

                assert count == 1
                assert registry.has("my-helper")
            finally:
                os.chdir(original_cwd)

    def test_discover_project_components(self):
        """发现项目根目录 .grass/components/ 中的组件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建项目 .grass/components/ 目录
            components_dir = Path(tmpdir) / ".grass" / "components"
            components_dir.mkdir(parents=True)

            gf_file = components_dir / "helper.gf"
            gf_file.write_text(SIMPLE_GF_CONTENT, encoding="utf-8")

            registry = ComponentRegistry(project_dir=tmpdir)
            count = registry.discover()

            assert count == 1
            assert registry.has("my-helper")

    def test_discover_global_components(self):
        """发现全局 ~/.Grass/components/ 中的组件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            global_dir = Path(tmpdir) / "components"
            global_dir.mkdir(parents=True)

            gf_file = global_dir / "global.gf"
            gf_file.write_text(SIMPLE_GF_CONTENT, encoding="utf-8")

            registry = ComponentRegistry(global_dir=str(global_dir))
            count = registry.discover()

            assert count == 1
            assert registry.has("my-helper")

    def test_discover_priority_local_over_global(self):
        """本地组件优先于全局组件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 全局目录
            global_dir = Path(tmpdir) / "global_components"
            global_dir.mkdir()
            (global_dir / "x.gf").write_text(
                'component my-comp { description: "global version" }',
                encoding="utf-8",
            )

            # 本地目录
            local_dir = Path(tmpdir) / ".grass" / "components"
            local_dir.mkdir(parents=True)
            (local_dir / "x.gf").write_text(
                'component my-comp { description: "local version" }',
                encoding="utf-8",
            )

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                registry = ComponentRegistry(
                    project_dir=tmpdir,
                    global_dir=str(global_dir),
                )
                registry.discover()

                entry = registry.get("my-comp")
                assert entry is not None
                assert entry.description == "local version"
            finally:
                os.chdir(original_cwd)

    def test_discover_empty_directory(self):
        """空目录不报错"""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir) / "empty"
            empty_dir.mkdir()

            registry = ComponentRegistry(project_dir=str(empty_dir))
            count = registry.discover()
            assert count == 0

    def test_discover_nonexistent_directory(self):
        """不存在的目录不报错"""
        registry = ComponentRegistry(project_dir="/nonexistent/path/abc123")
        count = registry.discover()
        assert count == 0

    def test_discover_auto_create_dirs(self):
        """自动创建目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "myproject"
            registry = ComponentRegistry(
                project_dir=str(project_dir),
                auto_create_dirs=True,
            )
            registry.discover()

            expected_dir = project_dir / ".grass" / "components"
            assert expected_dir.is_dir()

    def test_discover_recursive(self):
        """递归扫描子目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            components_dir = Path(tmpdir) / ".grass" / "components"
            subdir = components_dir / "subdir"
            subdir.mkdir(parents=True)

            (subdir / "nested.gf").write_text(SIMPLE_GF_CONTENT, encoding="utf-8")

            registry = ComponentRegistry(project_dir=tmpdir)
            count = registry.discover()

            assert count == 1
            assert registry.has("my-helper")

    def test_discover_multiple_files(self):
        """扫描多个 .gf 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            components_dir = Path(tmpdir) / ".grass" / "components"
            components_dir.mkdir(parents=True)

            (components_dir / "a.gf").write_text(SIMPLE_GF_CONTENT, encoding="utf-8")
            (components_dir / "b.gf").write_text(
                'component other { description: "other" }',
                encoding="utf-8",
            )

            registry = ComponentRegistry(project_dir=tmpdir)
            count = registry.discover()

            assert count == 2
            assert registry.has("my-helper")
            assert registry.has("other")

    def test_get_search_paths(self):
        """获取搜索路径列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ComponentRegistry(project_dir=tmpdir)
            paths = registry.get_search_paths()

            assert len(paths) >= 2  # 至少有 local 和 project/global
            # 每个元素是 (Path, source_type)
            for path, source_type in paths:
                assert isinstance(path, Path)
                assert isinstance(source_type, str)


# ===========================================================================
#  TestSuite 8: 导出
# ===========================================================================


class TestExport:
    """组件导出测试"""

    def test_export_component(self):
        """导出组件为 .gf 文件"""
        registry = ComponentRegistry()
        registry.register(make_reviewer_component())

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "exported.gf"
            registry.export_component("code-reviewer", output)

            assert output.is_file()
            content = output.read_text(encoding="utf-8")
            assert "component code-reviewer" in content
            assert "审查代码" in content

    def test_export_nonexistent(self):
        """导出不存在的组件"""
        registry = ComponentRegistry()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.gf"
            with pytest.raises(ComponentNotFoundError):
                registry.export_component("nonexistent", output)

    def test_export_creates_parent_dirs(self):
        """导出时自动创建父目录"""
        registry = ComponentRegistry()
        registry.register(make_simple_component())

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "subdir" / "deep" / "exported.gf"
            registry.export_component("text-processor", output)

            assert output.is_file()

    def test_export_roundtrip(self):
        """导出后再导入，内容一致"""
        registry1 = ComponentRegistry()
        registry1.register(make_reviewer_component())

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "roundtrip.gf"
            registry1.export_component("code-reviewer", output)

            registry2 = ComponentRegistry()
            registry2.import_from_file(output)

            entry = registry2.get("code-reviewer")
            assert entry is not None
            assert entry.description == "代码审查专家"
            assert entry.version == "1.0.0"
            assert len(entry.component.ports) == 4


# ===========================================================================
#  TestSuite 9: 错误类型
# ===========================================================================


class TestErrorTypes:
    """错误类型测试"""

    def test_registry_error_hierarchy(self):
        """错误类型继承关系"""
        assert issubclass(ComponentNotFoundError, ComponentRegistryError)
        assert issubclass(ComponentDuplicateError, ComponentRegistryError)
        assert issubclass(ComponentLoadError, ComponentRegistryError)

    def test_not_found_error(self):
        """ComponentNotFoundError"""
        err = ComponentNotFoundError("my-comp")
        assert err.name == "my-comp"
        assert "my-comp" in str(err)

    def test_duplicate_error(self):
        """ComponentDuplicateError"""
        source = ComponentSource(ComponentSource.LOCAL, "/test.gf")
        err = ComponentDuplicateError("my-comp", source)
        assert err.name == "my-comp"
        assert err.existing_source == source
        assert "my-comp" in str(err)
        assert "already registered" in str(err)

    def test_load_error(self):
        """ComponentLoadError"""
        err = ComponentLoadError("/path/file.gf", "parse error")
        assert err.path == "/path/file.gf"
        assert err.detail == "parse error"
        assert "/path/file.gf" in str(err)


# ===========================================================================
#  TestSuite 10: 单例管理
# ===========================================================================


class TestSingleton:
    """默认全局注册表测试"""

    def setup_method(self):
        """每个测试前重置单例"""
        reset_default_component_registry()

    def test_get_default_registry(self):
        """获取默认注册表"""
        registry = get_default_component_registry()
        assert isinstance(registry, ComponentRegistry)

    def test_default_registry_is_singleton(self):
        """默认注册表是单例"""
        r1 = get_default_component_registry()
        r2 = get_default_component_registry()
        assert r1 is r2

    def test_reset_default_registry(self):
        """重置默认注册表"""
        r1 = get_default_component_registry()
        r1.register(make_reviewer_component())

        r2 = reset_default_component_registry()
        assert r2 is not r1
        assert len(r2) == 0

    def teardown_method(self):
        """每个测试后重置单例"""
        reset_default_component_registry()


# ===========================================================================
#  TestSuite 11: 集成测试
# ===========================================================================


class TestIntegration:
    """端到端集成测试"""

    def test_full_discovery_workflow(self):
        """完整的发现 -> 查询 -> 导出流程"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 设置目录结构
            local_dir = Path(tmpdir) / ".grass" / "components"
            local_dir.mkdir(parents=True)

            # 写入组件文件
            (local_dir / "reviewer.gf").write_text(SAMPLE_GF_CONTENT, encoding="utf-8")

            # 发现
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                registry = ComponentRegistry(project_dir=tmpdir)
                count = registry.discover()

                assert count == 2

                # 查询
                reviewer = registry.get("code-reviewer")
                assert reviewer is not None
                assert reviewer.description == "代码审查专家"

                processor = registry.get("text-processor")
                assert processor is not None

                # 搜索
                results = registry.search("审查")
                assert len(results) == 1

                # 详情
                detail = registry.detail("code-reviewer")
                assert detail["model"]["default"] == "gpt-4"

                # 导出
                export_path = Path(tmpdir) / "exported.gf"
                registry.export_component("text-processor", export_path)
                assert export_path.is_file()

                # 导出后再导入验证
                registry2 = ComponentRegistry()
                registry2.import_from_file(export_path)
                assert registry2.has("text-processor")

            finally:
                os.chdir(original_cwd)

    def test_discover_with_mixed_sources(self):
        """混合来源的发现"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 全局目录有组件 A
            global_dir = Path(tmpdir) / "global"
            global_dir.mkdir()
            (global_dir / "a.gf").write_text(
                'component shared-comp { description: "from global" }',
                encoding="utf-8",
            )

            # 项目目录有同名组件 A 和新组件 B
            project_dir = Path(tmpdir) / "project"
            components_dir = project_dir / ".grass" / "components"
            components_dir.mkdir(parents=True)
            (components_dir / "a.gf").write_text(
                'component shared-comp { description: "from project" }',
                encoding="utf-8",
            )
            (components_dir / "b.gf").write_text(
                'component project-only { description: "project only" }',
                encoding="utf-8",
            )

            registry = ComponentRegistry(
                project_dir=str(project_dir),
                global_dir=str(global_dir),
            )
            registry.discover()

            # 项目版本优先
            shared = registry.get("shared-comp")
            assert shared.description == "from project"

            # 全局独有组件也被发现
            assert registry.has("project-only")

    def test_programmatic_register_then_discover(self):
        """程序注册后发现，高优先级来源保留"""
        with tempfile.TemporaryDirectory() as tmpdir:
            components_dir = Path(tmpdir) / ".grass" / "components"
            components_dir.mkdir(parents=True)
            (components_dir / "x.gf").write_text(
                'component my-comp { description: "from file" }',
                encoding="utf-8",
            )

            registry = ComponentRegistry(project_dir=tmpdir)

            # 先手动注册
            registry.register(
                Component(name="my-comp", description="programmatic"),
            )
            assert registry.get("my-comp").description == "programmatic"

            # 发现后，programmatic 优先级低于 local，会被替换
            registry.discover()
            entry = registry.get("my-comp")
            assert entry.description == "from file"

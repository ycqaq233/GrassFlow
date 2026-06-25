"""
GrassFlow Skills 管理器测试

测试覆盖：
- YAML frontmatter 解析
- SKILL.md 文件加载
- 多目录发现机制
- 渐进式披露格式化
- SkillManager 完整功能
"""

import os
import tempfile
from pathlib import Path

import pytest

from core.skills import (
    SkillInfo,
    SkillManager,
    SkillNameMismatchError,
    SkillNotFoundError,
    SkillParseError,
    _coerce_value,
    _parse_yaml_simple,
    discover_skill_files,
    load_skill_file,
    load_skills,
    parse_frontmatter,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_skills_dir(tmp_path):
    """创建一个临时 skills 目录结构"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


@pytest.fixture
def sample_skill_file(tmp_skills_dir):
    """创建一个示例 SKILL.md 文件"""
    skill_dir = tmp_skills_dir / "code-reviewer"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: code-reviewer
description: Code review expert
slash: true
---

# Code Reviewer

Review code for quality, security, and performance.

## Usage

Provide the code to review as input.
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def sample_skill_minimal(tmp_skills_dir):
    """创建一个最小 SKILL.md 文件（只有 name）"""
    skill_dir = tmp_skills_dir / "minimal"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: minimal
---
Just a minimal skill.
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def sample_skill_extra_metadata(tmp_skills_dir):
    """创建一个包含额外 metadata 的 SKILL.md 文件"""
    skill_dir = tmp_skills_dir / "advanced"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: advanced-skill
description: Advanced skill with extra metadata
version: "2.0"
author: test-user
tags:
  - code
  - review
---

# Advanced Skill

Content here.
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture
def multi_dir_setup(tmp_path):
    """创建多目录结构，用于测试发现机制"""
    # 目录 1: 项目级
    project_dir = tmp_path / "project" / ".grass" / "skills"
    project_skill = project_dir / "project-skill"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        """---
name: project-skill
description: Project level skill
---
Project content
""",
        encoding="utf-8",
    )

    # 目录 2: 全局级
    global_dir = tmp_path / "global" / ".Grass" / "skills"
    global_skill = global_dir / "global-skill"
    global_skill.mkdir(parents=True)
    (global_skill / "SKILL.md").write_text(
        """---
name: global-skill
description: Global level skill
---
Global content
""",
        encoding="utf-8",
    )

    # 目录 3: 全局级另一个，嵌套子目录
    nested_skill = global_dir / "nested" / "deep-skill"
    nested_skill.mkdir(parents=True)
    (nested_skill / "SKILL.md").write_text(
        """---
name: deep-skill
description: Deeply nested skill
---
Deep content
""",
        encoding="utf-8",
    )

    return {
        "project_dir": tmp_path / "project" / ".grass",
        "global_dir": tmp_path / "global" / ".Grass",
    }


# ── Frontmatter 解析测试 ─────────────────────────────────────────────────────


class TestParseFrontmatter:
    """测试 YAML frontmatter 解析"""

    def test_basic_parse(self):
        content = "---\nname: test\ndescription: A test skill\n---\nBody here"
        metadata, body = parse_frontmatter(content)
        assert metadata["name"] == "test"
        assert metadata["description"] == "A test skill"
        assert body == "Body here"

    def test_empty_body(self):
        content = "---\nname: test\n---\n"
        metadata, body = parse_frontmatter(content)
        assert metadata["name"] == "test"
        assert body.strip() == ""

    def test_multiline_body(self):
        content = "---\nname: test\n---\n# Title\n\nParagraph 1\n\nParagraph 2"
        metadata, body = parse_frontmatter(content)
        assert "# Title" in body
        assert "Paragraph 1" in body

    def test_quoted_values(self):
        content = '---\nname: test\ndescription: "A quoted value"\n---\n'
        metadata, body = parse_frontmatter(content)
        assert metadata["description"] == "A quoted value"

    def test_single_quoted_values(self):
        content = "---\nname: test\ndescription: 'Single quoted'\n---\n"
        metadata, body = parse_frontmatter(content)
        assert metadata["description"] == "Single quoted"

    def test_boolean_values(self):
        content = "---\nname: test\nslash: true\nactive: false\n---\n"
        metadata, body = parse_frontmatter(content)
        assert metadata["slash"] is True
        assert metadata["active"] is False

    def test_numeric_values(self):
        content = "---\nname: test\nversion: 42\nratio: 3.14\n---\n"
        metadata, body = parse_frontmatter(content)
        assert metadata["version"] == 42
        assert metadata["ratio"] == 3.14

    def test_no_frontmatter_raises(self):
        content = "Just some text without frontmatter"
        with pytest.raises(SkillParseError):
            parse_frontmatter(content)

    def test_empty_frontmatter(self):
        content = "---\n---\nBody"
        metadata, body = parse_frontmatter(content)
        assert metadata == {}

    def test_frontmatter_with_comments(self):
        content = "---\n# This is a comment\nname: test\n# Another comment\n---\nBody"
        metadata, body = parse_frontmatter(content)
        assert metadata["name"] == "test"


class TestYamlSimpleParser:
    """测试简单 YAML 解析器"""

    def test_simple_key_value(self):
        result = _parse_yaml_simple("name: test\ndescription: hello")
        assert result == {"name": "test", "description": "hello"}

    def test_boolean_coercion(self):
        result = _parse_yaml_simple("a: true\nb: false\nc: yes\nd: no")
        assert result["a"] is True
        assert result["b"] is False
        assert result["c"] is True
        assert result["d"] is False

    def test_number_coercion(self):
        result = _parse_yaml_simple("int: 42\nfloat: 3.14")
        assert result["int"] == 42
        assert result["float"] == 3.14

    def test_quoted_strings(self):
        result = _parse_yaml_simple('a: "hello world"\nb: \'single quotes\'')
        assert result["a"] == "hello world"
        assert result["b"] == "single quotes"

    def test_comments_skipped(self):
        result = _parse_yaml_simple("# comment\nname: test\n# another")
        assert result == {"name": "test"}

    def test_empty_lines_skipped(self):
        result = _parse_yaml_simple("\nname: test\n\nvalue: 42\n")
        assert result == {"name": "test", "value": 42}

    def test_empty_input(self):
        result = _parse_yaml_simple("")
        assert result == {}

    def test_null_values(self):
        result = _parse_yaml_simple("a: null\nb: ~")
        assert result["a"] is None
        assert result["b"] is None


class TestCoerceValue:
    """测试值类型转换"""

    def test_empty_string(self):
        assert _coerce_value("") == ""

    def test_quoted_string(self):
        assert _coerce_value('"hello"') == "hello"
        assert _coerce_value("'world'") == "world"

    def test_boolean(self):
        assert _coerce_value("true") is True
        assert _coerce_value("True") is True
        assert _coerce_value("false") is False
        assert _coerce_value("yes") is True
        assert _coerce_value("no") is False

    def test_integer(self):
        assert _coerce_value("42") == 42
        assert _coerce_value("-1") == -1

    def test_float(self):
        assert _coerce_value("3.14") == pytest.approx(3.14)

    def test_null(self):
        assert _coerce_value("null") is None
        assert _coerce_value("~") is None

    def test_plain_string(self):
        assert _coerce_value("hello world") == "hello world"


# ── Skill 文件加载测试 ────────────────────────────────────────────────────────


class TestLoadSkillFile:
    """测试单个 SKILL.md 文件加载"""

    def test_load_basic(self, sample_skill_file):
        info = load_skill_file(sample_skill_file)
        assert info.name == "code-reviewer"
        assert info.description == "Code review expert"
        assert info.slash is True
        assert "# Code Reviewer" in info.content
        assert info.location == str(sample_skill_file.resolve())

    def test_load_minimal(self, sample_skill_minimal):
        info = load_skill_file(sample_skill_minimal)
        assert info.name == "minimal"
        assert info.description is None
        assert info.slash is False

    def test_load_extra_metadata(self, sample_skill_extra_metadata):
        info = load_skill_file(sample_skill_extra_metadata)
        assert info.name == "advanced-skill"
        assert info.metadata.get("version") == "2.0"
        assert info.metadata.get("author") == "test-user"

    def test_load_nonexistent_file(self, tmp_path):
        with pytest.raises(SkillParseError):
            load_skill_file(tmp_path / "nonexistent" / "SKILL.md")

    def test_load_no_frontmatter(self, tmp_path):
        bad_file = tmp_path / "SKILL.md"
        bad_file.write_text("No frontmatter here", encoding="utf-8")
        with pytest.raises(SkillParseError):
            load_skill_file(bad_file)

    def test_load_missing_name(self, tmp_path):
        bad_file = tmp_path / "SKILL.md"
        bad_file.write_text("---\ndescription: no name\n---\n", encoding="utf-8")
        with pytest.raises(SkillParseError):
            load_skill_file(bad_file)


# ── SkillInfo 渐进式披露测试 ─────────────────────────────────────────────────


class TestSkillInfoFormatting:
    """测试 SkillInfo 的渐进式披露格式化"""

    @pytest.fixture
    def skill_info(self):
        return SkillInfo(
            name="test-skill",
            description="A test skill for testing",
            slash=True,
            location="/some/path/SKILL.md",
            content="# Test\n\nHello world",
            metadata={"version": "1.0"},
        )

    def test_to_list_line(self, skill_info):
        line = skill_info.to_list_line()
        assert "**test-skill**" in line
        assert "A test skill for testing" in line

    def test_to_list_line_no_description(self):
        info = SkillInfo(name="no-desc")
        line = info.to_list_line()
        assert "**no-desc**" in line
        assert ":" not in line

    def test_to_detail(self, skill_info):
        detail = skill_info.to_detail()
        assert "## test-skill" in detail
        assert "A test skill for testing" in detail
        assert "Slash command: yes" in detail
        assert "/some/path/SKILL.md" in detail
        assert "version: 1.0" in detail
        assert "# Test" in detail

    def test_to_full(self, skill_info):
        full = skill_info.to_full()
        assert full.startswith("---")
        assert "name: test-skill" in full
        assert "description: A test skill for testing" in full
        assert "slash: true" in full
        assert "---" in full
        assert "# Test" in full
        assert "Hello world" in full

    def test_to_full_minimal(self):
        info = SkillInfo(name="min", content="body")
        full = info.to_full()
        assert "name: min" in full
        assert "description:" not in full
        assert "slash:" not in full


# ── 文件发现测试 ──────────────────────────────────────────────────────────────


class TestDiscovery:
    """测试多目录发现机制"""

    def test_discover_single_dir(self, tmp_skills_dir, sample_skill_file):
        files = discover_skill_files([tmp_skills_dir.parent])
        assert len(files) == 1
        assert files[0].name == "SKILL.md"

    def test_discover_multiple_dirs(self, multi_dir_setup):
        dirs = list(multi_dir_setup.values())
        files = discover_skill_files(dirs)
        names = {f.parent.name for f in files}
        assert "project-skill" in names
        assert "global-skill" in names
        assert "deep-skill" in names

    def test_discover_nonexistent_dir(self, tmp_path):
        files = discover_skill_files([tmp_path / "nonexistent"])
        assert files == []

    def test_discover_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty" / "skills"
        empty_dir.mkdir(parents=True)
        files = discover_skill_files([tmp_path / "empty"])
        assert files == []

    def test_discover_nested(self, multi_dir_setup):
        """测试嵌套子目录中的 Skill 能被发现"""
        dirs = [multi_dir_setup["global_dir"]]
        files = discover_skill_files(dirs)
        names = {f.parent.name for f in files}
        assert "global-skill" in names
        assert "deep-skill" in names

    def test_scan_skill_files(self, tmp_skills_dir, sample_skill_file):
        from core.skills import _scan_skill_files

        files = _scan_skill_files(tmp_skills_dir.parent)
        assert len(files) == 1

    def test_scan_no_skills_subdir(self, tmp_path):
        from core.skills import _scan_skill_files

        files = _scan_skill_files(tmp_path)
        assert files == []


# ── load_skills 测试 ──────────────────────────────────────────────────────────


class TestLoadSkills:
    """测试批量加载 Skills"""

    def test_load_from_single_dir(self, tmp_skills_dir, sample_skill_file):
        skills = load_skills([tmp_skills_dir.parent])
        assert "code-reviewer" in skills
        assert skills["code-reviewer"].description == "Code review expert"

    def test_load_from_multi_dir(self, multi_dir_setup):
        dirs = list(multi_dir_setup.values())
        skills = load_skills(dirs)
        assert "project-skill" in skills
        assert "global-skill" in skills
        assert "deep-skill" in skills

    def test_load_empty(self, tmp_path):
        skills = load_skills([tmp_path])
        assert skills == {}

    def test_load_duplicate_name_overwrite(self, tmp_path):
        """同名 Skill 后加载的覆盖先加载的"""
        # 第一个
        dir1 = tmp_path / "dir1" / "skills" / "dup"
        dir1.mkdir(parents=True)
        (dir1 / "SKILL.md").write_text(
            "---\nname: dup\ndescription: first\n---\nFirst", encoding="utf-8"
        )
        # 第二个（同名）
        dir2 = tmp_path / "dir2" / "skills" / "dup"
        dir2.mkdir(parents=True)
        (dir2 / "SKILL.md").write_text(
            "---\nname: dup\ndescription: second\n---\nSecond", encoding="utf-8"
        )

        skills = load_skills([tmp_path / "dir1", tmp_path / "dir2"])
        assert skills["dup"].description == "second"


# ── SkillManager 测试 ─────────────────────────────────────────────────────────


class TestSkillManager:
    """测试 SkillManager 完整功能"""

    @pytest.fixture
    def manager(self, multi_dir_setup):
        dirs = list(multi_dir_setup.values())
        return SkillManager(search_dirs=dirs)

    def test_list(self, manager):
        skills = manager.list()
        names = [s.name for s in skills]
        assert names == sorted(names)  # 按名称排序
        assert len(skills) == 3

    def test_get(self, manager):
        skill = manager.get("project-skill")
        assert skill is not None
        assert skill.name == "project-skill"
        assert skill.description == "Project level skill"

    def test_get_not_found(self, manager):
        assert manager.get("nonexistent") is None

    def test_require(self, manager):
        skill = manager.require("global-skill")
        assert skill.name == "global-skill"

    def test_require_not_found(self, manager):
        with pytest.raises(SkillNotFoundError) as exc_info:
            manager.require("nonexistent")
        assert "nonexistent" in str(exc_info.value)
        assert "project-skill" in str(exc_info.value)

    def test_has(self, manager):
        assert manager.has("project-skill") is True
        assert manager.has("nonexistent") is False

    def test_count(self, manager):
        assert manager.count == 3

    def test_directories(self, manager):
        dirs = manager.directories
        assert len(dirs) > 0
        # 每个目录都是包含 SKILL.md 的父目录
        for d in dirs:
            assert Path(d, "SKILL.md").exists()

    def test_reload(self, manager):
        _ = manager.list()  # 触发加载
        assert manager._skills is not None
        manager.reload()
        # reload 后重新懒加载
        assert manager._skills is None

    def test_slash_skills(self, tmp_path):
        """测试 slash 属性过滤"""
        skill_dir = tmp_path / "skills" / "s1"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: s1\nslash: true\n---\n", encoding="utf-8"
        )
        skill_dir2 = tmp_path / "skills" / "s2"
        skill_dir2.mkdir(parents=True)
        (skill_dir2 / "SKILL.md").write_text(
            "---\nname: s2\nslash: false\n---\n", encoding="utf-8"
        )
        skill_dir3 = tmp_path / "skills" / "s3"
        skill_dir3.mkdir(parents=True)
        (skill_dir3 / "SKILL.md").write_text(
            "---\nname: s3\n---\n", encoding="utf-8"
        )

        manager = SkillManager(search_dirs=[tmp_path])
        slash = manager.slash_skills
        assert len(slash) == 1
        assert slash[0].name == "s1"

    def test_repr(self, manager):
        r = repr(manager)
        assert "SkillManager" in r
        assert "count=" in r


# ── 渐进式披露格式化测试 ─────────────────────────────────────────────────────


class TestProgressiveDisclosure:
    """测试渐进式披露格式化"""

    @pytest.fixture
    def manager(self, multi_dir_setup):
        dirs = list(multi_dir_setup.values())
        return SkillManager(search_dirs=dirs)

    def test_format_list(self, manager):
        output = manager.format_list()
        assert "## Available Skills" in output
        assert "**project-skill**" in output
        assert "**global-skill**" in output
        assert "**deep-skill**" in output

    def test_format_list_empty(self, tmp_path):
        manager = SkillManager(search_dirs=[tmp_path])
        assert "No skills" in manager.format_list()

    def test_format_detail(self, manager):
        detail = manager.format_detail("project-skill")
        assert "## project-skill" in detail
        assert "Project level skill" in detail
        assert "Location:" in detail

    def test_format_detail_not_found(self, manager):
        with pytest.raises(SkillNotFoundError):
            manager.format_detail("nonexistent")

    def test_format_full(self, manager):
        full = manager.format_full("project-skill")
        assert full.startswith("---")
        assert "name: project-skill" in full
        assert "Project content" in full

    def test_format_full_not_found(self, manager):
        with pytest.raises(SkillNotFoundError):
            manager.format_full("nonexistent")

    def test_format_for_agent_markdown(self, manager):
        output = manager.format_for_agent(verbose=False)
        assert "## Available Skills" in output
        assert "**project-skill**: Project level skill" in output

    def test_format_for_agent_xml(self, manager):
        output = manager.format_for_agent(verbose=True)
        assert "<available_skills>" in output
        assert "<name>project-skill</name>" in output
        assert "<description>Project level skill</description>" in output
        assert "</available_skills>" in output

    def test_format_for_agent_empty(self, tmp_path):
        manager = SkillManager(search_dirs=[tmp_path])
        assert "No skills" in manager.format_for_agent()


# ── 集成测试 ──────────────────────────────────────────────────────────────────


class TestIntegration:
    """端到端集成测试"""

    def test_full_workflow(self, tmp_path):
        """完整的发现 → 加载 → 查询 → 格式化流程"""
        # 1. 创建 Skill 文件
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: my-skill
description: An integration test skill
slash: true
version: "1.0"
---

# My Skill

This is a test skill for integration testing.

## Steps

1. Read input
2. Process
3. Output
""",
            encoding="utf-8",
        )

        # 2. 创建 SkillManager
        manager = SkillManager(search_dirs=[tmp_path])

        # 3. 验证发现
        assert manager.count == 1

        # 4. 验证查询
        skill = manager.get("my-skill")
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.description == "An integration test skill"
        assert skill.slash is True
        assert skill.metadata.get("version") == "1.0"

        # 5. 验证渐进式披露
        list_output = manager.format_list()
        assert "my-skill" in list_output

        detail_output = manager.format_detail("my-skill")
        assert "integration test skill" in detail_output
        assert "version: 1.0" in detail_output

        full_output = manager.format_full("my-skill")
        assert "---" in full_output
        assert "# My Skill" in full_output
        assert "Steps" in full_output

        # 6. 验证 agent 格式
        agent_output = manager.format_for_agent(verbose=False)
        assert "my-skill" in agent_output

    def test_priority_override(self, tmp_path):
        """后发现的同名 Skill 覆盖先发现的"""
        # 低优先级目录
        low_dir = tmp_path / "low" / "skills" / "shared"
        low_dir.mkdir(parents=True)
        (low_dir / "SKILL.md").write_text(
            "---\nname: shared\ndescription: low priority\n---\nLow", encoding="utf-8"
        )

        # 高优先级目录
        high_dir = tmp_path / "high" / "skills" / "shared"
        high_dir.mkdir(parents=True)
        (high_dir / "SKILL.md").write_text(
            "---\nname: shared\ndescription: high priority\n---\nHigh", encoding="utf-8"
        )

        # 先 low 后 high，high 应覆盖 low
        manager = SkillManager(
            search_dirs=[tmp_path / "low", tmp_path / "high"]
        )
        skill = manager.require("shared")
        assert skill.description == "high priority"
        assert "High" in skill.content

    def test_special_characters_in_name(self, tmp_path):
        """测试名称中包含连字符等特殊字符"""
        skill_dir = tmp_path / "skills" / "my-special-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-special-skill\ndescription: Has hyphens\n---\nContent",
            encoding="utf-8",
        )

        manager = SkillManager(search_dirs=[tmp_path])
        assert manager.has("my-special-skill")
        skill = manager.require("my-special-skill")
        assert skill.name == "my-special-skill"

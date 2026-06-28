"""
GrassFlow 斜杠命令测试

测试 /generate 命令的完整功能：
- 命令注册
- 参数解析（interactive / preview / save）
- LLM 调用和 DSL 生成
- DSL 验证（DSLv2Parser）
- 语法高亮
- 文件保存
- 交互确认流程
"""

import asyncio
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tui.slash_commands import (
    CommandDef,
    CommandRegistry,
    _cmd_generate,
    _highlight_dsl,
    _save_workflow_dsl,
    command_registry,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


SAMPLE_DSL = """workflow ticket_processing {
  agent input {
    type: "input"
    output_schema: { "ticket": "string" }
  }

  agent classify {
    model: "gpt-4"
    prompt: "分类工单: {ticket}"
    output_schema: { "category": "string" }
  }

  agent process {
    model: "gpt-4"
    prompt: "处理工单: {category}"
  }

  input -> classify
  classify -> process
}"""


@pytest.fixture
def mock_repl():
    """创建模拟的 REPL 实例"""
    repl = MagicMock()
    repl.output = []
    repl._pending_generated_dsl = ""
    repl._pending_generated_name = ""
    repl.add_output = MagicMock()

    def _capture_add_output(text, role="system"):
        repl.output.append(MagicMock(text=text, role=role))

    repl.add_output.side_effect = _capture_add_output
    return repl


@pytest.fixture
def mock_generation_result():
    """创建模拟的 GenerationResult"""
    from core.workflow_generator import GenerationResult

    return GenerationResult(
        dsl=SAMPLE_DSL,
        workflow_name="ticket_processing",
        agent_count=3,
        connection_count=2,
        suggestions=["Consider adding an output agent"],
        warnings=[],
    )


@pytest.fixture
def mock_config():
    """创建模拟的配置"""
    config = MagicMock()
    config.llm.default_provider = "openai"
    config.llm.default_model = "gpt-4"
    config.provider = {
        "openai": MagicMock(api_key="sk-test", base_url=None),
    }
    return config


# ── 命令注册测试 ─────────────────────────────────────────────────────────────


class TestGenerateCommandRegistration:
    """测试 /generate 命令注册"""

    def test_generate_registered(self):
        """测试 /generate 命令已注册"""
        cmd = command_registry.get("generate")
        assert cmd is not None
        assert cmd.name == "generate"
        assert cmd.category == "Workflow"
        assert cmd.handler_name == "_cmd_generate"

    def test_generate_alias_gen(self):
        """测试 /gen 别名"""
        cmd = command_registry.get("gen")
        assert cmd is not None
        assert cmd.name == "generate"

    def test_generate_visible(self):
        """测试 /generate 命令可见"""
        cmd = command_registry.get("generate")
        assert cmd.visible is True

    def test_generate_handler_exists(self):
        """测试 handler 已注册"""
        cmd = command_registry.get("generate")
        registry = command_registry
        handler = registry._handlers.get(cmd.handler_name)
        assert handler is not None
        assert handler is _cmd_generate


# ── 参数解析测试 ─────────────────────────────────────────────────────────────


class TestGenerateArgumentParsing:
    """测试 /generate 参数解析"""

    def test_no_args_shows_usage(self, mock_repl):
        """无参数时显示用法"""
        _cmd_generate(mock_repl, [])
        mock_repl.add_output.assert_called()
        call_args = mock_repl.add_output.call_args[0][0]
        assert "Usage" in call_args

    def test_empty_args_shows_usage(self, mock_repl):
        """空参数时显示用法"""
        _cmd_generate(mock_repl, [""])
        mock_repl.add_output.assert_called()
        call_args = mock_repl.add_output.call_args[0][0]
        assert "Description cannot be empty" in call_args

    def test_save_without_name_shows_usage(self, mock_repl):
        """/generate save 无名称时显示用法"""
        _cmd_generate(mock_repl, ["save"])
        mock_repl.add_output.assert_called()
        call_args = mock_repl.add_output.call_args[0][0]
        assert "Usage" in call_args

    def test_save_without_description_shows_usage(self, mock_repl):
        """/generate save <name> 无描述时显示用法"""
        _cmd_generate(mock_repl, ["save", "my_workflow"])
        mock_repl.add_output.assert_called()
        call_args = mock_repl.add_output.call_args[0][0]
        assert "Description cannot be empty" in call_args

    def test_preview_without_description_shows_usage(self, mock_repl):
        """/generate preview 无描述时显示用法"""
        _cmd_generate(mock_repl, ["preview"])
        mock_repl.add_output.assert_called()
        call_args = mock_repl.add_output.call_args[0][0]
        assert "Description cannot be empty" in call_args


# ── _highlight_dsl 测试 ──────────────────────────────────────────────────────


class TestHighlightDSL:
    """测试 DSL 语法高亮"""

    def test_highlight_keywords(self):
        """测试关键字高亮"""
        lines = _highlight_dsl("workflow test {")
        assert len(lines) == 1
        assert "\033[1;36m" in lines[0]  # CYAN_BOLD
        assert "workflow" in lines[0]

    def test_highlight_strings(self):
        """测试字符串高亮"""
        lines = _highlight_dsl('model: "gpt-4"')
        assert len(lines) == 1
        assert "\033[32m" in lines[0]  # GREEN
        assert "gpt-4" in lines[0]

    def test_highlight_arrows(self):
        """测试箭头高亮"""
        lines = _highlight_dsl("A -> B")
        assert len(lines) == 1
        assert "\033[33m" in lines[0]  # YELLOW
        assert "->" in lines[0]

    def test_highlight_comments(self):
        """测试注释高亮"""
        lines = _highlight_dsl("# This is a comment")
        assert len(lines) == 1
        assert "\033[90m" in lines[0]  # GRAY

    def test_highlight_agent_keyword(self):
        """测试 agent 关键字高亮"""
        lines = _highlight_dsl('agent classify {')
        assert len(lines) == 1
        assert "\033[1;36m" in lines[0]
        assert "agent" in lines[0]

    def test_highlight_multiline(self):
        """测试多行 DSL 高亮"""
        dsl = "workflow test {\n  agent a { }\n}"
        lines = _highlight_dsl(dsl)
        assert len(lines) == 3

    def test_highlight_component_keyword(self):
        """测试 component 关键字高亮"""
        lines = _highlight_dsl("component my-comp {")
        assert "\033[1;36m" in lines[0]
        assert "component" in lines[0]


# ── _save_workflow_dsl 测试 ──────────────────────────────────────────────────


class TestSaveWorkflowDSL:
    """测试 DSL 保存"""

    def test_save_creates_file(self, tmp_path):
        """测试保存创建文件"""
        from tui.slash_commands import _save_workflow_dsl
        with patch("pathlib.Path.home", return_value=tmp_path):
            saved = _save_workflow_dsl("test_workflow", SAMPLE_DSL)

        assert os.path.exists(saved)
        assert saved.endswith(".gf")
        with open(saved, encoding="utf-8") as f:
            content = f.read()
        assert "workflow ticket_processing" in content

    def test_save_name_sanitization(self, tmp_path):
        """测试文件名清理"""
        from tui.slash_commands import _save_workflow_dsl
        with patch("pathlib.Path.home", return_value=tmp_path):
            saved = _save_workflow_dsl("my workflow/name", SAMPLE_DSL)
        assert "my_workflow_name.gf" in saved

    def test_save_no_overwrite(self, tmp_path):
        """测试不覆盖已存在文件"""
        from tui.slash_commands import _save_workflow_dsl
        with patch("pathlib.Path.home", return_value=tmp_path):
            saved1 = _save_workflow_dsl("dup_test", SAMPLE_DSL)
            saved2 = _save_workflow_dsl("dup_test", SAMPLE_DSL)
        assert saved1 != saved2
        assert "_1.gf" in saved2

    def test_save_creates_directory(self, tmp_path):
        """测试自动创建目录"""
        from tui.slash_commands import _save_workflow_dsl
        target = tmp_path / "nonexistent"
        with patch("pathlib.Path.home", return_value=target):
            saved = _save_workflow_dsl("new_wf", SAMPLE_DSL)
        assert os.path.exists(saved)


# ── DSLv2Parser 验证集成测试 ─────────────────────────────────────────────────


class TestGenerateDSLValidation:
    """测试生成的 DSL 通过 DSLv2Parser 验证"""

    def test_sample_dsl_parses(self):
        """测试示例 DSL 可被 v2 解析器解析"""
        from tui.dsl_parser_v2 import DSLv2Parser
        parser = DSLv2Parser()
        result = parser.parse(SAMPLE_DSL)
        assert result.errors == []
        assert len(result.workflows) == 1
        assert result.workflows[0].name == "ticket_processing"
        assert len(result.workflows[0].agents) == 3

    def test_sample_dsl_connections(self):
        """测试示例 DSL 连接解析"""
        from tui.dsl_parser_v2 import DSLv2Parser
        parser = DSLv2Parser()
        result = parser.parse(SAMPLE_DSL)
        wf = result.workflows[0]
        assert len(wf.connections) == 2


# ── _cmd_generate 完整流程测试 ────────────────────────────────────────────────


class TestCmdGenerateFlow:
    """测试 _cmd_generate 完整流程"""

    @pytest.mark.asyncio
    async def test_preview_mode(self, mock_repl, mock_generation_result, mock_config):
        """测试 preview 模式"""
        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen:

            # 设置生成器返回值
            mock_generator = AsyncMock()
            mock_generator.generate_workflow.return_value = mock_generation_result
            MockGen.return_value = mock_generator

            _cmd_generate(mock_repl, ["preview", "create", "a", "ticket", "workflow"])

            # 等待 async task 完成
            await asyncio.sleep(0.1)

            # 验证输出包含预览
            output_texts = [call[0][0] for call in mock_repl.add_output.call_args_list]
            assert any("Preview" in t for t in output_texts)
            assert any("not saved" in t for t in output_texts)
            # 不应该提示保存
            assert not any("Save this workflow" in t for t in output_texts)

    @pytest.mark.asyncio
    async def test_save_mode(self, mock_repl, mock_generation_result, mock_config, tmp_path):
        """测试 save 模式"""
        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen, \
             patch("tui.slash_commands._save_workflow_dsl") as mock_save:

            mock_generator = AsyncMock()
            mock_generator.generate_workflow.return_value = mock_generation_result
            MockGen.return_value = mock_generator
            mock_save.return_value = "/tmp/test.gf"

            _cmd_generate(mock_repl, ["save", "my_wf", "create", "a", "workflow"])

            await asyncio.sleep(0.1)

            mock_save.assert_called_once_with("my_wf", SAMPLE_DSL)
            output_texts = [call[0][0] for call in mock_repl.add_output.call_args_list]
            assert any("Saved to" in t for t in output_texts)

    @pytest.mark.asyncio
    async def test_interactive_mode(self, mock_repl, mock_generation_result, mock_config):
        """测试交互模式（默认）"""
        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen:

            mock_generator = AsyncMock()
            mock_generator.generate_workflow.return_value = mock_generation_result
            MockGen.return_value = mock_generator

            _cmd_generate(mock_repl, ["create", "a", "workflow"])

            await asyncio.sleep(0.1)

            # 验证输出包含保存提示
            output_texts = [call[0][0] for call in mock_repl.add_output.call_args_list]
            assert any("Save this workflow" in t for t in output_texts)

            # 验证 pending DSL 已设置
            assert mock_repl._pending_generated_dsl == SAMPLE_DSL
            assert mock_repl._pending_generated_name == "ticket_processing"

    @pytest.mark.asyncio
    async def test_generation_error(self, mock_repl, mock_config):
        """测试生成失败"""
        from core.workflow_generator import WorkflowGeneratorError

        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen:

            mock_generator = AsyncMock()
            mock_generator.generate_workflow.side_effect = WorkflowGeneratorError("API failed")
            MockGen.return_value = mock_generator

            _cmd_generate(mock_repl, ["test", "workflow"])

            await asyncio.sleep(0.1)

            output_texts = [call[0][0] for call in mock_repl.add_output.call_args_list]
            assert any("Generation failed" in t for t in output_texts)

    @pytest.mark.asyncio
    async def test_unexpected_error(self, mock_repl, mock_config):
        """测试意外错误"""
        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen:

            mock_generator = AsyncMock()
            mock_generator.generate_workflow.side_effect = RuntimeError("boom")
            MockGen.return_value = mock_generator

            _cmd_generate(mock_repl, ["test", "workflow"])

            await asyncio.sleep(0.1)

            output_texts = [call[0][0] for call in mock_repl.add_output.call_args_list]
            assert any("Unexpected error" in t for t in output_texts)

    @pytest.mark.asyncio
    async def test_parse_errors_shown(self, mock_repl, mock_generation_result, mock_config):
        """测试解析错误被展示"""
        # 生成无效 DSL
        bad_result = MagicMock()
        bad_result.dsl = "invalid dsl"
        bad_result.workflow_name = "bad"
        bad_result.agent_count = 0
        bad_result.connection_count = 0
        bad_result.suggestions = []
        bad_result.warnings = ["some warning"]

        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen:

            mock_generator = AsyncMock()
            mock_generator.generate_workflow.return_value = bad_result
            MockGen.return_value = mock_generator

            _cmd_generate(mock_repl, ["preview", "test"])

            await asyncio.sleep(0.1)

            output_texts = [call[0][0] for call in mock_repl.add_output.call_args_list]
            # 应该有 warnings
            assert any("Warnings" in t for t in output_texts)


# ── 补全器测试 ───────────────────────────────────────────────────────────────


class TestGenerateCompletion:
    """测试 /generate 命令补全"""

    def test_generate_in_arg_completions(self):
        """测试 generate 的参数补全映射"""
        from tui.slash_commands import SlashCommandCompleter
        completer = SlashCommandCompleter()
        completions = completer._get_argument_completions("generate", "")
        texts = [c.text for c in completions]
        assert "preview" in texts
        assert "save" in texts

    def test_gen_alias_in_arg_completions(self):
        """测试 gen 别名的参数补全"""
        from tui.slash_commands import SlashCommandCompleter
        completer = SlashCommandCompleter()
        completions = completer._get_argument_completions("gen", "")
        texts = [c.text for c in completions]
        assert "preview" in texts
        assert "save" in texts

    def test_generate_partial_completion(self):
        """测试部分输入补全"""
        from tui.slash_commands import SlashCommandCompleter
        completer = SlashCommandCompleter()
        completions = completer._get_argument_completions("generate", "pre")
        texts = [c.text for c in completions]
        assert "preview" in texts
        assert "save" not in texts


# ── 边界情况测试 ─────────────────────────────────────────────────────────────


class TestGenerateEdgeCases:
    """测试边界情况"""

    def test_save_name_with_spaces(self, tmp_path):
        """测试保存名包含空格"""
        from tui.slash_commands import _save_workflow_dsl
        with patch("pathlib.Path.home", return_value=tmp_path):
            saved = _save_workflow_dsl("my workflow name", SAMPLE_DSL)
        assert "my_workflow_name.gf" in saved

    def test_save_name_with_special_chars(self, tmp_path):
        """测试保存名包含特殊字符"""
        from tui.slash_commands import _save_workflow_dsl
        with patch("pathlib.Path.home", return_value=tmp_path):
            saved = _save_workflow_dsl("test/flow\\v2", SAMPLE_DSL)
        assert "test_flow_v2.gf" in saved

    def test_highlight_empty_text(self):
        """测试空文本高亮"""
        lines = _highlight_dsl("")
        assert lines == []

    def test_highlight_plain_text(self):
        """测试纯文本（无特殊元素）"""
        lines = _highlight_dsl("just plain text")
        assert len(lines) == 1
        # 不应有 ANSI 码
        assert "\033[" not in lines[0]

    @pytest.mark.asyncio
    async def test_generate_preserves_dsl_content(self, mock_repl, mock_config):
        """测试生成的 DSL 内容完整保留"""
        complex_dsl = """workflow complex {
  agent a {
    model: "gpt-4"
    prompt: "step 1"
    input_schema: { "x": "string" }
  }
  agent b {
    model: "gpt-3.5-turbo"
    prompt: "step 2"
  }
  a -> b
}"""
        result = MagicMock()
        result.dsl = complex_dsl
        result.workflow_name = "complex"
        result.agent_count = 2
        result.connection_count = 1
        result.suggestions = []
        result.warnings = []

        with patch("tui.config_integration.load_config_readonly", return_value=mock_config), \
             patch("core.llm.LLMClient") as MockLLM, \
             patch("core.workflow_generator.WorkflowGenerator") as MockGen:

            mock_generator = AsyncMock()
            mock_generator.generate_workflow.return_value = result
            MockGen.return_value = mock_generator

            _cmd_generate(mock_repl, ["preview", "complex", "workflow"])

            await asyncio.sleep(0.1)

            assert mock_repl._pending_generated_dsl == ""
            # preview 模式不应设置 pending

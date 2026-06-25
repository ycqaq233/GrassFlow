"""
GrassFlow AI 工作流生成器测试

测试覆盖：
- WorkflowGenerator 类
- DSL 语法验证
- 工作流生成
- 边界情况和错误处理
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.workflow_generator import (
    GenerationResult,
    ValidationResult,
    WorkflowComplexity,
    WorkflowGenerator,
    WorkflowGeneratorError,
    WorkflowSuggestion,
    generate_workflow_from_description,
    validate_workflow_dsl,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_client():
    """创建模拟的 LLM 客户端"""
    client = AsyncMock()
    client.chat = AsyncMock()
    return client


@pytest.fixture
def sample_dsl():
    """示例 DSL 代码"""
    return """workflow ticket_processing {
  agent input {
    type: "input"
    output_schema: { "ticket": "string" }
  }

  agent classify {
    model: "gpt-4"
    prompt: "分类工单: {ticket}"
    output_schema: { "category": "string", "priority": "string" }
  }

  agent route {
    type: "condition"
    rules: ["urgent", "normal", "info"]
  }

  agent human {
    type: "manual"
    prompt: "请审批此工单"
  }

  agent bot {
    model: "gpt-4"
    prompt: "自动回复工单: {ticket}"
    output_schema: { "response": "string" }
  }

  agent output {
    type: "output"
    input_schema: { "response": "string" }
  }

  input -> classify
  classify -> route
  route -> [urgent] human, [normal] bot, [info] bot
  human -> output
  bot -> output
}"""


@pytest.fixture
def sample_simple_dsl():
    """简单 DSL 代码"""
    return """
workflow simple_workflow {
  agent input {
    type: "input"
  }

  agent process {
    model: "gpt-4"
    prompt: "处理输入"
  }

  agent output {
    type: "output"
  }

  input -> process
  process -> output
}
"""


@pytest.fixture
def generator(mock_llm_client):
    """创建 WorkflowGenerator 实例"""
    return WorkflowGenerator(llm_client=mock_llm_client)


# ── WorkflowGenerator 测试 ────────────────────────────────────────────────────


class TestWorkflowGenerator:
    """测试 WorkflowGenerator 类"""

    def test_init_with_client(self, mock_llm_client):
        """测试使用客户端初始化"""
        generator = WorkflowGenerator(llm_client=mock_llm_client)
        assert generator.llm_client == mock_llm_client

    def test_init_without_client(self):
        """测试不使用客户端初始化"""
        generator = WorkflowGenerator()
        with pytest.raises(WorkflowGeneratorError, match="LLM client not initialized"):
            _ = generator.llm_client

    def test_set_llm_client(self, mock_llm_client):
        """测试设置 LLM 客户端"""
        generator = WorkflowGenerator()
        generator.llm_client = mock_llm_client
        assert generator.llm_client == mock_llm_client

    def test_get_syntax_reference(self, generator):
        """测试获取语法参考"""
        reference = generator.get_syntax_reference()
        assert "workflow" in reference
        assert "agent" in reference
        assert "->" in reference


# ── DSL 验证测试 ──────────────────────────────────────────────────────────────


class TestDSLValidation:
    """测试 DSL 语法验证"""

    def test_valid_dsl(self, generator, sample_dsl):
        """测试有效 DSL"""
        result = generator.validate_dsl(sample_dsl)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_empty_dsl(self, generator):
        """测试空 DSL"""
        result = generator.validate_dsl("")
        assert result.is_valid is False
        assert "empty" in result.errors[0].lower()

    def test_missing_workflow_declaration(self, generator):
        """测试缺少 workflow 声明"""
        dsl = """
        agent test {
          model: "gpt-4"
        }
        test -> test
        """
        result = generator.validate_dsl(dsl)
        assert result.is_valid is False
        assert any("workflow" in error.lower() for error in result.errors)

    def test_missing_agent_declaration(self, generator):
        """测试缺少 agent 声明"""
        dsl = """
        workflow test {
          input -> output
        }
        """
        result = generator.validate_dsl(dsl)
        assert result.is_valid is False
        assert any("agent" in error.lower() for error in result.errors)

    def test_mismatched_braces(self, generator):
        """测试大括号不匹配"""
        dsl = """
        workflow test {
          agent input {
            model: "gpt-4"
        """
        result = generator.validate_dsl(dsl)
        assert result.is_valid is False
        assert any("brace" in error.lower() for error in result.errors)

    def test_no_execution_flow(self, generator):
        """测试没有执行流"""
        dsl = """
        workflow test {
          agent input {
            model: "gpt-4"
          }
        }
        """
        result = generator.validate_dsl(dsl)
        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert any("flow" in warning.lower() for warning in result.warnings)

    def test_validation_with_sample_dsl(self, generator, sample_dsl):
        """测试使用示例 DSL 验证"""
        result = generator.validate_dsl(sample_dsl)
        assert result.is_valid is True
        # 应该有一些建议
        assert len(result.suggestions) >= 0


# ── 工作流生成测试 ────────────────────────────────────────────────────────────


class TestWorkflowGeneration:
    """测试工作流生成"""

    @pytest.mark.asyncio
    async def test_generate_workflow_success(self, generator, mock_llm_client, sample_dsl):
        """测试成功生成工作流"""
        # 模拟 LLM 响应
        mock_response = MagicMock()
        mock_response.content = f"```grassflow\n{sample_dsl}\n```"
        mock_llm_client.chat.return_value = mock_response

        result = await generator.generate_workflow("创建一个工单处理工作流")

        assert isinstance(result, GenerationResult)
        assert result.dsl == sample_dsl
        assert result.workflow_name == "ticket_processing"
        assert result.agent_count == 6
        assert result.edge_count > 0
        mock_llm_client.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_workflow_empty_description(self, generator):
        """测试空描述"""
        with pytest.raises(WorkflowGeneratorError, match="empty"):
            await generator.generate_workflow("")

    @pytest.mark.asyncio
    async def test_generate_workflow_llm_error(self, generator, mock_llm_client):
        """测试 LLM 调用失败"""
        from core.llm import LLMError
        mock_llm_client.chat.side_effect = LLMError("API Error")

        with pytest.raises(WorkflowGeneratorError, match="LLM call failed"):
            await generator.generate_workflow("测试工作流")

    @pytest.mark.asyncio
    async def test_generate_workflow_with_custom_name(self, generator, mock_llm_client, sample_dsl):
        """测试使用自定义名称生成工作流"""
        mock_response = MagicMock()
        mock_response.content = sample_dsl
        mock_llm_client.chat.return_value = mock_response

        result = await generator.generate_workflow(
            "创建一个工单处理工作流",
            workflow_name="custom_workflow"
        )

        assert result.workflow_name == "custom_workflow"

    @pytest.mark.asyncio
    async def test_generate_workflow_temperature(self, generator, mock_llm_client, sample_dsl):
        """测试温度参数"""
        mock_response = MagicMock()
        mock_response.content = sample_dsl
        mock_llm_client.chat.return_value = mock_response

        await generator.generate_workflow("测试", temperature=0.5)

        # 验证调用参数
        call_args = mock_llm_client.chat.call_args
        assert call_args.kwargs.get("temperature") == 0.5


# ── DSL 提取测试 ──────────────────────────────────────────────────────────────


class TestDSLExtraction:
    """测试 DSL 提取"""

    def test_extract_from_code_block(self, generator, sample_dsl):
        """测试从代码块中提取"""
        content = f"```grassflow\n{sample_dsl}\n```"
        extracted = generator._extract_dsl(content)
        assert extracted == sample_dsl

    def test_extract_from_plain_text(self, generator, sample_dsl):
        """测试从纯文本中提取"""
        extracted = generator._extract_dsl(sample_dsl)
        assert extracted == sample_dsl

    def test_extract_workflow_name(self, generator, sample_dsl):
        """测试提取工作流名称"""
        name = generator._extract_workflow_name(sample_dsl)
        assert name == "ticket_processing"

    def test_extract_workflow_name_missing(self, generator):
        """测试提取缺失的工作流名称"""
        name = generator._extract_workflow_name("no workflow here")
        assert name == "unnamed_workflow"

    def test_count_agents(self, generator, sample_dsl):
        """测试统计 Agent 数量"""
        count = generator._count_agents(sample_dsl)
        assert count == 6

    def test_count_edges(self, generator, sample_dsl):
        """测试统计边数量"""
        count = generator._count_edges(sample_dsl)
        assert count > 0


# ── 建议生成测试 ──────────────────────────────────────────────────────────────


class TestSuggestionGeneration:
    """测试建议生成"""

    def test_suggest_workflow_structure_simple(self, generator):
        """测试简单工作流建议"""
        suggestion = generator.suggest_workflow_structure("创建一个简单的工作流")
        assert isinstance(suggestion, WorkflowSuggestion)
        assert suggestion.complexity == WorkflowComplexity.SIMPLE

    def test_suggest_workflow_structure_complex(self, generator):
        """测试复杂工作流建议"""
        suggestion = generator.suggest_workflow_structure("创建一个复杂的工作流")
        assert suggestion.complexity == WorkflowComplexity.COMPLEX

    def test_suggest_workflow_structure_with_keywords(self, generator):
        """测试带关键词的工作流建议"""
        suggestion = generator.suggest_workflow_structure(
            "创建一个包含输入、分类和输出的工作流"
        )
        assert "input" in suggestion.agents
        assert "classify" in suggestion.agents
        assert "output" in suggestion.agents

    def test_suggest_workflow_structure_with_interactions(self, generator):
        """测试带交互类型的工作流建议"""
        suggestion = generator.suggest_workflow_structure(
            "创建一个并行处理的工作流"
        )
        assert "parallel" in suggestion.interactions

    def test_generate_suggestions(self, generator, sample_dsl):
        """测试生成改进建议"""
        suggestions = generator._generate_suggestions(sample_dsl, "测试描述")
        assert isinstance(suggestions, list)


# ── 便捷函数测试 ──────────────────────────────────────────────────────────────


class TestConvenienceFunctions:
    """测试便捷函数"""

    @pytest.mark.asyncio
    async def test_generate_workflow_from_description(self, mock_llm_client, sample_dsl):
        """测试便捷函数生成工作流"""
        mock_response = MagicMock()
        mock_response.content = sample_dsl
        mock_llm_client.chat.return_value = mock_response

        result = await generate_workflow_from_description(
            "测试工作流",
            llm_client=mock_llm_client
        )

        assert isinstance(result, GenerationResult)

    def test_validate_workflow_dsl(self, sample_dsl):
        """测试便捷函数验证 DSL"""
        result = validate_workflow_dsl(sample_dsl)
        assert isinstance(result, ValidationResult)
        assert result.is_valid is True

    def test_validate_workflow_dsl_invalid(self):
        """测试便捷函数验证无效 DSL"""
        result = validate_workflow_dsl("")
        assert result.is_valid is False


# ── 数据模型测试 ──────────────────────────────────────────────────────────────


class TestDataModels:
    """测试数据模型"""

    def test_generation_result(self):
        """测试 GenerationResult"""
        result = GenerationResult(
            dsl="workflow test {}",
            workflow_name="test",
            agent_count=1,
            edge_count=0,
        )
        assert result.dsl == "workflow test {}"
        assert result.workflow_name == "test"
        assert result.agent_count == 1
        assert result.edge_count == 0
        assert result.suggestions == []
        assert result.warnings == []

    def test_validation_result(self):
        """测试 ValidationResult"""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        assert result.suggestions == []

    def test_workflow_suggestion(self):
        """测试 WorkflowSuggestion"""
        suggestion = WorkflowSuggestion(
            name="test",
            description="测试",
            agents=["input", "output"],
            interactions=["sequence"],
            complexity=WorkflowComplexity.SIMPLE,
        )
        assert suggestion.name == "test"
        assert len(suggestion.agents) == 2
        assert suggestion.complexity == WorkflowComplexity.SIMPLE


# ── 边界情况测试 ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    """测试边界情况"""

    def test_validation_with_whitespace(self, generator):
        """测试带空白的 DSL"""
        dsl = """
        workflow test   {
          agent input   {
            model: "gpt-4"
          }
          input -> input
        }
        """
        result = generator.validate_dsl(dsl)
        assert result.is_valid is True

    def test_validation_with_comments(self, generator):
        """测试带注释的 DSL"""
        dsl = """
        # 这是注释
        workflow test {
          agent input {
            # Agent 注释
            model: "gpt-4"
          }
          input -> input
        }
        """
        result = generator.validate_dsl(dsl)
        assert result.is_valid is True

    def test_extract_dsl_with_multiple_code_blocks(self, generator):
        """测试多个代码块"""
        content = """
        这是第一个代码块：
        ```python
        print("hello")
        ```

        这是 DSL 代码块：
        ```grassflow
        workflow test {
          agent input {
            model: "gpt-4"
          }
        }
        ```
        """
        extracted = generator._extract_dsl(content)
        assert "workflow test" in extracted

    def test_count_agents_with_nested_braces(self, generator):
        """测试嵌套大括号"""
        dsl = """
        workflow test {
          agent input {
            model: "gpt-4"
            input_schema: { "key": "value" }
          }
        }
        """
        count = generator._count_agents(dsl)
        assert count == 1


# ── 集成测试 ──────────────────────────────────────────────────────────────────


class TestIntegration:
    """端到端集成测试"""

    @pytest.mark.asyncio
    async def test_full_workflow_generation(self, generator, mock_llm_client, sample_dsl):
        """完整的生成流程"""
        # 模拟 LLM 响应
        mock_response = MagicMock()
        mock_response.content = f"```grassflow\n{sample_dsl}\n```"
        mock_llm_client.chat.return_value = mock_response

        # 生成工作流
        result = await generator.generate_workflow(
            "创建一个工单处理工作流，包含分类、路由和自动回复功能"
        )

        # 验证结果
        assert isinstance(result, GenerationResult)
        assert result.dsl == sample_dsl
        assert result.workflow_name == "ticket_processing"
        assert result.agent_count == 6

        # 验证 DSL
        validation = generator.validate_dsl(result.dsl)
        assert validation.is_valid is True

    @pytest.mark.asyncio
    async def test_generate_and_validate(self, generator, mock_llm_client):
        """生成并验证工作流"""
        # 简单的 DSL
        simple_dsl = """
workflow test {
  agent input {
    type: "input"
  }
  agent output {
    type: "output"
  }
  input -> output
}
"""
        mock_response = MagicMock()
        mock_response.content = simple_dsl
        mock_llm_client.chat.return_value = mock_response

        # 生成
        result = await generator.generate_workflow("简单工作流")

        # 验证
        validation = generator.validate_dsl(result.dsl)
        assert validation.is_valid is True

    def test_suggest_and_generate(self, generator):
        """建议和生成流程"""
        # 获取建议
        suggestion = generator.suggest_workflow_structure(
            "创建一个包含输入、分类和输出的工作流"
        )

        # 验证建议
        assert "input" in suggestion.agents
        assert "output" in suggestion.agents
        assert suggestion.complexity in [
            WorkflowComplexity.SIMPLE,
            WorkflowComplexity.MEDIUM,
            WorkflowComplexity.COMPLEX,
        ]

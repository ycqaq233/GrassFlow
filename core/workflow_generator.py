"""
GrassFlow AI 工作流生成器

使用 LLM 根据用户描述生成 GrassFlow DSL 代码。

功能：
- 自然语言到 DSL 的转换
- DSL 语法验证
- 工作流模板生成
- 智能提示和建议

使用示例：
    generator = WorkflowGenerator(llm_client)
    dsl = await generator.generate_workflow("创建一个工单处理工作流")
    print(dsl)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)


# ── 常量 ──────────────────────────────────────────────────────────────────────

# GrassFlow DSL 语法参考
DSL_SYNTAX_REFERENCE = """
## GrassFlow DSL 语法参考

### 基础结构
```
workflow <name> {
  # Agent 声明
  agent <name> {
    type: "llm" | "condition" | "manual" | "input" | "output"
    model: "<model-name>"
    prompt: "<prompt-text>"
    input_schema: { "<field>": "<type>" }
    output_schema: { "<field>": "<type>" }
    on_fail: "stop" | "skip" | "retry"
    retry_count: <number>
  }

  # 执行流
  <source> -> <target>                    # 顺序执行
  (<source1>, <source2>) -> <target>      # 并行执行
  <source> | <target>                     # 立即执行
  <source> -> [<condition>] <target>      # 条件分支
}
```

### Agent 类型
- **llm**: 调用大语言模型（默认）
- **condition**: 条件分支，根据输入决定路由
- **manual**: 人工审批暂停点
- **input**: 工作流输入
- **output**: 工作流输出

### 交互类型
- **顺序执行** (`->`): A 输出作为 B 输入
- **并行执行** (`(A, B) -> C`): 多个 Agent 并行执行，结果聚合到 C
- **立即执行** (`|`): 立即启动，遇到依赖时等待
- **条件分支** (`[condition]`): 根据条件选择目标 Agent

### 示例
```
workflow ticket_processing {
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
}
```
"""

# 系统提示词模板
SYSTEM_PROMPT = """你是一个 GrassFlow 工作流生成专家。你的任务是根据用户的自然语言描述，生成符合 GrassFlow DSL 语法的工作流代码。

## 你的能力
1. 理解用户的工作流需求
2. 设计合理的 Agent 结构和连接关系
3. 生成符合 GrassFlow DSL 语法的代码
4. 提供清晰的工作流说明

## 输出要求
1. 只输出 DSL 代码，不要输出其他内容
2. 确保语法正确
3. 使用有意义的 Agent 名称
4. 添加适当的注释说明

## GrassFlow DSL 语法参考
{syntax_reference}
"""

# 用户提示词模板
USER_PROMPT = """请根据以下描述生成 GrassFlow 工作流 DSL 代码：

## 用户描述
{description}

## 要求
1. 生成完整的工作流定义
2. 包含所有必要的 Agent 声明
3. 定义清晰的执行流
4. 使用合适的 Agent 类型和模型

请直接输出 DSL 代码：
"""


# ── 数据模型 ──────────────────────────────────────────────────────────────────


class WorkflowComplexity(str, Enum):
    """工作流复杂度"""
    SIMPLE = "simple"        # 简单：2-3 个 Agent
    MEDIUM = "medium"        # 中等：4-6 个 Agent
    COMPLEX = "complex"      # 复杂：7+ 个 Agent


@dataclass
class WorkflowSuggestion:
    """工作流建议"""
    name: str
    description: str
    agents: List[str]
    interactions: List[str]
    complexity: WorkflowComplexity


@dataclass
class GenerationResult:
    """生成结果"""
    dsl: str
    workflow_name: str
    agent_count: int
    edge_count: int
    suggestions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


# ── 工作流生成器 ──────────────────────────────────────────────────────────────


class WorkflowGeneratorError(Exception):
    """工作流生成器错误"""
    pass


class WorkflowGenerator:
    """AI 工作流生成器

    使用 LLM 根据用户描述生成 GrassFlow DSL 代码。

    用法：
        generator = WorkflowGenerator(llm_client)
        result = await generator.generate_workflow("创建一个工单处理工作流")
        print(result.dsl)
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        syntax_reference: Optional[str] = None,
    ):
        """初始化工作流生成器

        Args:
            llm_client: LLM 客户端实例
            syntax_reference: DSL 语法参考（可选）
        """
        self._llm_client = llm_client
        self._syntax_reference = syntax_reference or DSL_SYNTAX_REFERENCE
        self._system_prompt = SYSTEM_PROMPT.format(
            syntax_reference=self._syntax_reference
        )

    @property
    def llm_client(self) -> LLMClient:
        """获取 LLM 客户端"""
        if self._llm_client is None:
            raise WorkflowGeneratorError("LLM client not initialized")
        return self._llm_client

    @llm_client.setter
    def llm_client(self, client: LLMClient) -> None:
        """设置 LLM 客户端"""
        self._llm_client = client

    async def generate_workflow(
        self,
        description: str,
        workflow_name: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> GenerationResult:
        """根据描述生成工作流

        Args:
            description: 用户描述
            workflow_name: 工作流名称（可选，默认从描述中提取）
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            GenerationResult 对象

        Raises:
            WorkflowGeneratorError: 生成失败
        """
        if not description or not description.strip():
            raise WorkflowGeneratorError("Description cannot be empty")

        try:
            # 准备提示词
            user_prompt = USER_PROMPT.format(description=description)

            # 调用 LLM
            response = await self.llm_client.chat(
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # 提取 DSL 代码
            dsl = self._extract_dsl(response.content)

            # 验证 DSL
            validation = self.validate_dsl(dsl)

            # 解析工作流信息
            workflow_name = workflow_name or self._extract_workflow_name(dsl)
            agent_count = self._count_agents(dsl)
            edge_count = self._count_edges(dsl)

            # 生成建议
            suggestions = self._generate_suggestions(dsl, description)

            return GenerationResult(
                dsl=dsl,
                workflow_name=workflow_name,
                agent_count=agent_count,
                edge_count=edge_count,
                suggestions=suggestions,
                warnings=validation.warnings,
            )

        except LLMError as e:
            raise WorkflowGeneratorError(f"LLM call failed: {e}")
        except Exception as e:
            raise WorkflowGeneratorError(f"Workflow generation failed: {e}")

    def validate_dsl(self, dsl: str) -> ValidationResult:
        """验证 DSL 语法

        Args:
            dsl: DSL 代码

        Returns:
            ValidationResult 对象
        """
        errors: List[str] = []
        warnings: List[str] = []
        suggestions: List[str] = []

        # 检查基本结构
        if not dsl or not dsl.strip():
            errors.append("DSL code is empty")
            return ValidationResult(is_valid=False, errors=errors)

        # 检查 workflow 声明
        if not re.search(r'workflow\s+\w+\s*\{', dsl):
            errors.append("Missing workflow declaration")

        # 检查 agent 声明
        agent_matches = re.findall(r'agent\s+(\w+)\s*\{', dsl)
        if not agent_matches:
            errors.append("No agent declarations found")

        # 检查大括号匹配
        open_braces = dsl.count('{')
        close_braces = dsl.count('}')
        if open_braces != close_braces:
            errors.append(f"Mismatched braces: {open_braces} opening vs {close_braces} closing")

        # 检查执行流
        if '->' not in dsl and '|' not in dsl:
            warnings.append("No execution flow defined")

        # 检查 Agent 类型
        for agent_name in agent_matches:
            agent_pattern = rf'agent\s+{agent_name}\s*\{{([^}}]+)\}}'
            agent_match = re.search(agent_pattern, dsl, re.DOTALL)
            if agent_match:
                agent_body = agent_match.group(1)
                if 'type:' not in agent_body:
                    suggestions.append(f"Consider specifying type for agent '{agent_name}'")

        # 检查模型配置
        llm_agents = re.findall(r'agent\s+(\w+)\s*\{[^}]*type:\s*"llm"[^}]*\}', dsl, re.DOTALL)
        for agent_name in llm_agents:
            agent_pattern = rf'agent\s+{agent_name}\s*\{{([^}}]+)\}}'
            agent_match = re.search(agent_pattern, dsl, re.DOTALL)
            if agent_match:
                agent_body = agent_match.group(1)
                if 'model:' not in agent_body:
                    suggestions.append(f"Consider specifying model for LLM agent '{agent_name}'")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )

    def _extract_dsl(self, content: str) -> str:
        """从 LLM 响应中提取 DSL 代码

        Args:
            content: LLM 响应内容

        Returns:
            提取的 DSL 代码
        """
        # 尝试提取代码块
        code_block_match = re.search(r'```(?:grassflow|dsl)?\s*\n(.*?)\n```', content, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1).strip()

        # 尝试提取 workflow 块
        workflow_match = re.search(r'(workflow\s+\w+\s*\{.*\})', content, re.DOTALL)
        if workflow_match:
            return workflow_match.group(1).strip()

        # 返回整个内容（去除前后空白）
        return content.strip()

    def _extract_workflow_name(self, dsl: str) -> str:
        """从 DSL 中提取工作流名称

        Args:
            dsl: DSL 代码

        Returns:
            工作流名称
        """
        match = re.search(r'workflow\s+(\w+)\s*\{', dsl)
        if match:
            return match.group(1)
        return "unnamed_workflow"

    def _count_agents(self, dsl: str) -> int:
        """统计 Agent 数量

        Args:
            dsl: DSL 代码

        Returns:
            Agent 数量
        """
        return len(re.findall(r'agent\s+\w+\s*\{', dsl))

    def _count_edges(self, dsl: str) -> int:
        """统计边数量

        Args:
            dsl: DSL 代码

        Returns:
            边数量
        """
        # 移除 agent 声明块
        dsl_without_agents = re.sub(r'agent\s+\w+\s*\{[^}]*\}', '', dsl, flags=re.DOTALL)
        # 统计 -> 和 |
        edges = re.findall(r'->|\|', dsl_without_agents)
        return len(edges)

    def _generate_suggestions(self, dsl: str, description: str) -> List[str]:
        """生成改进建议

        Args:
            dsl: DSL 代码
            description: 用户描述

        Returns:
            建议列表
        """
        suggestions = []

        # 检查是否有输入/输出 Agent
        has_input = bool(re.search(r'type:\s*"input"', dsl))
        has_output = bool(re.search(r'type:\s*"output"', dsl))

        if not has_input:
            suggestions.append("Consider adding an input agent for workflow input")
        if not has_output:
            suggestions.append("Consider adding an output agent for workflow output")

        # 检查是否有条件分支
        if '[' in dsl and ']' in dsl:
            # 检查是否有 condition agent
            if not re.search(r'type:\s*"condition"', dsl):
                suggestions.append("Consider adding a condition agent for branching logic")

        # 检查是否有手动审批
        if 'manual' in description.lower() or '审批' in description or '人工' in description:
            if not re.search(r'type:\s*"manual"', dsl):
                suggestions.append("Consider adding a manual agent for human approval")

        return suggestions

    def get_syntax_reference(self) -> str:
        """获取 DSL 语法参考

        Returns:
            DSL 语法参考文本
        """
        return self._syntax_reference

    def suggest_workflow_structure(self, description: str) -> WorkflowSuggestion:
        """根据描述建议工作流结构

        Args:
            description: 用户描述

        Returns:
            WorkflowSuggestion 对象
        """
        # 分析描述中的关键词
        description_lower = description.lower()

        # 识别复杂度
        if any(word in description_lower for word in ['简单', 'basic', 'simple', '基础']):
            complexity = WorkflowComplexity.SIMPLE
        elif any(word in description_lower for word in ['复杂', 'complex', 'advanced', '高级']):
            complexity = WorkflowComplexity.COMPLEX
        else:
            complexity = WorkflowComplexity.MEDIUM

        # 识别 Agent 类型
        agents = []
        if any(word in description_lower for word in ['输入', 'input', '接收']):
            agents.append("input")
        if any(word in description_lower for word in ['分类', 'classify', 'classify', '判断']):
            agents.append("classify")
        if any(word in description_lower for word in ['条件', 'condition', '路由', 'route']):
            agents.append("condition")
        if any(word in description_lower for word in ['人工', 'manual', '审批', 'approve']):
            agents.append("manual")
        if any(word in description_lower for word in ['处理', 'process', '生成', 'generate']):
            agents.append("process")
        if any(word in description_lower for word in ['输出', 'output', '结果']):
            agents.append("output")

        # 如果没有识别到，添加默认 Agent
        if not agents:
            agents = ["input", "process", "output"]

        # 识别交互类型
        interactions = []
        if any(word in description_lower for word in ['并行', 'parallel', '同时']):
            interactions.append("parallel")
        if any(word in description_lower for word in ['条件', 'condition', '分支']):
            interactions.append("condition")
        if any(word in description_lower for word in ['立即', 'immediate', '快速']):
            interactions.append("immediate")

        return WorkflowSuggestion(
            name="suggested_workflow",
            description=description,
            agents=agents,
            interactions=interactions,
            complexity=complexity,
        )


# ── 便捷函数 ──────────────────────────────────────────────────────────────────


async def generate_workflow_from_description(
    description: str,
    llm_client: Optional[LLMClient] = None,
    workflow_name: Optional[str] = None,
) -> GenerationResult:
    """根据描述生成工作流的便捷函数

    Args:
        description: 用户描述
        llm_client: LLM 客户端（可选）
        workflow_name: 工作流名称（可选）

    Returns:
        GenerationResult 对象
    """
    generator = WorkflowGenerator(llm_client=llm_client)
    return await generator.generate_workflow(
        description=description,
        workflow_name=workflow_name,
    )


def validate_workflow_dsl(dsl: str) -> ValidationResult:
    """验证工作流 DSL 的便捷函数

    Args:
        dsl: DSL 代码

    Returns:
        ValidationResult 对象
    """
    generator = WorkflowGenerator()
    return generator.validate_dsl(dsl)

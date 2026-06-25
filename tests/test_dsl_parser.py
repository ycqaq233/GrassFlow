"""
DSL 解析器测试

测试内容：
- 工作流定义解析
- Agent 声明解析
- 执行流解析（顺序/并行/条件/立即执行）
"""

import pytest
from tui.dsl_parser import DSLParser, DSLError


class TestDSLParser:
    """DSL 解析器测试"""

    def test_parse_simple_workflow(self):
        """测试解析简单工作流"""
        dsl = """
        workflow test {
          agent A {
            model: "gpt-4"
            prompt: "test"
          }
          agent B {
            model: "gpt-4"
            prompt: "test"
          }
          A -> B
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert workflow.name == "test"
        assert len(workflow.agents) == 2
        assert len(workflow.edges) == 1
        assert workflow.edges[0].source == "A"
        assert workflow.edges[0].target == "B"

    def test_parse_agent_declaration(self):
        """测试解析 Agent 声明"""
        dsl = """
        workflow test {
          agent my_agent {
            model: "gpt-4"
            prompt: "test prompt"
            input_schema: { "text": "string" }
            output_schema: { "result": "string" }
            on_fail: "retry"
            retry_count: 3
          }
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.agents) == 1
        agent = workflow.agents[0]
        assert agent.name == "my_agent"
        assert agent.model == "gpt-4"
        assert agent.prompt == "test prompt"
        assert agent.on_fail == "retry"
        assert agent.retry_count == 3

    def test_parse_condition_agent(self):
        """测试解析条件 Agent"""
        dsl = """
        workflow test {
          agent route {
            type: "condition"
            rules: ["urgent", "normal", "info"]
          }
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.agents) == 1
        agent = workflow.agents[0]
        assert agent.name == "route"
        assert agent.type.value == "condition"

    def test_parse_sequence_flow(self):
        """测试解析顺序流：A -> B -> C"""
        dsl = """
        workflow test {
          agent A { model: "gpt-4" }
          agent B { model: "gpt-4" }
          agent C { model: "gpt-4" }
          A -> B -> C
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.edges) == 2
        assert workflow.edges[0].source == "A"
        assert workflow.edges[0].target == "B"
        assert workflow.edges[1].source == "B"
        assert workflow.edges[1].target == "C"

    def test_parse_parallel_flow(self):
        """测试解析并行流：(A, B) -> C"""
        dsl = """
        workflow test {
          agent A { model: "gpt-4" }
          agent B { model: "gpt-4" }
          agent C { model: "gpt-4" }
          (A, B) -> C
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.edges) == 2
        assert any(e.source == "A" and e.target == "C" for e in workflow.edges)
        assert any(e.source == "B" and e.target == "C" for e in workflow.edges)

    def test_parse_condition_flow(self):
        """测试解析条件分支流：route -> [urgent] A, [normal] B"""
        dsl = """
        workflow test {
          agent route {
            type: "condition"
            rules: ["urgent", "normal"]
          }
          agent A { model: "gpt-4" }
          agent B { model: "gpt-4" }
          route -> [urgent] A, [normal] B
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.edges) == 2
        urgent_edge = next(e for e in workflow.edges if e.condition == "urgent")
        normal_edge = next(e for e in workflow.edges if e.condition == "normal")
        assert urgent_edge.source == "route"
        assert urgent_edge.target == "A"
        assert normal_edge.source == "route"
        assert normal_edge.target == "B"

    def test_parse_immediate_flow(self):
        """测试解析立即执行流：A | B"""
        dsl = """
        workflow test {
          agent A { model: "gpt-4" }
          agent B { model: "gpt-4" }
          A | B
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.edges) == 1
        assert workflow.edges[0].source == "A"
        assert workflow.edges[0].target == "B"
        assert workflow.edges[0].interaction_type.value == "immediate"

    def test_parse_complex_flow(self):
        """测试解析复杂流：(A, B) -> route -> [urgent] C, [normal] D"""
        dsl = """
        workflow test {
          agent A { model: "gpt-4" }
          agent B { model: "gpt-4" }
          agent route {
            type: "condition"
            rules: ["urgent", "normal"]
          }
          agent C { model: "gpt-4" }
          agent D { model: "gpt-4" }
          (A, B) -> route
          route -> [urgent] C, [normal] D
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.agents) == 5
        assert len(workflow.edges) == 4

    def test_parse_ticket_processing_example(self):
        """测试解析工单处理示例"""
        dsl = """
        workflow ticket_processing {
          agent classify {
            model: "gpt-4"
            prompt: "分类工单: {input}"
            input_schema: { "ticket": "string" }
            output_schema: { "category": "string" }
          }
          agent priority {
            model: "gpt-4"
            prompt: "判断优先级: {input}"
          }
          agent route {
            type: "condition"
            rules: ["urgent", "normal", "info"]
          }
          agent human {
            type: "manual"
            prompt: "人工处理工单"
          }
          agent bot {
            model: "gpt-4"
            prompt: "自动回复: {input}"
          }
          (classify, priority) -> route
          route -> [urgent] human, [normal] bot
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert workflow.name == "ticket_processing"
        assert len(workflow.agents) == 5
        assert len(workflow.edges) == 4

    def test_parse_competitor_analysis_example(self):
        """测试解析竞品分析示例"""
        dsl = """
        workflow competitor_analysis {
          agent search_a {
            model: "gpt-4"
            prompt: "搜索竞品A"
          }
          agent search_b {
            model: "gpt-4"
            prompt: "搜索竞品B"
          }
          agent search_c {
            model: "gpt-4"
            prompt: "搜索竞品C"
          }
          agent analyze {
            model: "gpt-4"
            prompt: "分析竞品"
          }
          agent report {
            model: "gpt-4"
            prompt: "生成报告"
          }
          (search_a, search_b, search_c) -> analyze -> report
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert workflow.name == "competitor_analysis"
        assert len(workflow.agents) == 5
        assert len(workflow.edges) == 4

    def test_parse_error_missing_workflow(self):
        """测试解析错误：缺少 workflow 定义"""
        dsl = """
        agent A { model: "gpt-4" }
        """
        parser = DSLParser()

        with pytest.raises(DSLError):
            parser.parse(dsl)

    def test_parse_error_missing_agent(self):
        """测试解析错误：引用未定义的 Agent"""
        dsl = """
        workflow test {
          agent A { model: "gpt-4" }
          A -> B
        }
        """
        parser = DSLParser()

        with pytest.raises(DSLError, match="Agent 'B' not defined"):
            parser.parse(dsl)

    def test_parse_empty_workflow(self):
        """测试解析空工作流"""
        dsl = """
        workflow test {
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert workflow.name == "test"
        assert len(workflow.agents) == 0
        assert len(workflow.edges) == 0

    def test_parse_comments(self):
        """测试解析带注释的工作流"""
        dsl = """
        # 这是注释
        workflow test {
          # Agent 声明
          agent A {
            model: "gpt-4"  # 模型
          }
          # 执行流
          A -> A  # 自环不会被检测到，因为 DAG 引擎在运行时才检测
        }
        """
        parser = DSLParser()
        # 这个应该能解析成功，自环在 DAG 构建时才检测
        workflow = parser.parse(dsl)
        assert workflow.name == "test"

    def test_parse_multiline_prompt(self):
        """测试解析多行 prompt"""
        dsl = """
        workflow test {
          agent A {
            model: "gpt-4"
            prompt: "这是一个很长的提示词"
          }
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.agents) == 1
        assert workflow.agents[0].prompt == "这是一个很长的提示词"

    def test_parse_agent_with_type(self):
        """测试解析带类型的 Agent"""
        dsl = """
        workflow test {
          agent input {
            type: "input"
          }
          agent output {
            type: "output"
          }
          agent manual {
            type: "manual"
          }
          input -> output
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.agents) == 3
        assert workflow.agents[0].type.value == "input"
        assert workflow.agents[1].type.value == "output"
        assert workflow.agents[2].type.value == "manual"

    def test_parse_parallel_with_multiple_targets(self):
        """测试解析并行流到多个目标：(A, B) -> (C, D)"""
        dsl = """
        workflow test {
          agent A { model: "gpt-4" }
          agent B { model: "gpt-4" }
          agent C { model: "gpt-4" }
          agent D { model: "gpt-4" }
          (A, B) -> C
          (A, B) -> D
        }
        """
        parser = DSLParser()
        workflow = parser.parse(dsl)

        assert len(workflow.edges) == 4

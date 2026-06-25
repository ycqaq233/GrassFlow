"""
DAG 引擎测试

测试内容：
- 拓扑排序
- 依赖解析
- 环检测
- 并行分组
"""

import pytest
from core.models import Workflow, AgentConfig, Edge, AgentType, InteractionType
from core.dag import DAG, DAGError, topological_sort, get_parallel_groups, detect_cycle


class TestDAG:
    """DAG 引擎测试"""

    def test_simple_sequence(self):
        """测试简单顺序：A -> B -> C"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="B", target="C"))

        dag = DAG(workflow)
        order = dag.topological_sort()

        # 验证顺序：A 在 B 前，B 在 C 前
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_parallel_execution(self):
        """测试并行执行：(A, B) -> C"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="C", interaction_type=InteractionType.PARALLEL))
        workflow.add_edge(Edge(source="B", target="C", interaction_type=InteractionType.PARALLEL))

        dag = DAG(workflow)
        groups = dag.get_parallel_groups()

        # 第一组应该是 A 和 B（并行），第二组是 C
        assert len(groups) == 2
        assert set(groups[0]) == {"A", "B"}
        assert groups[1] == ["C"]

    def test_diamond_pattern(self):
        """测试菱形依赖：A -> (B, C) -> D"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="D", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="A", target="C"))
        workflow.add_edge(Edge(source="B", target="D"))
        workflow.add_edge(Edge(source="C", target="D"))

        dag = DAG(workflow)
        groups = dag.get_parallel_groups()

        # 第一组：A，第二组：B 和 C（并行），第三组：D
        assert len(groups) == 3
        assert groups[0] == ["A"]
        assert set(groups[1]) == {"B", "C"}
        assert groups[2] == ["D"]

    def test_cycle_detection(self):
        """测试环检测：A -> B -> C -> A（应该报错）"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="B", target="C"))
        workflow.add_edge(Edge(source="C", target="A"))

        with pytest.raises(DAGError, match="Cycle detected"):
            DAG(workflow)

    def test_self_loop_detection(self):
        """测试自环检测：A -> A（应该报错）"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="A"))

        with pytest.raises(DAGError, match="Cycle detected"):
            DAG(workflow)

    def test_empty_workflow(self):
        """测试空工作流"""
        workflow = Workflow(name="test")
        dag = DAG(workflow)

        assert dag.topological_sort() == []
        assert dag.get_parallel_groups() == []

    def test_single_agent(self):
        """测试单个 Agent"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))

        dag = DAG(workflow)
        assert dag.topological_sort() == ["A"]
        assert dag.get_parallel_groups() == [["A"]]

    def test_get_dependencies(self):
        """测试获取依赖关系"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="C"))
        workflow.add_edge(Edge(source="B", target="C"))

        dag = DAG(workflow)

        assert dag.get_dependencies("A") == []
        assert dag.get_dependencies("B") == []
        assert set(dag.get_dependencies("C")) == {"A", "B"}

    def test_get_dependents(self):
        """测试获取被依赖关系"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="A", target="C"))

        dag = DAG(workflow)

        assert set(dag.get_dependents("A")) == {"B", "C"}
        assert dag.get_dependents("B") == []
        assert dag.get_dependents("C") == []

    def test_is_ready(self):
        """测试判断 Agent 是否就绪"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="C"))
        workflow.add_edge(Edge(source="B", target="C"))

        dag = DAG(workflow)

        # A 和 B 没有依赖，应该就绪
        assert dag.is_ready("A", completed=set()) is True
        assert dag.is_ready("B", completed=set()) is True

        # C 依赖 A 和 B，未完成时不就绪
        assert dag.is_ready("C", completed=set()) is False
        assert dag.is_ready("C", completed={"A"}) is False

        # A 和 B 都完成后，C 就绪
        assert dag.is_ready("C", completed={"A", "B"}) is True

    def test_immediate_interaction(self):
        """测试立即执行类型：A | B"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="B", interaction_type=InteractionType.IMMEDIATE))

        dag = DAG(workflow)

        # 立即执行类型应该被正确识别
        edge = workflow.edges[0]
        assert edge.interaction_type == InteractionType.IMMEDIATE

    def test_condition_interaction(self):
        """测试条件分支类型"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="route", type=AgentType.CONDITION))
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_edge(Edge(source="route", target="A", interaction_type=InteractionType.CONDITION, condition="urgent"))
        workflow.add_edge(Edge(source="route", target="B", interaction_type=InteractionType.CONDITION, condition="normal"))

        dag = DAG(workflow)

        # 条件分支应该被正确识别
        condition_edges = dag.get_condition_edges("route")
        assert len(condition_edges) == 2
        assert any(e.condition == "urgent" for e in condition_edges)
        assert any(e.condition == "normal" for e in condition_edges)

    def test_complex_workflow(self):
        """测试复杂工作流：多个并行组和条件分支"""
        workflow = Workflow(name="test")
        # 输入层
        workflow.add_agent(AgentConfig(name="input1", type=AgentType.INPUT))
        workflow.add_agent(AgentConfig(name="input2", type=AgentType.INPUT))

        # 处理层（并行）
        workflow.add_agent(AgentConfig(name="process1", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="process2", type=AgentType.LLM))

        # 路由层
        workflow.add_agent(AgentConfig(name="route", type=AgentType.CONDITION))

        # 输出层
        workflow.add_agent(AgentConfig(name="output1", type=AgentType.OUTPUT))
        workflow.add_agent(AgentConfig(name="output2", type=AgentType.OUTPUT))

        # 边
        workflow.add_edge(Edge(source="input1", target="process1"))
        workflow.add_edge(Edge(source="input2", target="process2"))
        workflow.add_edge(Edge(source="process1", target="route"))
        workflow.add_edge(Edge(source="process2", target="route"))
        workflow.add_edge(Edge(source="route", target="output1", interaction_type=InteractionType.CONDITION, condition="success"))
        workflow.add_edge(Edge(source="route", target="output2", interaction_type=InteractionType.CONDITION, condition="fail"))

        dag = DAG(workflow)
        order = dag.topological_sort()

        # 验证拓扑排序的有效性
        for edge in workflow.edges:
            assert order.index(edge.source) < order.index(edge.target)

    def test_multiple_roots(self):
        """测试多个根节点"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="C"))
        workflow.add_edge(Edge(source="B", target="C"))

        dag = DAG(workflow)
        roots = dag.get_roots()

        assert set(roots) == {"A", "B"}

    def test_multiple_leaves(self):
        """测试多个叶子节点"""
        workflow = Workflow(name="test")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM))
        workflow.add_agent(AgentConfig(name="C", type=AgentType.LLM))
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="A", target="C"))

        dag = DAG(workflow)
        leaves = dag.get_leaves()

        assert set(leaves) == {"B", "C"}

"""
DAG 引擎测试

测试内容：
- 拓扑排序
- 依赖解析
- 环检测
- 并行分组
"""

import pytest
try:
    from core.models import (
        Component, Workflow, AgentInstance, Connection, Port, ModelConfig,
        WorkflowV1, AgentConfig, Edge, AgentType, InteractionType,
    )
except ImportError:
    from core.dsl_v2_ast import Component, Workflow, AgentInstance, Connection, Port, ModelConfig
    from core.models import WorkflowV1, AgentConfig, Edge, AgentType, InteractionType
from core.dag import DAG, DAGError, topological_sort, get_parallel_groups, detect_cycle


def make_v1_workflow(
    agents: list[tuple[str, str]] | None = None,
    edges: list[tuple[str, str, str | None, str | None]] | None = None,
    name: str = "test",
) -> WorkflowV1:
    """Helper: build a v1 Workflow from concise specs.

    Args:
        agents: list of (name, type_str) e.g. [("A", "llm"), ("B", "condition")]
        edges: list of (source, target, interaction_str, condition)
               interaction_str is one of "sequence","parallel","immediate","condition" or None
        name: workflow name
    """
    type_map = {
        "llm": AgentType.LLM,
        "condition": AgentType.CONDITION,
        "manual": AgentType.MANUAL,
        "input": AgentType.INPUT,
        "output": AgentType.OUTPUT,
    }
    interaction_map = {
        "sequence": InteractionType.SEQUENCE,
        "parallel": InteractionType.PARALLEL,
        "immediate": InteractionType.IMMEDIATE,
        "condition": InteractionType.CONDITION,
        None: InteractionType.SEQUENCE,
    }

    wf = WorkflowV1(name=name)
    for agent_name, agent_type in (agents or []):
        wf.add_agent(AgentConfig(name=agent_name, type=type_map.get(agent_type, AgentType.LLM)))
    for src, tgt, itype, cond in (edges or []):
        wf.add_edge(Edge(
            source=src,
            target=tgt,
            interaction_type=interaction_map.get(itype, InteractionType.SEQUENCE),
            condition=cond,
        ))
    return wf


class TestDAG:
    """DAG 引擎测试"""

    def test_simple_sequence(self):
        """测试简单顺序：A -> B -> C"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "B", None, None), ("B", "C", None, None)],
        )

        dag = DAG(workflow)
        order = dag.topological_sort()

        # 验证顺序：A 在 B 前，B 在 C 前
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_parallel_execution(self):
        """测试并行执行：(A, B) -> C"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "C", "parallel", None), ("B", "C", "parallel", None)],
        )

        dag = DAG(workflow)
        groups = dag.get_parallel_groups()

        # 第一组应该是 A 和 B（并行），第二组是 C
        assert len(groups) == 2
        assert set(groups[0]) == {"A", "B"}
        assert groups[1] == ["C"]

    def test_diamond_pattern(self):
        """测试菱形依赖：A -> (B, C) -> D"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm"), ("D", "llm")],
            edges=[
                ("A", "B", None, None),
                ("A", "C", None, None),
                ("B", "D", None, None),
                ("C", "D", None, None),
            ],
        )

        dag = DAG(workflow)
        groups = dag.get_parallel_groups()

        # 第一组：A，第二组：B 和 C（并行），第三组：D
        assert len(groups) == 3
        assert groups[0] == ["A"]
        assert set(groups[1]) == {"B", "C"}
        assert groups[2] == ["D"]

    def test_cycle_detection(self):
        """测试环检测：A -> B -> C -> A（应该报错）"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "B", None, None), ("B", "C", None, None), ("C", "A", None, None)],
        )

        with pytest.raises(DAGError, match="Cycle detected"):
            DAG(workflow)

    def test_self_loop_detection(self):
        """测试自环检测：A -> A（应该报错）"""
        workflow = make_v1_workflow(
            agents=[("A", "llm")],
            edges=[("A", "A", None, None)],
        )

        with pytest.raises(DAGError, match="Cycle detected"):
            DAG(workflow)

    def test_empty_workflow(self):
        """测试空工作流"""
        workflow = WorkflowV1(name="test")
        dag = DAG(workflow)

        assert dag.topological_sort() == []
        assert dag.get_parallel_groups() == []

    def test_single_agent(self):
        """测试单个 Agent"""
        workflow = make_v1_workflow(agents=[("A", "llm")])

        dag = DAG(workflow)
        assert dag.topological_sort() == ["A"]
        assert dag.get_parallel_groups() == [["A"]]

    def test_get_dependencies(self):
        """测试获取依赖关系"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "C", None, None), ("B", "C", None, None)],
        )

        dag = DAG(workflow)

        assert dag.get_dependencies("A") == []
        assert dag.get_dependencies("B") == []
        assert set(dag.get_dependencies("C")) == {"A", "B"}

    def test_get_dependents(self):
        """测试获取被依赖关系"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "B", None, None), ("A", "C", None, None)],
        )

        dag = DAG(workflow)

        assert set(dag.get_dependents("A")) == {"B", "C"}
        assert dag.get_dependents("B") == []
        assert dag.get_dependents("C") == []

    def test_is_ready(self):
        """测试判断 Agent 是否就绪"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "C", None, None), ("B", "C", None, None)],
        )

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
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm")],
            edges=[("A", "B", "immediate", None)],
        )

        dag = DAG(workflow)

        # 立即执行类型应该被正确识别
        edge = workflow.edges[0]
        assert edge.interaction_type == InteractionType.IMMEDIATE

    def test_condition_interaction(self):
        """测试条件分支类型"""
        workflow = make_v1_workflow(
            agents=[("route", "condition"), ("A", "llm"), ("B", "llm")],
            edges=[
                ("route", "A", "condition", "urgent"),
                ("route", "B", "condition", "normal"),
            ],
        )

        dag = DAG(workflow)

        # 条件分支应该被正确识别
        condition_edges = dag.get_condition_edges("route")
        assert len(condition_edges) == 2
        assert any(e.condition == "urgent" for e in condition_edges)
        assert any(e.condition == "normal" for e in condition_edges)

    def test_complex_workflow(self):
        """测试复杂工作流：多个并行组和条件分支"""
        workflow = make_v1_workflow(
            agents=[
                ("input1", "input"), ("input2", "input"),
                ("process1", "llm"), ("process2", "llm"),
                ("route", "condition"),
                ("output1", "output"), ("output2", "output"),
            ],
            edges=[
                ("input1", "process1", None, None),
                ("input2", "process2", None, None),
                ("process1", "route", None, None),
                ("process2", "route", None, None),
                ("route", "output1", "condition", "success"),
                ("route", "output2", "condition", "fail"),
            ],
        )

        dag = DAG(workflow)
        order = dag.topological_sort()

        # 验证拓扑排序的有效性
        for edge in workflow.edges:
            assert order.index(edge.source) < order.index(edge.target)

    def test_multiple_roots(self):
        """测试多个根节点"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "C", None, None), ("B", "C", None, None)],
        )

        dag = DAG(workflow)
        roots = dag.get_roots()

        assert set(roots) == {"A", "B"}

    def test_multiple_leaves(self):
        """测试多个叶子节点"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            edges=[("A", "B", None, None), ("A", "C", None, None)],
        )

        dag = DAG(workflow)
        leaves = dag.get_leaves()

        assert set(leaves) == {"B", "C"}

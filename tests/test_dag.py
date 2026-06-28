"""
DAG 引擎测试

测试内容：
- 拓扑排序
- 依赖解析
- 环检测
- 并行分组

使用 v2 类型: Workflow, AgentInstance, Connection
"""

import pytest
from core.models import Workflow, AgentInstance, Connection
from core.dag import DAG, DAGError, topological_sort, get_parallel_groups, detect_cycle


def make_workflow(
    agent_names: list[str] | None = None,
    connections: list[tuple[str, list[str]]] | None = None,
    name: str = "test",
) -> Workflow:
    """Helper: build a v2 Workflow from concise specs.

    Args:
        agent_names: list of agent names
        connections: list of (source, [targets])
        name: workflow name
    """
    agents = [AgentInstance(name=n) for n in (agent_names or [])]
    conns = [
        Connection(source_agent=src, target_agents=tgts)
        for src, tgts in (connections or [])
    ]
    return Workflow(name=name, agents=agents, connections=conns)


class TestDAG:
    """DAG 引擎测试"""

    def test_simple_sequence(self):
        """测试简单顺序：A -> B -> C"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["B"]), ("B", ["C"])],
        )

        dag = DAG(workflow)
        order = dag.topological_sort()

        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_parallel_execution(self):
        """测试并行执行：(A, B) -> C"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
        )

        dag = DAG(workflow)
        groups = dag.get_parallel_groups()

        assert len(groups) == 2
        assert set(groups[0]) == {"A", "B"}
        assert groups[1] == ["C"]

    def test_diamond_pattern(self):
        """测试菱形依赖：A -> (B, C) -> D"""
        workflow = make_workflow(
            agent_names=["A", "B", "C", "D"],
            connections=[("A", ["B", "C"]), ("B", ["D"]), ("C", ["D"])],
        )

        dag = DAG(workflow)
        groups = dag.get_parallel_groups()

        assert len(groups) == 3
        assert groups[0] == ["A"]
        assert set(groups[1]) == {"B", "C"}
        assert groups[2] == ["D"]

    def test_cycle_detection(self):
        """测试环检测：A -> B -> C -> A（应该报错）"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["B"]), ("B", ["C"]), ("C", ["A"])],
        )

        with pytest.raises(DAGError, match="Cycle detected"):
            DAG(workflow)

    def test_self_loop_detection(self):
        """测试自环检测：A -> A（应该报错）"""
        workflow = make_workflow(
            agent_names=["A"],
            connections=[("A", ["A"])],
        )

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
        workflow = make_workflow(agent_names=["A"])

        dag = DAG(workflow)
        assert dag.topological_sort() == ["A"]
        assert dag.get_parallel_groups() == [["A"]]

    def test_get_dependencies(self):
        """测试获取依赖关系"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
        )

        dag = DAG(workflow)

        assert dag.get_dependencies("A") == []
        assert dag.get_dependencies("B") == []
        assert set(dag.get_dependencies("C")) == {"A", "B"}

    def test_get_dependents(self):
        """测试获取被依赖关系"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["B", "C"])],
        )

        dag = DAG(workflow)

        assert set(dag.get_dependents("A")) == {"B", "C"}
        assert dag.get_dependents("B") == []
        assert dag.get_dependents("C") == []

    def test_is_ready(self):
        """测试判断 Agent 是否就绪"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
        )

        dag = DAG(workflow)

        assert dag.is_ready("A", completed=set()) is True
        assert dag.is_ready("B", completed=set()) is True
        assert dag.is_ready("C", completed=set()) is False
        assert dag.is_ready("C", completed={"A"}) is False
        assert dag.is_ready("C", completed={"A", "B"}) is True

    def test_condition_routing(self):
        """测试条件路由：Connection 带 routing_rules"""
        workflow = Workflow(
            name="test_condition",
            agents=[
                AgentInstance(name="route"),
                AgentInstance(name="A"),
                AgentInstance(name="B"),
            ],
            connections=[
                Connection(
                    source_agent="route",
                    target_agents=["A", "B"],
                    routing_rules={
                        "urgent": ["A"],
                        "normal": ["B"],
                    },
                ),
            ],
        )

        dag = DAG(workflow)

        # 结构上 A 和 B 都依赖 route
        assert "route" in dag.get_dependencies("A")
        assert "route" in dag.get_dependencies("B")

        # 获取入边连接
        incoming_a = dag.get_incoming_connections("A")
        assert len(incoming_a) == 1
        assert incoming_a[0].routing_rules == {"urgent": ["A"], "normal": ["B"]}

    def test_complex_workflow(self):
        """测试复杂工作流：多个并行组和条件分支"""
        workflow = make_workflow(
            agent_names=["input1", "input2", "process1", "process2", "route", "output1", "output2"],
            connections=[
                ("input1", ["process1"]),
                ("input2", ["process2"]),
                ("process1", ["route"]),
                ("process2", ["route"]),
                ("route", ["output1", "output2"]),
            ],
        )

        dag = DAG(workflow)
        order = dag.topological_sort()

        # 验证拓扑排序的有效性
        for conn in workflow.connections:
            for target in conn.target_agents:
                assert order.index(conn.source_agent) < order.index(target)

    def test_multiple_roots(self):
        """测试多个根节点"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
        )

        dag = DAG(workflow)
        roots = dag.get_roots()

        assert set(roots) == {"A", "B"}

    def test_multiple_leaves(self):
        """测试多个叶子节点"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["B", "C"])],
        )

        dag = DAG(workflow)
        leaves = dag.get_leaves()

        assert set(leaves) == {"B", "C"}

    def test_get_incoming_connections(self):
        """测试获取入边连接"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
        )

        dag = DAG(workflow)

        incoming_c = dag.get_incoming_connections("C")
        assert len(incoming_c) == 2
        sources = {c.source_agent for c in incoming_c}
        assert sources == {"A", "B"}

    def test_get_outgoing_connections(self):
        """测试获取出边连接"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["B", "C"])],
        )

        dag = DAG(workflow)

        outgoing_a = dag.get_outgoing_connections("A")
        assert len(outgoing_a) == 1
        assert outgoing_a[0].target_agents == ["B", "C"]

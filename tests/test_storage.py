"""
存储模块测试

测试内容：
- 工作流保存
- 工作流加载
- 工作流列表
- 工作流删除

使用 v2 类型: Workflow, AgentInstance, Connection
"""

import pytest
import tempfile
from pathlib import Path

from core.models import Workflow, AgentInstance, Connection
from core.storage import WorkflowStorage, StorageError


def make_workflow(
    agent_names: list[str] | None = None,
    connections: list[tuple[str, list[str]]] | None = None,
    name: str = "test",
) -> Workflow:
    """Build a v2 Workflow from concise specs."""
    agents = [AgentInstance(name=n) for n in (agent_names or [])]
    conns = [
        Connection(source_agent=src, target_agents=tgts)
        for src, tgts in (connections or [])
    ]
    return Workflow(name=name, agents=agents, connections=conns)


class TestWorkflowStorage:
    """WorkflowStorage 测试"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage(self, temp_dir):
        return WorkflowStorage(base_dir=temp_dir)

    @pytest.fixture
    def sample_workflow(self):
        return make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_workflow",
        )

    def test_save_and_load(self, storage, sample_workflow):
        """测试保存和加载"""
        filepath = storage.save(sample_workflow)
        assert filepath.exists()

        loaded = storage.load("test_workflow.json")
        assert loaded.name == "test_workflow"
        assert len(loaded.agents) == 2
        assert len(loaded.connections) == 1

    def test_save_custom_filename(self, storage, sample_workflow):
        """测试自定义文件名保存"""
        filepath = storage.save(sample_workflow, "custom.json")
        assert filepath.name == "custom.json"
        assert filepath.exists()

    def test_list_workflows(self, storage, sample_workflow):
        """测试列出工作流"""
        assert storage.list() == []

        storage.save(sample_workflow)

        workflows = storage.list()
        assert "test_workflow.json" in workflows

    def test_delete_workflow(self, storage, sample_workflow):
        """测试删除工作流"""
        storage.save(sample_workflow)
        assert storage.exists("test_workflow.json")

        storage.delete("test_workflow.json")
        assert not storage.exists("test_workflow.json")

    def test_load_nonexistent(self, storage):
        """测试加载不存在的工作流"""
        with pytest.raises(StorageError, match="not found"):
            storage.load("nonexistent.json")

    def test_delete_nonexistent(self, storage):
        """测试删除不存在的工作流"""
        with pytest.raises(StorageError, match="not found"):
            storage.delete("nonexistent.json")

    def test_exists(self, storage, sample_workflow):
        """测试检查存在性"""
        assert not storage.exists("test_workflow.json")

        storage.save(sample_workflow)
        assert storage.exists("test_workflow.json")

    def test_save_preserves_agents(self, storage, sample_workflow):
        """测试保存保留 Agent 信息"""
        storage.save(sample_workflow)
        loaded = storage.load("test_workflow.json")

        assert loaded.agents[0].name == "A"
        assert loaded.agents[1].name == "B"

    def test_save_preserves_connections(self, storage, sample_workflow):
        """测试保存保留连接信息"""
        storage.save(sample_workflow)
        loaded = storage.load("test_workflow.json")

        assert len(loaded.connections) == 1
        assert loaded.connections[0].source_agent == "A"
        assert loaded.connections[0].target_agents == ["B"]

    def test_multiple_workflows(self, storage):
        """测试多个工作流"""
        workflow1 = make_workflow(agent_names=["A"], name="workflow1")
        workflow2 = make_workflow(agent_names=["B"], name="workflow2")

        storage.save(workflow1)
        storage.save(workflow2)

        workflows = storage.list()
        assert len(workflows) == 2
        assert "workflow1.json" in workflows
        assert "workflow2.json" in workflows

    def test_save_with_routing_rules(self, storage):
        """测试保存带 routing_rules 的连接"""
        workflow = Workflow(
            name="routing_test",
            agents=[
                AgentInstance(name="route"),
                AgentInstance(name="A"),
                AgentInstance(name="B"),
            ],
            connections=[
                Connection(
                    source_agent="route",
                    target_agents=["A", "B"],
                    routing_rules={"urgent": ["A"], "normal": ["B"]},
                ),
            ],
        )

        storage.save(workflow)
        loaded = storage.load("routing_test.json")

        assert loaded.connections[0].routing_rules == {"urgent": ["A"], "normal": ["B"]}

"""
存储模块测试

测试内容：
- 工作流保存
- 工作流加载
- 工作流列表
- 工作流删除
"""

import pytest
import tempfile
from pathlib import Path

try:
    from core.models import (
        Component, Workflow, AgentInstance, Connection, Port, ModelConfig,
        WorkflowV1, AgentConfig, Edge, AgentType, InteractionType,
    )
except ImportError:
    from core.dsl_v2_ast import Component, Workflow, AgentInstance, Connection, Port, ModelConfig
    from core.models import WorkflowV1, AgentConfig, Edge, AgentType, InteractionType
from core.storage import WorkflowStorage, StorageError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_v1_workflow(
    agents: list[tuple[str, str, str]] | None = None,
    edges: list[tuple[str, str]] | None = None,
    name: str = "test",
) -> WorkflowV1:
    """Build a v1 Workflow from concise specs."""
    type_map = {
        "llm": AgentType.LLM,
        "condition": AgentType.CONDITION,
        "manual": AgentType.MANUAL,
        "input": AgentType.INPUT,
        "output": AgentType.OUTPUT,
    }
    wf = WorkflowV1(name=name)
    for agent_name, agent_type, model in (agents or []):
        wf.add_agent(AgentConfig(
            name=agent_name,
            type=type_map.get(agent_type, AgentType.LLM),
            model=model,
        ))
    for src, tgt in (edges or []):
        wf.add_edge(Edge(source=src, target=tgt))
    return wf


class TestWorkflowStorage:
    """WorkflowStorage 测试"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage(self, temp_dir):
        """创建存储实例"""
        return WorkflowStorage(base_dir=temp_dir)

    @pytest.fixture
    def sample_workflow(self):
        """创建示例工作流"""
        return make_v1_workflow(
            agents=[("A", "llm", "gpt-4"), ("B", "llm", "gpt-4")],
            edges=[("A", "B")],
            name="test_workflow",
        )

    def test_save_and_load(self, storage, sample_workflow):
        """测试保存和加载"""
        # 保存
        filepath = storage.save(sample_workflow)
        assert filepath.exists()

        # 加载
        loaded = storage.load("test_workflow.json")
        assert loaded.name == "test_workflow"
        assert len(loaded.agents) == 2
        assert len(loaded.edges) == 1

    def test_save_custom_filename(self, storage, sample_workflow):
        """测试自定义文件名保存"""
        filepath = storage.save(sample_workflow, "custom.json")
        assert filepath.name == "custom.json"
        assert filepath.exists()

    def test_list_workflows(self, storage, sample_workflow):
        """测试列出工作流"""
        # 初始为空
        assert storage.list() == []

        # 保存一个工作流
        storage.save(sample_workflow)

        # 列出工作流
        workflows = storage.list()
        assert "test_workflow.json" in workflows

    def test_delete_workflow(self, storage, sample_workflow):
        """测试删除工作流"""
        # 保存
        storage.save(sample_workflow)
        assert storage.exists("test_workflow.json")

        # 删除
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

        # 检查 Agent 信息
        agent_a = loaded.get_agent("A")
        assert agent_a is not None
        assert agent_a.model == "gpt-4"

    def test_save_preserves_edges(self, storage, sample_workflow):
        """测试保存保留边信息"""
        storage.save(sample_workflow)
        loaded = storage.load("test_workflow.json")

        # 检查边信息
        assert len(loaded.edges) == 1
        assert loaded.edges[0].source == "A"
        assert loaded.edges[0].target == "B"

    def test_multiple_workflows(self, storage):
        """测试多个工作流"""
        # 创建多个工作流
        workflow1 = make_v1_workflow(agents=[("A", "llm", "gpt-4")], name="workflow1")
        workflow2 = make_v1_workflow(agents=[("B", "llm", "gpt-4")], name="workflow2")

        # 保存
        storage.save(workflow1)
        storage.save(workflow2)

        # 列出
        workflows = storage.list()
        assert len(workflows) == 2
        assert "workflow1.json" in workflows
        assert "workflow2.json" in workflows

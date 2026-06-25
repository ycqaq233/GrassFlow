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

from core.models import Workflow, AgentConfig, Edge, AgentType, InteractionType
from core.storage import WorkflowStorage, StorageError


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
        workflow = Workflow(name="test_workflow")
        workflow.add_agent(AgentConfig(name="A", type=AgentType.LLM, model="gpt-4"))
        workflow.add_agent(AgentConfig(name="B", type=AgentType.LLM, model="gpt-4"))
        workflow.add_edge(Edge(source="A", target="B"))
        return workflow

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
        workflow1 = Workflow(name="workflow1")
        workflow1.add_agent(AgentConfig(name="A", type=AgentType.LLM))

        workflow2 = Workflow(name="workflow2")
        workflow2.add_agent(AgentConfig(name="B", type=AgentType.LLM))

        # 保存
        storage.save(workflow1)
        storage.save(workflow2)

        # 列出
        workflows = storage.list()
        assert len(workflows) == 2
        assert "workflow1.json" in workflows
        assert "workflow2.json" in workflows

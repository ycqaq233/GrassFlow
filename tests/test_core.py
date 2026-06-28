"""
核心模块测试
"""

import asyncio
import pytest
from core.agent import Agent
from core.dsl_v2_ast import Component, Port, ModelConfig
from core.context import WorkflowContext
from core.models import Workflow, AgentConfig as ModelAgentConfig, Edge, InteractionType


# 测试用的 Agent 实现
class MockAgent(Agent):
    """测试用的 Mock Agent"""

    async def run(self, input_data: dict) -> dict:
        return {"result": f"processed: {input_data}"}


@pytest.fixture
def agent_component():
    """创建测试用的 Component"""
    return Component(
        name="test_agent",
        system_prompt="test prompt",
        ports=[
            Port(name="input", direction="input", type="string"),
            Port(name="result", direction="output", type="string"),
        ],
        model=ModelConfig(default="gpt-4"),
    )


@pytest.fixture
def mock_agent(agent_component):
    """创建测试用的 Mock Agent"""
    return MockAgent(agent_component)


@pytest.fixture
def context():
    """创建测试用的 WorkflowContext"""
    return WorkflowContext()


# Agent 测试
def test_agent_creation(mock_agent):
    """测试 Agent 创建"""
    assert mock_agent.name == "test_agent"
    assert mock_agent.on_fail == "stop"
    assert mock_agent.retry_count == 3


def test_agent_input_validation(mock_agent):
    """测试输入校验"""
    # 有效输入
    assert mock_agent.validate_input({"input": "test"}) is True

    # 无效输入（缺少必需字段）
    with pytest.raises(ValueError):
        mock_agent.validate_input({})


def test_agent_output_validation(mock_agent):
    """测试输出校验"""
    # 有效输出
    assert mock_agent.validate_output({"result": "test"}) is True

    # 无效输出
    with pytest.raises(ValueError):
        mock_agent.validate_output({"invalid": "data"})


@pytest.mark.asyncio
async def test_agent_execution(mock_agent):
    """测试 Agent 执行"""
    result = await mock_agent.execute({"input": "test"})
    assert "result" in result
    assert "processed:" in result["result"]


# Context 测试
def test_context_set_get(context):
    """测试 Context 的 set 和 get"""
    context.set("agent1", {"data": "test"})
    assert context.get("agent1") == {"data": "test"}
    assert context.get("nonexistent") == {}


def test_context_has_agent_data(context):
    """测试 Context 的 has_agent_data"""
    assert context.has_agent_data("agent1") is False
    context.set("agent1", {"data": "test"})
    assert context.has_agent_data("agent1") is True


def test_context_clear(context):
    """测试 Context 的 clear"""
    context.set("agent1", {"data": "test"})
    context.set("agent2", {"data": "test2"})
    context.clear()
    assert context.get("agent1") == {}
    assert context.get("agent2") == {}


def test_context_dependency_data(context, mock_agent):
    """测试获取依赖数据"""
    context.set("dep1", {"output": "test1"})
    context.set("dep2", {"output": "test2"})

    deps = context.get_dependency_data(mock_agent, ["dep1", "dep2"])
    assert "_deps" in deps
    assert deps["_deps"]["dep1"] == {"output": "test1"}
    assert deps["_deps"]["dep2"] == {"output": "test2"}


# Workflow 测试
def test_workflow_creation():
    """测试 Workflow 创建"""
    workflow = Workflow(name="test_workflow")
    assert workflow.name == "test_workflow"
    assert len(workflow.agents) == 0
    assert len(workflow.edges) == 0


def test_workflow_add_agent():
    """测试添加 Agent"""
    workflow = Workflow(name="test_workflow")
    agent_config = ModelAgentConfig(name="agent1")
    workflow.add_agent(agent_config)

    assert len(workflow.agents) == 1
    assert workflow.get_agent("agent1") is not None


def test_workflow_add_duplicate_agent():
    """测试添加重复 Agent"""
    workflow = Workflow(name="test_workflow")
    agent_config = ModelAgentConfig(name="agent1")
    workflow.add_agent(agent_config)

    with pytest.raises(ValueError):
        workflow.add_agent(agent_config)


def test_workflow_add_edge():
    """测试添加边"""
    workflow = Workflow(name="test_workflow")
    workflow.add_agent(ModelAgentConfig(name="agent1"))
    workflow.add_agent(ModelAgentConfig(name="agent2"))

    edge = Edge(source="agent1", target="agent2")
    workflow.add_edge(edge)

    assert len(workflow.edges) == 1


def test_workflow_add_edge_invalid_source():
    """测试添加边时源 Agent 不存在"""
    workflow = Workflow(name="test_workflow")
    workflow.add_agent(ModelAgentConfig(name="agent2"))

    edge = Edge(source="nonexistent", target="agent2")
    with pytest.raises(ValueError):
        workflow.add_edge(edge)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

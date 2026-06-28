"""
核心模块测试
"""

import asyncio
import pytest
from core.agent import Agent
from core.dsl_v2_ast import Component, Port, ModelConfig
from core.context import WorkflowContext
try:
    from core.models import Workflow, AgentInstance, Connection
except ImportError:
    from core.dsl_v2_ast import Workflow, AgentInstance, Connection


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


# Workflow 测试 (v2 dataclass)
def test_workflow_creation():
    """测试 Workflow 创建"""
    workflow = Workflow(name="test_workflow")
    assert workflow.name == "test_workflow"
    assert len(workflow.agents) == 0
    assert len(workflow.connections) == 0
    assert workflow.ports == []
    assert workflow.output_mappings == {}


def test_workflow_with_agents():
    """测试带 Agent 的 Workflow"""
    workflow = Workflow(
        name="test_workflow",
        agents=[
            AgentInstance(name="agent1"),
            AgentInstance(name="agent2"),
        ],
    )

    assert len(workflow.agents) == 2
    assert workflow.agents[0].name == "agent1"
    assert workflow.agents[1].name == "agent2"


def test_workflow_with_connections():
    """测试带连接的 Workflow"""
    workflow = Workflow(
        name="test_workflow",
        agents=[
            AgentInstance(name="agent1"),
            AgentInstance(name="agent2"),
        ],
        connections=[
            Connection(source_agent="agent1", target_agents=["agent2"]),
        ],
    )

    assert len(workflow.connections) == 1
    assert workflow.connections[0].source_agent == "agent1"
    assert workflow.connections[0].target_agents == ["agent2"]


def test_workflow_with_component_reference():
    """测试引用组件的 Workflow"""
    workflow = Workflow(
        name="test_workflow",
        agents=[
            AgentInstance(name="reviewer", component="code-reviewer"),
        ],
    )

    assert workflow.agents[0].component == "code-reviewer"


def test_workflow_with_output_mappings():
    """测试带输出映射的 Workflow"""
    workflow = Workflow(
        name="test_workflow",
        agents=[AgentInstance(name="proc")],
        output_mappings={"result": "proc.output"},
    )

    assert workflow.output_mappings == {"result": "proc.output"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

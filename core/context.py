"""
GrassFlow WorkflowContext

只读数据传递机制：
- Agent 只能写自己的 key
- 可以读任何 Agent 的输出
- 调度器注入依赖数据到 Agent 输入
"""

from typing import Any, Dict, List, Optional
from .agent import Agent


class WorkflowContext:
    """工作流上下文，管理 Agent 之间的数据传递"""

    def __init__(self):
        self._data: Dict[str, Any] = {}

    def set(self, agent_id: str, data: Dict[str, Any]) -> None:
        """
        设置 Agent 的输出数据

        Args:
            agent_id: Agent 的唯一标识
            data: 输出数据
        """
        self._data[agent_id] = data

    def get(self, agent_id: str) -> Dict[str, Any]:
        """
        获取 Agent 的输出数据

        Args:
            agent_id: Agent 的唯一标识

        Returns:
            输出数据，如果不存在返回空字典
        """
        return self._data.get(agent_id, {})

    def get_dependency_data(self, agent: Agent, dependencies: List[str]) -> Dict[str, Any]:
        """
        获取 Agent 的依赖数据

        Args:
            agent: Agent 实例
            dependencies: 依赖的 Agent ID 列表

        Returns:
            包含依赖数据的字典
        """
        deps = {}
        for dep_id in dependencies:
            deps[dep_id] = self.get(dep_id)
        return {"_deps": deps}

    def has_agent_data(self, agent_id: str) -> bool:
        """检查 Agent 是否已有输出数据"""
        return agent_id in self._data

    def clear(self) -> None:
        """清空所有数据"""
        self._data.clear()

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return self._data.copy()

    def __repr__(self) -> str:
        return f"WorkflowContext(agents={list(self._data.keys())})"

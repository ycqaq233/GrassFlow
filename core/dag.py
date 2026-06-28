"""
GrassFlow DAG 引擎

实现功能：
- 拓扑排序
- 依赖解析
- 环检测
- 并行分组

使用 v2 类型: Workflow, Connection, AgentInstance
"""

from typing import List, Set, Dict
from collections import defaultdict, deque
from core.models import Workflow, Connection


class DAGError(Exception):
    """DAG 相关错误"""
    pass


class DAG:
    """有向无环图（DAG）引擎"""

    def __init__(self, workflow: Workflow):
        """
        初始化 DAG

        Args:
            workflow: 工作流定义 (v2)

        Raises:
            DAGError: 如果检测到环
        """
        self.workflow = workflow
        self._adjacency: Dict[str, List[str]] = defaultdict(list)
        self._reverse_adjacency: Dict[str, List[str]] = defaultdict(list)
        self._connections: Dict[str, List[Connection]] = defaultdict(list)
        self._incoming_connections: Dict[str, List[Connection]] = defaultdict(list)

        # 构建邻接表
        for conn in workflow.connections:
            for target in conn.target_agents:
                self._adjacency[conn.source_agent].append(target)
                self._reverse_adjacency[target].append(conn.source_agent)
            self._connections[conn.source_agent].append(conn)
            for target in conn.target_agents:
                self._incoming_connections[target].append(conn)

        # 检测环
        if self._has_cycle():
            raise DAGError("Cycle detected in workflow")

    def _has_cycle(self) -> bool:
        """检测是否有环（使用 DFS）"""
        nodes = {agent.name for agent in self.workflow.agents}

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self._adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in nodes:
            if node not in visited:
                if dfs(node):
                    return True

        return False

    def topological_sort(self) -> List[str]:
        """
        拓扑排序

        Returns:
            排序后的节点列表

        Raises:
            DAGError: 如果有环
        """
        nodes = {agent.name for agent in self.workflow.agents}

        if not nodes:
            return []

        # 计算入度
        in_degree: Dict[str, int] = {node: 0 for node in nodes}
        for node in nodes:
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] += 1

        # Kahn 算法
        queue = deque([node for node in nodes if in_degree[node] == 0])
        result: List[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)

            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(nodes):
            raise DAGError("Cycle detected in workflow")

        return result

    def get_parallel_groups(self) -> List[List[str]]:
        """
        获取并行执行组

        将节点按照拓扑层级分组，同一层级的节点可以并行执行

        Returns:
            并行执行组列表
        """
        nodes = {agent.name for agent in self.workflow.agents}

        if not nodes:
            return []

        in_degree: Dict[str, int] = {node: 0 for node in nodes}
        for node in nodes:
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] += 1

        queue = deque([node for node in nodes if in_degree[node] == 0])
        groups: List[List[str]] = []

        while queue:
            current_level = list(queue)
            queue.clear()
            groups.append(current_level)

            for node in current_level:
                for neighbor in self._adjacency.get(node, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        return groups

    def get_dependencies(self, node: str) -> List[str]:
        """获取节点的依赖（前驱节点）"""
        return list(self._reverse_adjacency.get(node, []))

    def get_dependents(self, node: str) -> List[str]:
        """获取依赖该节点的节点（后继节点）"""
        return list(self._adjacency.get(node, []))

    def is_ready(self, node: str, completed: Set[str]) -> bool:
        """
        判断节点是否就绪（所有依赖都已完成）

        Args:
            node: 节点名称
            completed: 已完成的节点集合

        Returns:
            如果节点就绪返回 True，否则返回 False
        """
        dependencies = self.get_dependencies(node)
        return all(dep in completed for dep in dependencies)

    def get_incoming_connections(self, node: str) -> List[Connection]:
        """
        获取节点的所有入边连接

        Args:
            node: 节点名称

        Returns:
            入边连接列表
        """
        return list(self._incoming_connections.get(node, []))

    def get_outgoing_connections(self, node: str) -> List[Connection]:
        """
        获取节点的所有出边连接

        Args:
            node: 节点名称

        Returns:
            出边连接列表
        """
        return list(self._connections.get(node, []))

    def get_roots(self) -> List[str]:
        """获取根节点（没有前驱的节点）"""
        nodes = {agent.name for agent in self.workflow.agents}
        return [node for node in nodes if not self._reverse_adjacency.get(node)]

    def get_leaves(self) -> List[str]:
        """获取叶子节点（没有后继的节点）"""
        nodes = {agent.name for agent in self.workflow.agents}
        return [node for node in nodes if not self._adjacency.get(node)]


# 辅助函数

def topological_sort(workflow: Workflow) -> List[str]:
    """对工作流进行拓扑排序"""
    dag = DAG(workflow)
    return dag.topological_sort()


def get_parallel_groups(workflow: Workflow) -> List[List[str]]:
    """获取工作流的并行执行组"""
    dag = DAG(workflow)
    return dag.get_parallel_groups()


def detect_cycle(workflow: Workflow) -> bool:
    """检测工作流是否有环"""
    try:
        DAG(workflow)
        return False
    except DAGError:
        return True

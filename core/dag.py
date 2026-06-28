"""
GrassFlow DAG 引擎

实现功能：
- 拓扑排序
- 依赖解析
- 环检测
- 并行分组
"""

from typing import List, Set, Dict
from collections import defaultdict, deque

try:
    from core.models import Workflow, Connection
except ImportError:
    from core.dsl_v2_ast import Workflow, Connection


class DAGError(Exception):
    """DAG 相关错误"""
    pass


class DAG:
    """有向无环图（DAG）引擎"""

    def __init__(self, workflow: Workflow):
        """
        初始化 DAG

        Args:
            workflow: 工作流定义

        Raises:
            DAGError: 如果检测到环
        """
        self.workflow = workflow
        self._adjacency: Dict[str, List[str]] = defaultdict(list)  # 邻接表
        self._reverse_adjacency: Dict[str, List[str]] = defaultdict(list)  # 反向邻接表
        self._connections: Dict[str, List[Connection]] = defaultdict(list)  # 连接详情

        # 从 workflow.connections 构建邻接表
        for conn in workflow.connections:
            for target in conn.target_agents:
                self._adjacency[conn.source_agent].append(target)
                self._reverse_adjacency[target].append(conn.source_agent)
                self._connections[conn.source_agent].append(conn)

        # 检测环
        if self._has_cycle():
            raise DAGError("Cycle detected in workflow")

    def _has_cycle(self) -> bool:
        """
        检测是否有环（使用 DFS）

        Returns:
            如果有环返回 True，否则返回 False
        """
        nodes = {agent.name for agent in self.workflow.agents}

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            """深度优先搜索检测环"""
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

        # BFS 拓扑排序（Kahn 算法）
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
            并行执行组列表，每组包含可以并行执行的节点
        """
        nodes = {agent.name for agent in self.workflow.agents}

        if not nodes:
            return []

        # 计算入度
        in_degree: Dict[str, int] = {node: 0 for node in nodes}
        for node in nodes:
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] += 1

        # BFS 层级分组
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
        """
        获取节点的依赖（前驱节点）

        Args:
            node: 节点名称

        Returns:
            依赖节点列表
        """
        return self._reverse_adjacency.get(node, [])

    def get_dependents(self, node: str) -> List[str]:
        """
        获取依赖该节点的节点（后继节点）

        Args:
            node: 节点名称

        Returns:
            被依赖节点列表
        """
        return self._adjacency.get(node, [])

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

    def get_condition_connections(self, node: str) -> List[Connection]:
        """
        获取节点的条件分支连接

        Args:
            node: 节点名称

        Returns:
            条件分支连接列表
        """
        return [
            conn for conn in self._connections.get(node, [])
            if conn.source_port and "condition" in conn.source_port.lower()
        ]

    def get_roots(self) -> List[str]:
        """
        获取根节点（没有前驱的节点）

        Returns:
            根节点列表
        """
        nodes = {agent.name for agent in self.workflow.agents}
        return [node for node in nodes if not self._reverse_adjacency.get(node)]

    def get_leaves(self) -> List[str]:
        """
        获取叶子节点（没有后继的节点）

        Returns:
            叶子节点列表
        """
        nodes = {agent.name for agent in self.workflow.agents}
        return [node for node in nodes if not self._adjacency.get(node)]

    def get_connections(self, node: str) -> List[Connection]:
        """
        获取节点的所有出连接

        Args:
            node: 节点名称

        Returns:
            出连接列表
        """
        return self._connections.get(node, [])

    def get_incoming_connections(self, node: str) -> List[Connection]:
        """
        获取节点的所有入连接

        Args:
            node: 节点名称

        Returns:
            入连接列表
        """
        result = []
        for conn in self.workflow.connections:
            if node in conn.target_agents:
                result.append(conn)
        return result

    # 向后兼容别名（旧调用方尚未迁移时使用）
    get_edges = get_connections
    get_incoming_edges = get_incoming_connections
    get_condition_edges = get_condition_connections


# 辅助函数

def topological_sort(workflow: Workflow) -> List[str]:
    """
    对工作流进行拓扑排序

    Args:
        workflow: 工作流定义

    Returns:
        排序后的节点列表

    Raises:
        DAGError: 如果有环
    """
    dag = DAG(workflow)
    return dag.topological_sort()


def get_parallel_groups(workflow: Workflow) -> List[List[str]]:
    """
    获取工作流的并行执行组

    Args:
        workflow: 工作流定义

    Returns:
        并行执行组列表

    Raises:
        DAGError: 如果有环
    """
    dag = DAG(workflow)
    return dag.get_parallel_groups()


def detect_cycle(workflow: Workflow) -> bool:
    """
    检测工作流是否有环

    Args:
        workflow: 工作流定义

    Returns:
        如果有环返回 True，否则返回 False
    """
    try:
        DAG(workflow)
        return False
    except DAGError:
        return True

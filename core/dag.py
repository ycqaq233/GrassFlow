"""
GrassFlow DAG 引擎

实现功能：
- 拓扑排序
- 依赖解析
- 环检测
- 并行分组

支持 v1 (Workflow+Edge) 和 v2 (Workflow+Connection) 两种类型系统。
"""

from typing import List, Set, Dict, Optional, Any
from collections import defaultdict, deque


class DAGError(Exception):
    """DAG 相关错误"""
    pass


def _is_v2_workflow(workflow: Any) -> bool:
    """判断是否为 v2 Workflow（使用 connections 属性）"""
    return hasattr(workflow, 'connections') and not hasattr(workflow, 'edges')


def _get_nodes(workflow: Any) -> Set[str]:
    """获取工作流中的所有节点名称（兼容 v1/v2）"""
    if _is_v2_workflow(workflow):
        # v2: agents 是 AgentInstance 列表
        return {agent.name for agent in workflow.agents}
    else:
        # v1: agents 是 AgentConfig 列表
        return {agent.name for agent in workflow.agents}


def _build_adjacency(workflow: Any):
    """从工作流构建邻接表（兼容 v1/v2）"""
    adjacency: Dict[str, List[str]] = defaultdict(list)
    reverse_adjacency: Dict[str, List[str]] = defaultdict(list)
    edges_map: Dict[str, List[Any]] = defaultdict(list)

    if _is_v2_workflow(workflow):
        # v2: connections
        for conn in workflow.connections:
            for target in conn.target_agents:
                adjacency[conn.source_agent].append(target)
                reverse_adjacency[target].append(conn.source_agent)
                edges_map[conn.source_agent].append(conn)
    else:
        # v1: edges
        for edge in workflow.edges:
            adjacency[edge.source].append(edge.target)
            reverse_adjacency[edge.target].append(edge.source)
            edges_map[edge.source].append(edge)

    return adjacency, reverse_adjacency, edges_map


class DAG:
    """有向无环图（DAG）引擎"""

    def __init__(self, workflow: Any):
        """
        初始化 DAG

        Args:
            workflow: 工作流定义（v1 Workflow 或 v2 Workflow）

        Raises:
            DAGError: 如果检测到环
        """
        self.workflow = workflow
        self._adjacency, self._reverse_adjacency, self._edges = _build_adjacency(workflow)

        # 检测环
        if self._has_cycle():
            raise DAGError("Cycle detected in workflow")

    def _has_cycle(self) -> bool:
        """
        检测是否有环（使用 DFS）

        Returns:
            如果有环返回 True，否则返回 False
        """
        nodes = _get_nodes(self.workflow)

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

        # 对每个未访问的节点进行 DFS
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
        nodes = _get_nodes(self.workflow)

        if not nodes:
            return []

        # 计算入度
        in_degree: Dict[str, int] = {node: 0 for node in nodes}
        for node in nodes:
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] += 1

        # 使用 BFS 进行拓扑排序（Kahn 算法）
        queue = deque([node for node in nodes if in_degree[node] == 0])
        result: List[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)

            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 检查是否所有节点都被访问
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
        nodes = _get_nodes(self.workflow)

        if not nodes:
            return []

        # 计算入度
        in_degree: Dict[str, int] = {node: 0 for node in nodes}
        for node in nodes:
            for neighbor in self._adjacency.get(node, []):
                in_degree[neighbor] += 1

        # 使用 BFS 进行层级分组
        queue = deque([node for node in nodes if in_degree[node] == 0])
        groups: List[List[str]] = []

        while queue:
            # 当前层级的所有节点
            current_level = list(queue)
            queue.clear()
            groups.append(current_level)

            # 处理当前层级的所有节点
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

    def get_condition_edges(self, node: str) -> List[Any]:
        """
        获取节点的条件分支边

        Args:
            node: 节点名称

        Returns:
            条件分支边列表（v1 Edge 或 v2 Connection）
        """
        edges = self._edges.get(node, [])
        if _is_v2_workflow(self.workflow):
            # v2: 条件分支通过 source_port 判断（如 "[urgent]"）
            return [
                edge for edge in edges
                if edge.source_port and edge.source_port.startswith("[")
            ]
        else:
            # v1: 通过 interaction_type 判断
            from core.models import InteractionType
            return [
                edge for edge in edges
                if edge.interaction_type == InteractionType.CONDITION
            ]

    def get_roots(self) -> List[str]:
        """
        获取根节点（没有前驱的节点）

        Returns:
            根节点列表
        """
        nodes = _get_nodes(self.workflow)
        return [node for node in nodes if not self._reverse_adjacency.get(node)]

    def get_leaves(self) -> List[str]:
        """
        获取叶子节点（没有后继的节点）

        Returns:
            叶子节点列表
        """
        nodes = _get_nodes(self.workflow)
        return [node for node in nodes if not self._adjacency.get(node)]

    def get_edges(self, node: str) -> List[Any]:
        """
        获取节点的所有出边

        Args:
            node: 节点名称

        Returns:
            出边列表
        """
        return self._edges.get(node, [])

    def get_incoming_edges(self, node: str) -> List[Any]:
        """
        获取节点的所有入边

        Args:
            node: 节点名称

        Returns:
            入边列表
        """
        result = []
        if _is_v2_workflow(self.workflow):
            for conn in self.workflow.connections:
                if node in conn.target_agents:
                    result.append(conn)
        else:
            for edge in self.workflow.edges:
                if edge.target == node:
                    result.append(edge)
        return result


# 辅助函数

def topological_sort(workflow: Any) -> List[str]:
    """
    对工作流进行拓扑排序

    Args:
        workflow: 工作流定义（v1 或 v2）

    Returns:
        排序后的节点列表

    Raises:
        DAGError: 如果有环
    """
    dag = DAG(workflow)
    return dag.topological_sort()


def get_parallel_groups(workflow: Any) -> List[List[str]]:
    """
    获取工作流的并行执行组

    Args:
        workflow: 工作流定义（v1 或 v2）

    Returns:
        并行执行组列表

    Raises:
        DAGError: 如果有环
    """
    dag = DAG(workflow)
    return dag.get_parallel_groups()


def detect_cycle(workflow: Any) -> bool:
    """
    检测工作流是否有环

    Args:
        workflow: 工作流定义（v1 或 v2）

    Returns:
        如果有环返回 True，否则返回 False
    """
    try:
        DAG(workflow)
        return False
    except DAGError:
        return True

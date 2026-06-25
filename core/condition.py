"""
GrassFlow ConditionAgent

条件分支 Agent，根据输出选择路由
"""

from typing import Dict, Any, List, Optional
from core.agent import Agent, AgentConfig


class ConditionAgent(Agent):
    """
    条件分支 Agent

    根据输入数据的某个字段值来决定路由。

    使用方式：
    1. 在 DSL 中定义：agent route { type: "condition", rules: ["urgent", "normal"] }
    2. 在执行流中使用：route -> [urgent] A, [normal] B

    ConditionAgent 的输出包含一个 "route" 字段，值为匹配的规则。
    调度器根据这个字段值来决定执行哪个分支。
    """

    def __init__(self, name: str, rules: List[str], route_field: str = "route"):
        """
        初始化 ConditionAgent

        Args:
            name: Agent 名称
            rules: 条件规则列表，如 ["urgent", "normal", "info"]
            route_field: 用于路由的字段名，默认为 "route"
        """
        config = AgentConfig(
            name=name,
            input_schema={},
            output_schema={"route": "string"},
        )
        super().__init__(config)
        self.rules = rules
        self.route_field = route_field

    async def run(self, input_data: dict) -> dict:
        """
        执行条件判断

        Args:
            input_data: 输入数据，应包含路由字段

        Returns:
            包含 route 字段的输出数据
        """
        # 从输入数据中获取路由值
        route_value = input_data.get(self.route_field)

        # 如果输入数据在 _deps 中，尝试从依赖数据中获取
        if route_value is None:
            deps = input_data.get("_deps", {})
            for dep_name, dep_data in deps.items():
                if isinstance(dep_data, dict):
                    route_value = dep_data.get(self.route_field)
                    if route_value is not None:
                        break

        # 验证路由值是否在规则列表中
        if route_value is None:
            raise ValueError(
                f"ConditionAgent '{self.name}': route field '{self.route_field}' not found in input"
            )

        if route_value not in self.rules:
            raise ValueError(
                f"ConditionAgent '{self.name}': route value '{route_value}' not in rules {self.rules}"
            )

        return {self.route_field: route_value}


class SimpleConditionAgent(Agent):
    """
    简单条件分支 Agent

    根据输入数据的某个字段值和预定义的映射来决定路由。

    使用方式：
    1. 定义映射：{"high": "urgent", "low": "normal"}
    2. 输入数据包含字段值
    3. 输出包含映射后的路由值
    """

    def __init__(
        self,
        name: str,
        field: str,
        mapping: Dict[str, str],
        default: Optional[str] = None,
    ):
        """
        初始化 SimpleConditionAgent

        Args:
            name: Agent 名称
            field: 用于判断的字段名
            mapping: 字段值到路由值的映射
            default: 默认路由值（当字段值不在映射中时使用）
        """
        config = AgentConfig(
            name=name,
            input_schema={},
            output_schema={"route": "string"},
        )
        super().__init__(config)
        self.field = field
        self.mapping = mapping
        self.default = default

    async def run(self, input_data: dict) -> dict:
        """
        执行条件判断

        Args:
            input_data: 输入数据，应包含判断字段

        Returns:
            包含 route 字段的输出数据
        """
        # 从输入数据中获取字段值
        field_value = input_data.get(self.field)

        # 如果输入数据在 _deps 中，尝试从依赖数据中获取
        if field_value is None:
            deps = input_data.get("_deps", {})
            for dep_name, dep_data in deps.items():
                if isinstance(dep_data, dict):
                    field_value = dep_data.get(self.field)
                    if field_value is not None:
                        break

        # 映射到路由值
        route_value = self.mapping.get(str(field_value), self.default)

        if route_value is None:
            raise ValueError(
                f"SimpleConditionAgent '{self.name}': "
                f"field value '{field_value}' not in mapping and no default set"
            )

        return {"route": route_value}

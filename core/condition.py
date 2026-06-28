"""
GrassFlow ConditionAgent

条件分支 Agent，根据输出选择路由

使用 v2 类型: Component (从 Component 构造)
"""

from typing import Dict, Any, List, Optional

from core.agent import Agent
from core.models import Component, ModelConfig


class ConditionAgent(Agent):
    """
    条件分支 Agent

    根据输入数据的某个字段值来决定路由。

    从 Component 构造:
        comp = Component(name="route", ...)
        agent = ConditionAgent(comp, rules=["urgent", "normal"])

    ConditionAgent 的输出包含一个 "route" 字段，值为匹配的规则。
    调度器根据这个字段值来决定执行哪个分支。
    """

    def __init__(self, component: Component, rules: List[str], route_field: str = "route"):
        """
        初始化 ConditionAgent

        Args:
            component: DSL v2 组件定义
            rules: 条件规则列表，如 ["urgent", "normal", "info"]
            route_field: 用于路由的字段名，默认为 "route"
        """
        super().__init__(component)
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
        route_value = input_data.get(self.route_field)

        if route_value is None:
            deps = input_data.get("_deps", {})
            for dep_name, dep_data in deps.items():
                if isinstance(dep_data, dict):
                    route_value = dep_data.get(self.route_field)
                    if route_value is not None:
                        break

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

    从 Component 构造:
        comp = Component(name="route", ...)
        agent = SimpleConditionAgent(comp, field="priority", mapping={"high": "urgent"})
    """

    def __init__(
        self,
        component: Component,
        field: str,
        mapping: Dict[str, str],
        default: Optional[str] = None,
    ):
        """
        初始化 SimpleConditionAgent

        Args:
            component: DSL v2 组件定义
            field: 用于判断的字段名
            mapping: 字段值到路由值的映射
            default: 默认路由值（当字段值不在映射中时使用）
        """
        super().__init__(component)
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
        field_value = input_data.get(self.field)

        if field_value is None:
            deps = input_data.get("_deps", {})
            for dep_name, dep_data in deps.items():
                if isinstance(dep_data, dict):
                    field_value = dep_data.get(self.field)
                    if field_value is not None:
                        break

        route_value = self.mapping.get(str(field_value), self.default)

        if route_value is None:
            raise ValueError(
                f"SimpleConditionAgent '{self.name}': "
                f"field value '{field_value}' not in mapping and no default set"
            )

        return {"route": route_value}


def make_condition_component(
    name: str,
    rules: Optional[List[str]] = None,
    model: str = "gpt-4",
    on_fail: str = "stop",
    retry_count: int = 3,
) -> Component:
    """辅助函数：从规则列表创建条件路由 Component"""
    return Component(
        name=name,
        model=ModelConfig(default=model),
        on_fail=on_fail,
        retry_count=retry_count,
    )

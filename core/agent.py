"""
GrassFlow Agent 基类 + Schema 系统

所有 Agent 的基类，提供：
- 从 Component 推导 Schema
- 失败策略配置
- 统一的执行接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import jsonschema

from .models import Component, Port, ModelConfig


# ---------------------------------------------------------------------------
# 端口类型到 JSON Schema 的映射
# ---------------------------------------------------------------------------

PORT_TYPE_TO_JSON_SCHEMA: Dict[str, Dict[str, str]] = {
    "string": {"type": "string"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "object": {"type": "object"},
    "array": {"type": "array"},
}


def ports_to_schema(ports: List[Port], direction: str) -> Dict[str, Any]:
    """将端口列表转换为 JSON Schema。

    Args:
        ports: 端口定义列表
        direction: "input" 或 "output"

    Returns:
        JSON Schema 字典，无端口时返回空字典
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for p in ports:
        if p.direction != direction:
            continue
        properties[p.name] = PORT_TYPE_TO_JSON_SCHEMA.get(
            p.type, {"type": "object"}
        )
        required.append(p.name)

    if not properties:
        return {}
    return {"type": "object", "properties": properties, "required": required}


# ---------------------------------------------------------------------------
# Agent 基类
# ---------------------------------------------------------------------------


class Agent(ABC):
    """所有 Agent 的基类。

    接受一个 Component 定义，从 Component 的 ports 推导 input_schema / output_schema。
    """

    def __init__(self, component: Component):
        self._component = component
        self.name = component.name
        self.on_fail = component.on_fail
        self.retry_count = component.retry_count

    @property
    def component(self) -> Component:
        """返回此 Agent 关联的 Component"""
        return self._component

    @property
    def input_schema(self) -> Dict[str, Any]:
        """从 Component 的 input 端口推导的 JSON Schema"""
        return ports_to_schema(self._component.ports, direction="input")

    @property
    def output_schema(self) -> Dict[str, Any]:
        """从 Component 的 output 端口推导的 JSON Schema"""
        return ports_to_schema(self._component.ports, direction="output")

    def validate_input(self, data: Dict[str, Any]) -> bool:
        """校验输入数据是否符合 Schema"""
        schema = self.input_schema
        if not schema:
            return True
        # 如果没有输入数据，跳过校验（根节点可能没有输入）
        if not data:
            return True
        try:
            jsonschema.validate(instance=data, schema=schema)
            return True
        except jsonschema.ValidationError as e:
            raise ValueError(f"Input validation failed: {e.message}")

    def validate_output(self, data: Dict[str, Any]) -> bool:
        """校验输出数据是否符合 Schema"""
        schema = self.output_schema
        if not schema:
            return True
        try:
            jsonschema.validate(instance=data, schema=schema)
            return True
        except jsonschema.ValidationError as e:
            raise ValueError(f"Output validation failed: {e.message}")

    @abstractmethod
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Agent 逻辑

        Args:
            input_data: 输入数据，包含依赖 Agent 的输出

        Returns:
            输出数据
        """
        raise NotImplementedError

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Agent（带校验和重试）

        Args:
            input_data: 输入数据

        Returns:
            输出数据
        """
        # 校验输入
        self.validate_input(input_data)

        # 执行（带重试）
        last_error = None
        for attempt in range(self.retry_count):
            try:
                result = await self.run(input_data)
                # 校验输出
                self.validate_output(result)
                return result
            except Exception as e:
                last_error = e
                if self.on_fail == "stop":
                    raise
                elif self.on_fail == "skip":
                    return {}
                elif self.on_fail == "retry":
                    if attempt < self.retry_count - 1:
                        continue
                    raise

        raise last_error

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        model_default = self._component.model.default if self._component.model else "gpt-4"
        return {
            "name": self.name,
            "model": model_default,
            "prompt": self._component.system_prompt or "",
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "on_fail": self.on_fail,
            "retry_count": self.retry_count,
        }

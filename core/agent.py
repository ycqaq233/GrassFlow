"""
GrassFlow Agent 基类 + Schema 系统

所有 Agent 的基类，提供：
- Schema 定义和校验
- 失败策略配置
- 统一的执行接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator
import jsonschema


class AgentConfig(BaseModel):
    """Agent 配置"""
    name: str
    model: str = "gpt-4"
    prompt: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    on_fail: str = "stop"  # stop / skip / retry
    retry_count: int = 3
    timeout: Optional[int] = None  # 秒

    @field_validator("on_fail")
    @classmethod
    def validate_on_fail(cls, v: str) -> str:
        if v not in ("stop", "skip", "retry"):
            raise ValueError("on_fail must be one of: stop, skip, retry")
        return v


class Agent(ABC):
    """所有 Agent 的基类"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.name
        self.input_schema = config.input_schema
        self.output_schema = config.output_schema
        self.on_fail = config.on_fail
        self.retry_count = config.retry_count

    def validate_input(self, data: Dict[str, Any]) -> bool:
        """校验输入数据是否符合 Schema"""
        if not self.input_schema:
            return True
        try:
            jsonschema.validate(instance=data, schema=self.input_schema)
            return True
        except jsonschema.ValidationError as e:
            raise ValueError(f"Input validation failed: {e.message}")

    def validate_output(self, data: Dict[str, Any]) -> bool:
        """校验输出数据是否符合 Schema"""
        if not self.output_schema:
            return True
        try:
            jsonschema.validate(instance=data, schema=self.output_schema)
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
        return {
            "name": self.name,
            "model": self.config.model,
            "prompt": self.config.prompt,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "on_fail": self.on_fail,
            "retry_count": self.retry_count,
        }

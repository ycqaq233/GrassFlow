"""
GrassFlow 统一工具接口

参考 opencode 的工具设计，提供：
- Tool 基类：定义工具的标准接口
- ToolContext：工具执行上下文
- ToolResult：工具执行结果
- ToolRegistry：工具注册表
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Union
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """
    工具执行上下文

    参考 opencode 的 Tool.Context，提供工具执行所需的信息和能力
    """
    # 工作目录
    cwd: str
    # 会话 ID（可选）
    session_id: Optional[str] = None
    # 消息 ID（可选）
    message_id: Optional[str] = None
    # Agent 名称（可选）
    agent: Optional[str] = None
    # 超时时间（秒）
    timeout: int = 60
    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_absolute_path(self, path: str) -> str:
        """将相对路径转换为绝对路径"""
        p = Path(path)
        if p.is_absolute():
            return str(p)
        return str(Path(self.cwd) / p)


@dataclass
class ToolResult:
    """
    工具执行结果

    参考 opencode 的 ExecuteResult，统一工具返回格式
    """
    # 输出内容
    output: str
    # 标题（用于显示）
    title: str = ""
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 是否被截断
    truncated: bool = False
    # 附件列表（可选）
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "output": self.output,
            "title": self.title,
            "metadata": self.metadata,
            "truncated": self.truncated,
        }
        if self.attachments:
            result["attachments"] = self.attachments
        return result


class Tool(ABC):
    """
    工具基类

    参考 opencode 的 Tool.Def，定义工具的标准接口
    所有内置工具都应继承此类
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """工具唯一标识符"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（供 LLM 理解）"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        工具参数的 JSON Schema 定义

        示例:
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令"
                }
            },
            "required": ["command"]
        }
        """
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """
        执行工具

        Args:
            params: 工具参数（已校验）
            ctx: 执行上下文

        Returns:
            ToolResult: 执行结果

        Raises:
            ValueError: 参数错误
            RuntimeError: 执行错误
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        校验工具参数

        Args:
            params: 原始参数

        Returns:
            校验后的参数

        Raises:
            ValueError: 参数校验失败
        """
        required = self.parameters.get("required", [])
        properties = self.parameters.get("properties", {})

        # 检查必需参数
        for key in required:
            if key not in params:
                raise ValueError(f"Missing required parameter: {key}")

        # 类型检查（简单实现）
        for key, value in params.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    raise ValueError(f"Parameter '{key}' must be a string")
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    raise ValueError(f"Parameter '{key}' must be a number")
                elif expected_type == "integer" and not isinstance(value, int):
                    raise ValueError(f"Parameter '{key}' must be an integer")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    raise ValueError(f"Parameter '{key}' must be a boolean")
                elif expected_type == "array" and not isinstance(value, list):
                    raise ValueError(f"Parameter '{key}' must be an array")
                elif expected_type == "object" and not isinstance(value, dict):
                    raise ValueError(f"Parameter '{key}' must be an object")

        return params


class ToolRegistry:
    """
    工具注册表

    参考 opencode 的 ToolRegistry，管理所有可用工具
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具"""
        if tool.id in self._tools:
            logger.warning(f"Tool '{tool.id}' already registered, overwriting")
        self._tools[tool.id] = tool
        logger.debug(f"Registered tool: {tool.id}")

    def get(self, tool_id: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(tool_id)

    def list_tools(self) -> List[Tool]:
        """列出所有工具"""
        return list(self._tools.values())

    def list_ids(self) -> List[str]:
        """列出所有工具 ID"""
        return list(self._tools.keys())

    def to_schema_list(self) -> List[Dict[str, Any]]:
        """
        导出为 Schema 列表（供 LLM 使用）

        返回格式:
        [
            {
                "id": "shell",
                "description": "执行 shell 命令",
                "parameters": { ... }
            },
            ...
        ]
        """
        return [
            {
                "id": tool.id,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self,
        tool_id: str,
        params: Dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        """
        执行工具

        Args:
            tool_id: 工具 ID
            params: 工具参数
            ctx: 执行上下文

        Returns:
            ToolResult: 执行结果

        Raises:
            ValueError: 工具不存在或参数错误
        """
        tool = self.get(tool_id)
        if not tool:
            raise ValueError(f"Tool not found: {tool_id}")

        # 校验参数
        validated_params = tool.validate_params(params)

        # 执行工具
        try:
            result = await tool.execute(validated_params, ctx)
            return result
        except Exception as e:
            logger.error(f"Tool '{tool_id}' execution failed: {e}")
            raise


# 全局工具注册表实例
_global_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """获取全局工具注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def register_builtin_tools() -> ToolRegistry:
    """
    注册所有内置工具

    Returns:
        ToolRegistry: 注册了所有内置工具的注册表
    """
    registry = get_registry()

    # 延迟导入避免循环依赖
    from .shell import ShellTool
    from .read import ReadTool
    from .write import WriteTool
    from .glob import GlobTool
    from .grep import GrepTool
    from .webfetch import WebFetchTool

    registry.register(ShellTool())
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(WebFetchTool())

    logger.info(f"Registered {len(registry.list_tools())} builtin tools")
    return registry

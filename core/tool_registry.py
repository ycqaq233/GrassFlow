"""
GrassFlow 统一工具注册表

参考 opencode 的工具注册表设计，为 GrassFlow 提供统一的工具管理接口。
支持三种工具来源：
- 内置工具 (Builtin)：框架自带的核心工具
- 插件工具 (Plugin)：从外部文件/目录动态加载的工具
- MCP 工具 (MCP)：通过 MCP 协议接入的外部工具服务

设计原则：
- 所有工具共享统一的 ToolDef 接口
- 支持自注册模式（装饰器注册）
- JSON Schema 驱动的参数校验
- 统一的调用入口和错误处理
"""

from __future__ import annotations

import asyncio
import logging
import re as _re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Type,
    Union,
)

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ANSI 转义码剥离（用于清理 MCP 工具返回的终端彩色输出）
_ANSI_ESCAPE_RE = _re.compile(
    r"\x1b\[\??[0-9;]*[A-Za-z]"    # CSI 序列（含私有模式 ?2004h 等）
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC 序列
    r"|\x1b[()][A-Za-z]"           # 字符集选择序列
    r"|\x1b[>=]"                   # 应用/普通键盘模式
    r"|\r"                          # 回车
)


def _strip_ansi(text: str) -> str:
    """剥离 ANSI 转义码和回车符，保留纯文本内容。"""
    return _ANSI_ESCAPE_RE.sub("", text)


# ---------------------------------------------------------------------------
#  工具来源类型
# ---------------------------------------------------------------------------


class ToolSource(str, Enum):
    """工具来源"""

    BUILTIN = "builtin"  # 内置工具
    PLUGIN = "plugin"  # 插件工具（本地文件/目录加载）
    MCP = "mcp"  # MCP 协议接入的工具


# ---------------------------------------------------------------------------
#  工具权限（ask / allow / deny 三级）
# ---------------------------------------------------------------------------


class ToolPermission(str, Enum):
    """工具调用权限"""

    ALLOW = "allow"  # 直接允许
    ASK = "ask"  # 调用前询问用户
    DENY = "deny"  # 禁止调用


# ---------------------------------------------------------------------------
#  执行结果
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """工具执行结果"""

    output: str  # 文本输出
    title: str = ""  # 结果标题
    metadata: Dict[str, Any] = field(default_factory=dict)  # 附加元数据
    attachments: Optional[List[Dict[str, Any]]] = None  # 附件（文件、图片等）
    is_error: bool = False  # 是否为错误结果

    @staticmethod
    def success(output: str, **kwargs: Any) -> "ToolResult":
        return ToolResult(output=output, **kwargs)

    @staticmethod
    def error(message: str, **kwargs: Any) -> "ToolResult":
        return ToolResult(output=message, is_error=True, **kwargs)


# ---------------------------------------------------------------------------
#  执行上下文
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """工具执行上下文

    由调度器在调用工具时填充，向工具提供运行时信息。
    """

    session_id: str = ""  # 工作流执行会话 ID
    agent_name: str = ""  # 当前执行的 Agent 名称
    message_id: str = ""  # 消息 ID（用于追溯）
    call_id: str = ""  # 本次调用 ID
    abort_signal: Optional[asyncio.Event] = None  # 中止信号
    extra: Dict[str, Any] = field(default_factory=dict)  # 扩展字段
    _permission_requests: List[Dict[str, Any]] = field(
        default_factory=list, repr=False
    )

    def request_permission(
        self,
        permission: str,
        patterns: List[str],
        always: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录权限请求（实际决策由上层控制）"""
        self._permission_requests.append(
            {
                "permission": permission,
                "patterns": patterns,
                "always": always or [],
                "metadata": metadata or {},
            }
        )

    def is_aborted(self) -> bool:
        """检查是否被中止"""
        return self.abort_signal is not None and self.abort_signal.is_set()


# ---------------------------------------------------------------------------
#  工具参数 Schema
# ---------------------------------------------------------------------------


class ParameterSchema(BaseModel):
    """工具参数的 JSON Schema 描述"""

    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)
    description: str = ""

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
#  工具定义 (ToolDef)
# ---------------------------------------------------------------------------


class ToolDef(BaseModel):
    """工具定义 —— 注册表中每个工具的完整描述

    这是工具注册表的核心数据结构，包含工具的元信息、参数描述、
    以及实际的执行逻辑。
    """

    id: str  # 唯一标识，如 "read", "mcp_github.create_issue"
    description: str  # 工具描述，供 LLM 理解工具用途
    parameters: Dict[str, Any] = Field(default_factory=dict)  # JSON Schema 格式的参数定义
    source: ToolSource = ToolSource.BUILTIN  # 工具来源
    permission: ToolPermission = ToolPermission.ALLOW  # 默认权限
    tags: List[str] = Field(default_factory=list)  # 标签，用于分类/过滤
    enabled: bool = True  # 是否启用

    # ---- 运行时字段（不参与序列化） ----
    execute_fn: Optional[Callable[..., Awaitable[ToolResult]]] = Field(
        default=None, exclude=True, repr=False
    )

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("tool id must not be empty")
        # 允许字母、数字、下划线、点、连字符
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"tool id contains invalid characters: {invalid}")
        return v

    def parameter_schema(self) -> Dict[str, Any]:
        """返回完整的 JSON Schema（兼容 LLM tool calling 格式）"""
        return {
            "type": "object",
            "properties": self.parameters.get("properties", {}),
            "required": self.parameters.get("required", []),
        }

    def validate_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """校验并规范化参数

        使用 jsonschema 库进行校验；如果项目中已有 pydantic 也可以
        选择 pydantic 校验。这里使用轻量的 jsonschema。
        """
        try:
            import jsonschema

            schema = self.parameter_schema()
            if schema.get("properties"):
                jsonschema.validate(instance=args, schema=schema)
            return args
        except ImportError:
            # jsonschema 不可用时跳过校验
            logger.debug("jsonschema not installed, skipping parameter validation")
            return args
        except jsonschema.ValidationError as e:
            raise ToolInvalidArgumentsError(self.id, str(e)) from e

    async def execute(self, args: Dict[str, Any], ctx: Optional[ToolContext] = None) -> ToolResult:
        """执行工具

        Args:
            args: 工具参数
            ctx: 执行上下文

        Returns:
            ToolResult 执行结果

        Raises:
            ToolNotFoundError: 工具未注册执行函数
            ToolInvalidArgumentsError: 参数校验失败
            ToolExecutionError: 执行过程异常
        """
        if self.execute_fn is None:
            raise ToolNotFoundError(f"Tool '{self.id}' has no execute function registered")

        ctx = ctx or ToolContext()

        # 检查中止信号
        if ctx.is_aborted():
            return ToolResult.error("Tool execution aborted")

        # 校验参数
        validated_args = self.validate_args(args)

        # 记录执行开始
        start_time = time.monotonic()
        logger.debug("Executing tool '%s' with args: %s", self.id, _sanitize_args(validated_args))

        try:
            result = await self.execute_fn(validated_args, ctx)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            result.metadata.setdefault("tool_id", self.id)
            result.metadata.setdefault("elapsed_ms", elapsed_ms)
            logger.debug("Tool '%s' completed in %dms", self.id, elapsed_ms)
            return result
        except GrassFlowToolError:
            raise
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error("Tool '%s' failed after %dms: %s", self.id, elapsed_ms, e)
            raise ToolExecutionError(self.id, str(e)) from e

    def to_info_dict(self) -> Dict[str, Any]:
        """导出为供 LLM 使用的工具信息字典"""
        return {
            "id": self.id,
            "description": self.description,
            "parameters": self.parameter_schema(),
        }


# ---------------------------------------------------------------------------
#  工具错误体系
# ---------------------------------------------------------------------------


class GrassFlowToolError(Exception):
    """工具相关错误基类"""

    pass


class ToolNotFoundError(GrassFlowToolError):
    """请求的工具不存在"""

    def __init__(self, tool_id: str):
        self.tool_id = tool_id
        super().__init__(f"Tool not found: {tool_id}")


class ToolInvalidArgumentsError(GrassFlowToolError):
    """工具参数校验失败"""

    def __init__(self, tool_id: str, detail: str):
        self.tool_id = tool_id
        self.detail = detail
        super().__init__(
            f"Tool '{tool_id}' was called with invalid arguments: {detail}. "
            f"Please rewrite the input to satisfy the expected schema."
        )


class ToolExecutionError(GrassFlowToolError):
    """工具执行过程异常"""

    def __init__(self, tool_id: str, detail: str):
        self.tool_id = tool_id
        self.detail = detail
        super().__init__(f"Tool '{tool_id}' execution failed: {detail}")


class ToolRegistrationError(GrassFlowToolError):
    """工具注册失败"""

    pass


# ---------------------------------------------------------------------------
#  工具定义工厂（装饰器 + 手动注册）
# ---------------------------------------------------------------------------


# 全局装饰器注册表，供 @register_tool 使用
_DECORATOR_REGISTRY: Dict[str, ToolDef] = {}


def register_tool(
    tool_id: str,
    description: str,
    parameters: Optional[Dict[str, Any]] = None,
    source: ToolSource = ToolSource.BUILTIN,
    permission: ToolPermission = ToolPermission.ALLOW,
    tags: Optional[List[str]] = None,
    auto_register: bool = True,
) -> Callable:
    """装饰器：将函数注册为工具

    用法示例::

        @register_tool(
            "read_file",
            description="Read file contents",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"]
            }
        )
        async def read_file(args: dict, ctx: ToolContext) -> ToolResult:
            ...

    Args:
        tool_id: 工具唯一标识
        description: 工具描述
        parameters: JSON Schema 格式的参数定义
        source: 工具来源
        permission: 默认权限
        tags: 标签列表
        auto_register: 是否自动注册到全局装饰器注册表
    """

    def decorator(func: Callable[..., Awaitable[ToolResult]]) -> Callable[..., Awaitable[ToolResult]]:
        tool_def = ToolDef(
            id=tool_id,
            description=description,
            parameters=parameters or {},
            source=source,
            permission=permission,
            tags=tags or [],
        )
        tool_def.execute_fn = func

        if auto_register:
            _DECORATOR_REGISTRY[tool_id] = tool_def

        # 在函数上附加 tool_def 元信息，便于后续检索
        func._tool_def = tool_def  # type: ignore[attr-defined]
        return func

    return decorator


# ---------------------------------------------------------------------------
#  工具基类（面向对象的工具定义方式）
# ---------------------------------------------------------------------------


class BaseTool(ABC):
    """工具基类 —— 通过继承定义工具

    用法示例::

        class ReadFileTool(BaseTool):
            @property
            def id(self) -> str:
                return "read_file"

            @property
            def description(self) -> str:
                return "Read the contents of a file"

            @property
            def parameters(self) -> dict:
                return {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"}
                    },
                    "required": ["path"]
                }

            async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
                path = args["path"]
                ...
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """工具唯一标识"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        ...

    @property
    def parameters(self) -> Dict[str, Any]:
        """JSON Schema 参数定义（子类可覆盖）"""
        return {}

    @property
    def source(self) -> ToolSource:
        """工具来源（子类可覆盖）"""
        return ToolSource.BUILTIN

    @property
    def permission(self) -> ToolPermission:
        """默认权限（子类可覆盖）"""
        return ToolPermission.ALLOW

    @property
    def tags(self) -> List[str]:
        """标签（子类可覆盖）"""
        return []

    @abstractmethod
    async def run(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """执行逻辑（子类必须实现）"""
        ...

    def to_tool_def(self) -> ToolDef:
        """转换为 ToolDef 并绑定执行函数"""
        tool_def = ToolDef(
            id=self.id,
            description=self.description,
            parameters=self.parameters,
            source=self.source,
            permission=self.permission,
            tags=self.tags,
        )
        tool_def.execute_fn = self.run
        return tool_def


# ---------------------------------------------------------------------------
#  MCP 工具适配器
# ---------------------------------------------------------------------------


class MCPToolAdapter:
    """MCP 工具适配器

    将外部 MCP 工具服务暴露的工具包装为 ToolDef，统一纳入注册表管理。

    MCP (Model Context Protocol) 工具通常通过 stdio 或 HTTP 与外部进程通信，
    本适配器只负责「描述」和「转发调用」，实际通信由 MCP 客户端实现。
    """

    def __init__(
        self,
        server_name: str,
        tool_id: str,
        description: str,
        parameters: Dict[str, Any],
        mcp_client: Any,
        permission: ToolPermission = ToolPermission.ALLOW,
        tags: Optional[List[str]] = None,
    ):
        """
        Args:
            server_name: MCP 服务器名称（如 "github", "sonarqube"）
            tool_id: 工具 ID。如果已经包含 mcp_ 前缀（如 mcp_server_tool），
                     则直接用作注册 ID；否则以 mcp_{server}_{tool_id} 格式注册。
            description: 工具描述
            parameters: 参数 JSON Schema
            mcp_client: MCP 客户端实例，需实现 call_tool(tool_id, args) -> result
            permission: 默认权限
            tags: 标签
        """
        self.server_name = server_name
        self.tool_id = tool_id
        self.description = description
        self.parameters = parameters
        self.mcp_client = mcp_client
        self.permission = permission
        self.tags = tags or []
        # Avoid double-prefixing: if tool_id already starts with "mcp_", use it
        # directly as the registry ID (this is the case when called from
        # MCPManager.register_tools_to_registry which passes qualified names).
        if tool_id.startswith("mcp_"):
            self._full_id = tool_id
        else:
            self._full_id = f"mcp_{server_name}.{tool_id}"

    def to_tool_def(self) -> ToolDef:
        """转换为 ToolDef"""
        tool_def = ToolDef(
            id=self._full_id,
            description=f"[MCP:{self.server_name}] {self.description}",
            parameters=self.parameters,
            source=ToolSource.MCP,
            permission=self.permission,
            tags=[f"mcp:{self.server_name}", *self.tags],
        )
        tool_def.execute_fn = self._call_mcp
        return tool_def

    async def _call_mcp(
        self, args: Dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        """通过 MCP 客户端调用远程工具

        使用同步桥接 (call_tool_sync) 将工具调用调度到 MCP 后台事件循环，
        避免跨事件循环调用导致的挂起问题。
        """
        try:
            # 优先使用异步桥接 — 将 session.call_tool() 调度到 MCP 事件循环
            # call_tool_async 用 asyncio.wrap_future 避免阻塞主线程事件循环
            if hasattr(self.mcp_client, 'call_tool_async'):
                raw_result = await self.mcp_client.call_tool_async(
                    self.tool_id, args,
                )
            elif hasattr(self.mcp_client, 'call_tool_sync'):
                raw_result = self.mcp_client.call_tool_sync(
                    self.tool_id, args,
                )
            else:
                raw_result = await self.mcp_client.call_tool(self.tool_id, args)

            # MCP 返回格式通常为 {"content": [{"type": "text", "text": "..."}]}
            if isinstance(raw_result, dict) and "content" in raw_result:
                parts = raw_result["content"]
                text_parts = [
                    _strip_ansi(p.get("text", ""))
                    for p in parts if p.get("type") == "text"
                ]
                output = "\n".join(text_parts)
                is_error = raw_result.get("isError", False)
                return ToolResult(output=output, is_error=is_error)
            elif isinstance(raw_result, str):
                return ToolResult(output=_strip_ansi(raw_result))
            else:
                return ToolResult(output=_strip_ansi(str(raw_result)))
        except Exception as e:
            return ToolResult.error(f"MCP tool '{self._full_id}' call failed: {e}")


# ---------------------------------------------------------------------------
#  工具注册表 (ToolRegistry)
# ---------------------------------------------------------------------------


class ToolRegistry:
    """统一工具注册表

    管理所有工具的注册、查询和调用。支持：
    - 内置工具（BuiltinTool 的子类或 @register_tool 装饰的函数）
    - 插件工具（从指定目录动态加载）
    - MCP 工具（通过 MCPToolAdapter 包装）

    使用方式::

        registry = ToolRegistry()

        # 方式1：注册工具类实例
        registry.register(ReadFileTool())

        # 方式2：注册 ToolDef
        registry.register_tool_def(tool_def)

        # 方式3：从装饰器注册表批量导入
        registry.register_from_decorators()

        # 方式4：注册 MCP 工具
        registry.register_mcp_tools("github", mcp_client)

        # 调用工具
        result = await registry.invoke("read_file", {"path": "/tmp/test.txt"})
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}

    # ---- 注册 ----

    def register(self, tool: Union[BaseTool, ToolDef]) -> None:
        """注册工具（自动识别 BaseTool 实例或 ToolDef）

        Args:
            tool: BaseTool 子类实例 或 ToolDef

        Raises:
            ToolRegistrationError: tool_id 已存在且不是同一个对象
        """
        if isinstance(tool, BaseTool):
            tool_def = tool.to_tool_def()
        elif isinstance(tool, ToolDef):
            tool_def = tool
        else:
            raise ToolRegistrationError(
                f"Expected BaseTool or ToolDef, got {type(tool).__name__}"
            )

        self._do_register(tool_def)

    def register_tool_def(self, tool_def: ToolDef) -> None:
        """直接注册 ToolDef"""
        self._do_register(tool_def)

    def register_function(
        self,
        func: Callable[..., Awaitable[ToolResult]],
        tool_id: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
        source: ToolSource = ToolSource.BUILTIN,
        permission: ToolPermission = ToolPermission.ALLOW,
        tags: Optional[List[str]] = None,
    ) -> None:
        """注册函数为工具（不使用装饰器时的手动注册方式）"""
        tool_def = ToolDef(
            id=tool_id,
            description=description,
            parameters=parameters or {},
            source=source,
            permission=permission,
            tags=tags or [],
        )
        tool_def.execute_fn = func
        self._do_register(tool_def)

    def register_from_decorators(self) -> int:
        """从全局装饰器注册表批量导入工具

        Returns:
            导入的工具数量
        """
        count = 0
        for tool_id, tool_def in _DECORATOR_REGISTRY.items():
            if tool_id not in self._tools:
                self._do_register(tool_def)
                count += 1
        return count

    def register_mcp_tools(
        self,
        server_name: str,
        mcp_client: Any,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
        permission: ToolPermission = ToolPermission.ALLOW,
    ) -> List[str]:
        """注册 MCP 服务器的所有工具

        Args:
            server_name: MCP 服务器名称
            mcp_client: MCP 客户端实例
            tool_definitions: MCP 工具定义列表（由 MCP list_tools 返回）。
                每项至少包含 {id, description, inputSchema}。
                若为 None，尝试从 mcp_client.list_tools() 获取。
            permission: 默认权限

        Returns:
            注册的工具 ID 列表
        """
        if tool_definitions is None:
            # 尝试从客户端获取工具列表
            if hasattr(mcp_client, "list_tools"):
                tool_definitions = asyncio.get_event_loop().run_until_complete(
                    mcp_client.list_tools()
                ) if not asyncio.get_event_loop().is_running() else []
            else:
                logger.warning(
                    "MCP client '%s' has no list_tools method and no tool_definitions provided",
                    server_name,
                )
                return []

        registered_ids: List[str] = []
        for tool_info in tool_definitions:
            adapter = MCPToolAdapter(
                server_name=server_name,
                tool_id=tool_info.get("id") or tool_info.get("name", ""),
                description=tool_info.get("description", ""),
                parameters=tool_info.get("inputSchema", {}),
                mcp_client=mcp_client,
                permission=permission,
            )
            tool_def = adapter.to_tool_def()
            try:
                self._do_register(tool_def)
                registered_ids.append(tool_def.id)
            except ToolRegistrationError as e:
                logger.warning("Skipping MCP tool: %s", e)

        logger.info(
            "Registered %d MCP tools from server '%s'", len(registered_ids), server_name
        )
        return registered_ids

    async def load_plugins_from_directory(self, directory: Union[str, Path]) -> int:
        """从目录加载插件工具

        扫描目录下的 .py 文件，提取其中使用 @register_tool 装饰的函数
        以及 BaseTool 子类并注册。

        Args:
            directory: 插件目录路径

        Returns:
            加载的工具数量
        """
        import importlib.util

        directory = Path(directory)
        if not directory.is_dir():
            logger.warning("Plugin directory not found: %s", directory)
            return 0

        count = 0
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            module_name = f"grassflow_plugin_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 提取 @register_tool 装饰的函数
                for attr_name in dir(module):
                    attr = getattr(module, attr_name, None)
                    if attr is not None and hasattr(attr, "_tool_def"):
                        tool_def = attr._tool_def
                        if tool_def.id not in self._tools:
                            self._do_register(tool_def)
                            count += 1

                # 提取 BaseTool 子类的实例
                for attr_name in dir(module):
                    attr = getattr(module, attr_name, None)
                    if (
                        attr is not None
                        and isinstance(attr, type)
                        and issubclass(attr, BaseTool)
                        and attr is not BaseTool
                    ):
                        try:
                            instance = attr()
                            if instance.id not in self._tools:
                                self.register(instance)
                                count += 1
                        except Exception as e:
                            logger.warning(
                                "Failed to instantiate tool class '%s' from %s: %s",
                                attr_name,
                                py_file.name,
                                e,
                            )

            except Exception as e:
                logger.error("Failed to load plugin file %s: %s", py_file.name, e)

        logger.info("Loaded %d tools from plugin directory: %s", count, directory)
        return count

    # ---- 注销 ----

    def unregister(self, tool_id: str) -> bool:
        """注销工具

        Args:
            tool_id: 工具 ID

        Returns:
            是否成功注销
        """
        if tool_id in self._tools:
            del self._tools[tool_id]
            logger.debug("Unregistered tool: %s", tool_id)
            return True
        return False

    def clear(self) -> int:
        """清空所有注册的工具

        Returns:
            被清空的工具数量
        """
        count = len(self._tools)
        self._tools.clear()
        return count

    # ---- 查询 ----

    def get(self, tool_id: str) -> Optional[ToolDef]:
        """根据 ID 获取工具定义"""
        return self._tools.get(tool_id)

    def has(self, tool_id: str) -> bool:
        """检查工具是否已注册"""
        return tool_id in self._tools

    def ids(self) -> List[str]:
        """返回所有工具 ID（按注册顺序）"""
        return list(self._tools.keys())

    def all(self) -> List[ToolDef]:
        """返回所有工具定义"""
        return list(self._tools.values())

    def filter_by_source(self, source: ToolSource) -> List[ToolDef]:
        """按来源过滤工具"""
        return [t for t in self._tools.values() if t.source == source]

    def filter_by_tag(self, tag: str) -> List[ToolDef]:
        """按标签过滤工具"""
        return [t for t in self._tools.values() if tag in t.tags]

    def filter_by_permission(self, permission: ToolPermission) -> List[ToolDef]:
        """按权限过滤工具"""
        return [t for t in self._tools.values() if t.permission == permission]

    def enabled_tools(self) -> List[ToolDef]:
        """返回所有启用的工具"""
        return [t for t in self._tools.values() if t.enabled]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def __iter__(self):
        return iter(self._tools.values())

    # ---- 调用 ----

    async def invoke(
        self,
        tool_id: str,
        args: Dict[str, Any],
        ctx: Optional[ToolContext] = None,
    ) -> ToolResult:
        """调用指定工具

        这是工具调用的统一入口。

        Args:
            tool_id: 工具 ID
            args: 工具参数
            ctx: 执行上下文

        Returns:
            ToolResult 执行结果

        Raises:
            ToolNotFoundError: 工具未找到
            ToolInvalidArgumentsError: 参数校验失败
            ToolExecutionError: 执行异常
        """
        tool_def = self._tools.get(tool_id)
        if tool_def is None:
            raise ToolNotFoundError(tool_id)

        if not tool_def.enabled:
            return ToolResult.error(f"Tool '{tool_id}' is disabled")

        return await tool_def.execute(args, ctx)

    # ---- 序列化/导出 ----

    def to_llm_tool_list(self, filter_fn: Optional[Callable[[ToolDef], bool]] = None) -> List[Dict[str, Any]]:
        """导出为 LLM tool calling 格式

        用于传给 OpenAI / Anthropic 等 API 的 tools 参数。

        Args:
            filter_fn: 可选的过滤函数，返回 True 表示包含该工具

        Returns:
            工具定义列表，每个元素包含 type, function 顶层结构
        """
        result = []
        for tool in self.enabled_tools():
            if filter_fn and not filter_fn(tool):
                continue
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.id,
                        "description": tool.description,
                        "parameters": tool.parameter_schema(),
                    },
                }
            )
        return result

    def summary(self) -> Dict[str, Any]:
        """返回注册表摘要信息"""
        by_source: Dict[str, int] = {}
        for tool in self._tools.values():
            by_source[tool.source.value] = by_source.get(tool.source.value, 0) + 1

        return {
            "total": len(self._tools),
            "enabled": len(self.enabled_tools()),
            "by_source": by_source,
            "tool_ids": self.ids(),
        }

    # ---- 内部方法 ----

    def _do_register(self, tool_def: ToolDef) -> None:
        """内部注册逻辑"""
        existing = self._tools.get(tool_def.id)
        if existing is not None:
            raise ToolRegistrationError(
                f"Tool '{tool_def.id}' is already registered "
                f"(source={existing.source.value}). "
                f"Unregister it first or use a different id."
            )
        self._tools[tool_def.id] = tool_def
        logger.debug("Registered tool: %s (source=%s)", tool_def.id, tool_def.source.value)


# ---------------------------------------------------------------------------
#  辅助函数
# ---------------------------------------------------------------------------


def _sanitize_args(args: Dict[str, Any], max_value_len: int = 200) -> Dict[str, Any]:
    """脱敏参数值，用于日志输出"""
    sanitized: Dict[str, Any] = {}
    for k, v in args.items():
        sv = str(v)
        if len(sv) > max_value_len:
            sanitized[k] = sv[:max_value_len] + "..."
        else:
            sanitized[k] = sv
    return sanitized


# ---------------------------------------------------------------------------
#  默认全局注册表（单例）
# ---------------------------------------------------------------------------

_default_registry: Optional[ToolRegistry] = None


def get_default_registry() -> ToolRegistry:
    """获取默认全局注册表（懒初始化单例）"""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
    return _default_registry


def reset_default_registry() -> ToolRegistry:
    """重置默认全局注册表（主要用于测试）"""
    global _default_registry
    _default_registry = ToolRegistry()
    return _default_registry


def create_filtered_registry(source_registry: ToolRegistry, permissions: "PermissionConfig") -> ToolRegistry:
    """根据权限配置创建过滤后的工具注册表

    规则：
    - 如果 permissions 为空（allow/deny/ask 都为空），返回源 registry 的完整副本
    - 如果 allow 非空，只保留 allow 中列出的工具
    - 如果 deny 非空，排除 deny 中列出的工具
    - allow 和 deny 同时存在时，先 apply allow 再 remove deny

    Args:
        source_registry: 源工具注册表
        permissions: 权限配置（来自 Component.permission）

    Returns:
        过滤后的新 ToolRegistry 实例
    """
    from core.models import PermissionConfig  # 避免循环导入

    filtered = ToolRegistry()

    # 获取源 registry 的所有工具
    all_tools = source_registry.all()

    if permissions.allow:
        # allow 模式：只保留列出的工具
        allowed = set(permissions.allow)
        for tool in all_tools:
            if tool.id in allowed:
                filtered.register(tool)
    else:
        # 没有 allow，注册所有工具
        for tool in all_tools:
            filtered.register(tool)

    # deny 模式：排除列出的工具
    if permissions.deny:
        denied = set(permissions.deny)
        for tool_name in denied:
            if filtered.has(tool_name):
                filtered.unregister(tool_name)

    return filtered


def register_builtin_tools(registry: Optional[ToolRegistry] = None) -> int:
    """Register all built-in tools from tools/ package into the core registry.

    Uses the LegacyToolAdapter bridge to convert tools.tool.Tool instances
    into core.tool_registry.BaseTool instances.

    Args:
        registry: Target registry. Defaults to the global singleton.

    Returns:
        Number of tools successfully registered.
    """
    registry = registry or get_default_registry()
    from tools.bridge import LegacyToolAdapter
    from tools.shell import ShellTool
    from tools.read import ReadTool
    from tools.write import WriteTool
    from tools.glob import GlobTool
    from tools.grep import GrepTool
    from tools.webfetch import WebFetchTool
    from tools.run_workflow import RunWorkflowTool

    count = 0
    for tool_cls in [ShellTool, ReadTool, WriteTool, GlobTool, GrepTool, WebFetchTool, RunWorkflowTool]:
        try:
            instance = tool_cls()
            # Skip if already registered (e.g., from a previous call)
            if registry.has(instance.id):
                continue
            adapter = LegacyToolAdapter(instance)
            registry.register(adapter)
            count += 1
        except Exception as e:
            logger.warning("Failed to register builtin tool %s: %s", tool_cls.__name__, e)

    if count:
        logger.info("Registered %d builtin tools into core registry", count)
    return count

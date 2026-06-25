"""
GrassFlow 工具注册表测试

覆盖：
- ToolDef 创建与校验
- ToolResult / ToolContext
- BaseTool 子类注册
- @register_tool 装饰器注册
- ToolRegistry CRUD（注册/查询/注销/清空）
- ToolRegistry.invoke 统一调用入口
- MCPToolAdapter 适配
- 参数校验
- 插件目录加载
- LLM 工具列表导出
- 错误路径
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tool_registry import (
    BaseTool,
    GrassFlowToolError,
    MCPToolAdapter,
    ParameterSchema,
    ToolContext,
    ToolDef,
    ToolExecutionError,
    ToolInvalidArgumentsError,
    ToolNotFoundError,
    ToolPermission,
    ToolRegistrationError,
    ToolResult,
    ToolSource,
    ToolRegistry,
    _DECORATOR_REGISTRY,
    get_default_registry,
    register_tool,
    reset_default_registry,
)


# =========================================================================
#  辅助工具类 / 函数
# =========================================================================


class EchoTool(BaseTool):
    """测试用：回显输入"""

    @property
    def id(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo the input back"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"],
        }

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult.success(args["message"])


class FailingTool(BaseTool):
    """测试用：总是抛异常"""

    @property
    def id(self) -> str:
        return "failing"

    @property
    def description(self) -> str:
        return "Always raises an error"

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("intentional failure")


class SlowTool(BaseTool):
    """测试用：模拟慢工具"""

    @property
    def id(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "Simulates a slow operation"

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        await asyncio.sleep(0.05)
        return ToolResult.success("done")


class AbortCheckTool(BaseTool):
    """测试用：检查中止信号"""

    @property
    def id(self) -> str:
        return "abort_check"

    @property
    def description(self) -> str:
        return "Checks abort signal"

    async def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        if ctx.is_aborted():
            return ToolResult.error("aborted")
        return ToolResult.success("ok")


# =========================================================================
#  测试：ToolResult
# =========================================================================


class TestToolResult:
    def test_success_factory(self):
        r = ToolResult.success("hello")
        assert r.output == "hello"
        assert r.is_error is False

    def test_error_factory(self):
        r = ToolResult.error("oops")
        assert r.output == "oops"
        assert r.is_error is True

    def test_metadata_and_title(self):
        r = ToolResult.success("data", title="My Title", metadata={"key": 42})
        assert r.title == "My Title"
        assert r.metadata["key"] == 42

    def test_attachments(self):
        r = ToolResult.success("data", attachments=[{"type": "file", "url": "file:///tmp/test.txt"}])
        assert len(r.attachments) == 1


# =========================================================================
#  测试：ToolContext
# =========================================================================


class TestToolContext:
    def test_default_values(self):
        ctx = ToolContext()
        assert ctx.session_id == ""
        assert ctx.agent_name == ""
        assert ctx.is_aborted() is False

    def test_abort_signal(self):
        event = asyncio.Event()
        event.set()
        ctx = ToolContext(abort_signal=event)
        assert ctx.is_aborted() is True

    def test_request_permission(self):
        ctx = ToolContext()
        ctx.request_permission("read", ["/tmp/test.txt"], always=["*"])
        assert len(ctx._permission_requests) == 1
        assert ctx._permission_requests[0]["permission"] == "read"


# =========================================================================
#  测试：ToolDef
# =========================================================================


class TestToolDef:
    def test_create_minimal(self):
        td = ToolDef(id="test", description="A test tool")
        assert td.id == "test"
        assert td.source == ToolSource.BUILTIN
        assert td.enabled is True

    def test_create_with_parameters(self):
        params = {
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"],
        }
        td = ToolDef(id="greet", description="Greet", parameters=params)
        schema = td.parameter_schema()
        assert schema["properties"]["name"]["type"] == "string"
        assert "name" in schema["required"]

    def test_id_validation_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            ToolDef(id="", description="bad")

    def test_id_validation_rejects_spaces(self):
        with pytest.raises(ValueError, match="invalid characters"):
            ToolDef(id="has space", description="bad")

    def test_id_allows_dot_and_hyphen(self):
        td = ToolDef(id="mcp_github.create-issue", description="ok")
        assert td.id == "mcp_github.create-issue"

    def test_to_info_dict(self):
        td = ToolDef(
            id="my_tool",
            description="does stuff",
            parameters={"properties": {"x": {"type": "integer"}}, "required": ["x"]},
        )
        info = td.to_info_dict()
        assert info["id"] == "my_tool"
        assert info["description"] == "does stuff"
        assert "x" in info["parameters"]["properties"]


# =========================================================================
#  测试：BaseTool 子类
# =========================================================================


class TestBaseTool:
    def test_echo_tool_properties(self):
        tool = EchoTool()
        assert tool.id == "echo"
        assert tool.source == ToolSource.BUILTIN
        assert "message" in tool.parameters.get("properties", {})

    def test_to_tool_def(self):
        tool = EchoTool()
        td = tool.to_tool_def()
        assert td.id == "echo"
        assert td.execute_fn is not None

    @pytest.mark.asyncio
    async def test_echo_tool_execute(self):
        tool = EchoTool()
        td = tool.to_tool_def()
        result = await td.execute({"message": "hello"}, ToolContext())
        assert result.output == "hello"
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_failing_tool_raises(self):
        tool = FailingTool()
        td = tool.to_tool_def()
        with pytest.raises(ToolExecutionError, match="intentional failure"):
            await td.execute({}, ToolContext())


# =========================================================================
#  测试：@register_tool 装饰器
# =========================================================================


class TestRegisterToolDecorator:
    def setup_method(self):
        # 清理装饰器注册表中可能残留的测试条目
        _DECORATOR_REGISTRY.pop("decorated_echo", None)
        _DECORATOR_REGISTRY.pop("decorated_add", None)

    def test_decorator_registers_function(self):
        @register_tool(
            "decorated_echo",
            description="Echo via decorator",
            parameters={
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        )
        async def decorated_echo(args: dict, ctx: ToolContext) -> ToolResult:
            return ToolResult.success(args["msg"])

        assert "decorated_echo" in _DECORATOR_REGISTRY
        td = _DECORATOR_REGISTRY["decorated_echo"]
        assert td.description == "Echo via decorator"
        assert hasattr(decorated_echo, "_tool_def")

    @pytest.mark.asyncio
    async def test_decorated_function_is_executable(self):
        @register_tool(
            "decorated_add",
            description="Add two numbers",
            parameters={
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        )
        async def decorated_add(args: dict, ctx: ToolContext) -> ToolResult:
            return ToolResult.success(str(args["a"] + args["b"]))

        td = _DECORATOR_REGISTRY["decorated_add"]
        result = await td.execute({"a": 3, "b": 4}, ToolContext())
        assert result.output == "7"


# =========================================================================
#  测试：ToolRegistry
# =========================================================================


class TestToolRegistry:
    def test_register_base_tool(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        assert registry.has("echo")
        assert len(registry) == 1

    def test_register_tool_def(self):
        registry = ToolRegistry()
        td = ToolDef(id="t1", description="tool 1")
        registry.register_tool_def(td)
        assert "t1" in registry

    def test_register_function(self):
        registry = ToolRegistry()

        async def my_func(args: dict, ctx: ToolContext) -> ToolResult:
            return ToolResult.success("ok")

        registry.register_function(my_func, "fn_tool", "A function tool")
        assert registry.has("fn_tool")

    def test_duplicate_registration_raises(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        with pytest.raises(ToolRegistrationError, match="already registered"):
            registry.register(EchoTool())

    def test_unregister(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        assert registry.unregister("echo") is True
        assert registry.has("echo") is False
        assert registry.unregister("nonexistent") is False

    def test_clear(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(FailingTool())
        count = registry.clear()
        assert count == 2
        assert len(registry) == 0

    def test_get_returns_none_for_missing(self):
        registry = ToolRegistry()
        assert registry.get("nope") is None

    def test_ids_and_all(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(FailingTool())
        ids = registry.ids()
        assert "echo" in ids
        assert "failing" in ids
        assert len(registry.all()) == 2

    def test_filter_by_source(self):
        registry = ToolRegistry()
        registry.register(EchoTool())  # BUILTIN
        # 手动注册一个 plugin 来源
        td = PluginTool()
        registry.register(td)
        builtins = registry.filter_by_source(ToolSource.BUILTIN)
        assert len(builtins) == 1

    def test_filter_by_tag(self):
        registry = ToolRegistry()
        td = ToolDef(id="tagged", description="tagged", tags=["math", "test"])
        registry.register_tool_def(td)
        assert len(registry.filter_by_tag("math")) == 1
        assert len(registry.filter_by_tag("other")) == 0

    def test_filter_by_permission(self):
        registry = ToolRegistry()
        td = ToolDef(id="ask_tool", description="needs permission", permission=ToolPermission.ASK)
        registry.register_tool_def(td)
        assert len(registry.filter_by_permission(ToolPermission.ASK)) == 1
        assert len(registry.filter_by_permission(ToolPermission.DENY)) == 0

    def test_enabled_tools(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        td = ToolDef(id="disabled", description="off", enabled=False)
        registry.register_tool_def(td)
        assert len(registry.enabled_tools()) == 1

    def test_contains_and_iter(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        assert "echo" in registry
        tools = list(registry)
        assert len(tools) == 1

    def test_register_from_decorators(self):
        # 装饰器注册表在 setup_method 中可能已被清理
        # 这里手动放一个
        _DECORATOR_REGISTRY.pop("_test_from_dec", None)

        @register_tool("_test_from_dec", description="test", auto_register=True)
        async def _test_from_dec(args: dict, ctx: ToolContext) -> ToolResult:
            return ToolResult.success("ok")

        registry = ToolRegistry()
        count = registry.register_from_decorators()
        assert count >= 1
        assert registry.has("_test_from_dec")

    def test_summary(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        s = registry.summary()
        assert s["total"] == 1
        assert s["enabled"] == 1
        assert "builtin" in s["by_source"]


# =========================================================================
#  测试：ToolRegistry.invoke
# =========================================================================


class TestRegistryInvoke:
    @pytest.mark.asyncio
    async def test_invoke_success(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        result = await registry.invoke("echo", {"message": "hi"})
        assert result.output == "hi"

    @pytest.mark.asyncio
    async def test_invoke_not_found(self):
        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            await registry.invoke("nonexistent", {})

    @pytest.mark.asyncio
    async def test_invoke_disabled_tool(self):
        registry = ToolRegistry()
        td = ToolDef(id="d", description="disabled", enabled=False)
        registry.register_tool_def(td)
        result = await registry.invoke("d", {})
        assert result.is_error is True
        assert "disabled" in result.output

    @pytest.mark.asyncio
    async def test_invoke_with_context(self):
        registry = ToolRegistry()
        registry.register(AbortCheckTool())

        # 未中止
        result = await registry.invoke("abort_check", {})
        assert result.output == "ok"

        # 已中止
        event = asyncio.Event()
        event.set()
        result = await registry.invoke("abort_check", {}, ToolContext(abort_signal=event))
        assert result.is_error is True
        assert "aborted" in result.output

    @pytest.mark.asyncio
    async def test_invoke_propagates_execution_error(self):
        registry = ToolRegistry()
        registry.register(FailingTool())
        with pytest.raises(ToolExecutionError):
            await registry.invoke("failing", {})

    @pytest.mark.asyncio
    async def test_invoke_records_elapsed_ms(self):
        registry = ToolRegistry()
        registry.register(SlowTool())
        result = await registry.invoke("slow", {})
        assert "elapsed_ms" in result.metadata
        assert result.metadata["elapsed_ms"] >= 40  # 50ms sleep, with some tolerance


# =========================================================================
#  测试：MCPToolAdapter
# =========================================================================


class TestMCPToolAdapter:
    def test_to_tool_def_format(self):
        mock_client = MagicMock()
        adapter = MCPToolAdapter(
            server_name="github",
            tool_id="create_issue",
            description="Create a GitHub issue",
            parameters={
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title"],
            },
            mcp_client=mock_client,
            tags=["git"],
        )
        td = adapter.to_tool_def()
        assert td.id == "mcp_github.create_issue"
        assert td.source == ToolSource.MCP
        assert "mcp:github" in td.tags
        assert "Create a GitHub issue" in td.description

    @pytest.mark.asyncio
    async def test_mcp_call_text_content(self):
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {
            "content": [{"type": "text", "text": "Issue created #42"}],
            "isError": False,
        }
        adapter = MCPToolAdapter(
            server_name="github",
            tool_id="create_issue",
            description="Create issue",
            parameters={},
            mcp_client=mock_client,
        )
        td = adapter.to_tool_def()
        result = await td.execute({"title": "Bug"}, ToolContext())
        assert result.output == "Issue created #42"
        assert result.is_error is False
        mock_client.call_tool.assert_called_once_with("create_issue", {"title": "Bug"})

    @pytest.mark.asyncio
    async def test_mcp_call_string_result(self):
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = "plain text result"
        adapter = MCPToolAdapter(
            server_name="test",
            tool_id="echo",
            description="Echo",
            parameters={},
            mcp_client=mock_client,
        )
        td = adapter.to_tool_def()
        result = await td.execute({}, ToolContext())
        assert result.output == "plain text result"

    @pytest.mark.asyncio
    async def test_mcp_call_error(self):
        mock_client = AsyncMock()
        mock_client.call_tool.side_effect = ConnectionError("connection refused")
        adapter = MCPToolAdapter(
            server_name="remote",
            tool_id="do_thing",
            description="Do thing",
            parameters={},
            mcp_client=mock_client,
        )
        td = adapter.to_tool_def()
        result = await td.execute({}, ToolContext())
        assert result.is_error is True
        assert "connection refused" in result.output

    def test_register_mcp_tools(self):
        registry = ToolRegistry()
        mock_client = MagicMock()
        tool_defs = [
            {"id": "search", "description": "Search repos", "inputSchema": {"properties": {"q": {"type": "string"}}}},
            {"id": "list_issues", "description": "List issues", "inputSchema": {}},
        ]
        registered = registry.register_mcp_tools("github", mock_client, tool_defs)
        assert len(registered) == 2
        assert "mcp_github.search" in registered
        assert "mcp_github.list_issues" in registered
        assert registry.has("mcp_github.search")


# =========================================================================
#  测试：插件目录加载
# =========================================================================


class TestPluginLoading:
    @pytest.mark.asyncio
    async def test_load_plugins_from_directory(self):
        """创建临时插件目录，写入一个使用 @register_tool 的 .py 文件，验证加载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_code = '''
import sys
sys.path.insert(0, r"E:/opencode-desktop/GrassFlow")

from core.tool_registry import register_tool, ToolResult, ToolContext

@register_tool("plugin_hello", description="Say hello from plugin")
async def plugin_hello(args, ctx):
    return ToolResult.success("hello from plugin")
'''
            plugin_file = Path(tmpdir) / "hello_plugin.py"
            plugin_file.write_text(plugin_code, encoding="utf-8")

            registry = ToolRegistry()
            count = await registry.load_plugins_from_directory(tmpdir)
            assert count >= 1
            assert registry.has("plugin_hello")

            # 验证可以调用
            result = await registry.invoke("plugin_hello", {})
            assert result.output == "hello from plugin"

    @pytest.mark.asyncio
    async def test_load_plugins_skips_underscore_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "_private.py").write_text("x = 1", encoding="utf-8")
            registry = ToolRegistry()
            count = await registry.load_plugins_from_directory(tmpdir)
            assert count == 0

    @pytest.mark.asyncio
    async def test_load_plugins_nonexistent_directory(self):
        registry = ToolRegistry()
        count = await registry.load_plugins_from_directory("/nonexistent/path")
        assert count == 0


# =========================================================================
#  测试：参数校验
# =========================================================================


class TestParameterValidation:
    @pytest.mark.asyncio
    async def test_valid_args_pass(self):
        td = ToolDef(
            id="math_add",
            description="Add",
            parameters={
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
        )
        async def _add(args, ctx):
            return ToolResult.success(str(args["a"] + args["b"]))

        td.execute_fn = _add

        result = await td.execute({"a": 1, "b": 2}, ToolContext())
        assert result.output == "3"

    def test_validate_args_missing_required(self):
        td = ToolDef(
            id="strict",
            description="Strict tool",
            parameters={
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        )
        with pytest.raises(ToolInvalidArgumentsError, match="invalid arguments"):
            td.validate_args({})  # missing required "name"


# =========================================================================
#  测试：LLM 工具列表导出
# =========================================================================


class TestLLMToolList:
    def test_to_llm_tool_list_format(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        tools = registry.to_llm_tool_list()
        assert len(tools) == 1
        item = tools[0]
        assert item["type"] == "function"
        assert item["function"]["name"] == "echo"
        assert "message" in item["function"]["parameters"]["properties"]

    def test_to_llm_tool_list_with_filter(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        registry.register(FailingTool())

        # 只包含带 "echo" 的
        tools = registry.to_llm_tool_list(filter_fn=lambda t: t.id == "echo")
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "echo"

    def test_to_llm_tool_list_excludes_disabled(self):
        registry = ToolRegistry()
        registry.register(EchoTool())
        td = ToolDef(id="off", description="off", enabled=False)
        registry.register_tool_def(td)
        tools = registry.to_llm_tool_list()
        assert len(tools) == 1


# =========================================================================
#  测试：全局注册表单例
# =========================================================================


class TestGlobalRegistry:
    def test_get_default_registry_is_singleton(self):
        reset_default_registry()
        r1 = get_default_registry()
        r2 = get_default_registry()
        assert r1 is r2

    def test_reset_default_registry(self):
        r1 = get_default_registry()
        r1.register(EchoTool())
        r2 = reset_default_registry()
        assert r2 is not r1
        assert len(r2) == 0


# =========================================================================
#  测试：错误类型
# =========================================================================


class TestErrorTypes:
    def test_tool_not_found_error(self):
        e = ToolNotFoundError("missing")
        assert e.tool_id == "missing"
        assert "not found" in str(e).lower()

    def test_tool_invalid_arguments_error(self):
        e = ToolInvalidArgumentsError("t1", "field X is required")
        assert e.tool_id == "t1"
        assert "invalid arguments" in str(e).lower()

    def test_tool_execution_error(self):
        e = ToolExecutionError("t1", "connection timeout")
        assert e.tool_id == "t1"
        assert "execution failed" in str(e).lower()

    def test_all_errors_inherit_from_base(self):
        assert issubclass(ToolNotFoundError, GrassFlowToolError)
        assert issubclass(ToolInvalidArgumentsError, GrassFlowToolError)
        assert issubclass(ToolExecutionError, GrassFlowToolError)
        assert issubclass(ToolRegistrationError, GrassFlowToolError)


# =========================================================================
#  测试：ParameterSchema
# =========================================================================


class TestParameterSchema:
    def test_default_values(self):
        ps = ParameterSchema()
        assert ps.type == "object"
        assert ps.properties == {}

    def test_with_properties(self):
        ps = ParameterSchema(
            properties={"name": {"type": "string"}},
            required=["name"],
        )
        assert ps.required == ["name"]

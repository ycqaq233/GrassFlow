"""
GrassFlow MCP 客户端测试
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.mcp_client import (
    HTTPTransport,
    MCPClient,
    MCPClientStatus,
    MCPError,
    MCPServerConfig,
    MCPToolDefinition,
    MCPToolResult,
    MCPTransportType,
    SSETransport,
    StdioTransport,
    MCPManager,
)


class TestMCPServerConfig:
    """MCPServerConfig 测试"""

    def test_create_stdio_config(self):
        """测试创建 stdio 配置"""
        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )

        assert config.name == "test"
        assert config.transport_type == MCPTransportType.STDIO
        assert config.command == "npx"
        assert config.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        assert config.enabled is True

    def test_create_http_config(self):
        """测试创建 HTTP 配置"""
        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.HTTP,
            url="http://localhost:8080/mcp",
            headers={"Authorization": "Bearer token"},
        )

        assert config.name == "test"
        assert config.transport_type == MCPTransportType.HTTP
        assert config.url == "http://localhost:8080/mcp"
        assert config.headers == {"Authorization": "Bearer token"}

    def test_from_dict_stdio(self):
        """测试从字典创建 stdio 配置"""
        config_dict = {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": {"KEY": "value"},
        }

        config = MCPServerConfig.from_dict("test", config_dict)

        assert config.name == "test"
        assert config.transport_type == MCPTransportType.STDIO
        assert config.command == "npx"
        assert config.args == ["-y", "@modelcontextprotocol/server-filesystem"]
        assert config.env == {"KEY": "value"}

    def test_from_dict_http(self):
        """测试从字典创建 HTTP 配置"""
        config_dict = {
            "type": "http",
            "url": "http://localhost:8080/mcp",
            "timeout": 60.0,
        }

        config = MCPServerConfig.from_dict("test", config_dict)

        assert config.name == "test"
        assert config.transport_type == MCPTransportType.HTTP
        assert config.url == "http://localhost:8080/mcp"
        assert config.timeout == 60.0

    def test_from_dict_disabled(self):
        """测试禁用配置"""
        config_dict = {
            "type": "stdio",
            "command": "test",
            "enabled": False,
        }

        config = MCPServerConfig.from_dict("test", config_dict)

        assert config.enabled is False


class TestMCPToolDefinition:
    """MCPToolDefinition 测试"""

    def test_qualified_name(self):
        """测试限定名称"""
        tool = MCPToolDefinition(
            name="read_file",
            description="Read a file",
            server_name="filesystem",
        )

        assert tool.qualified_name == "filesystem:read_file"

    def test_qualified_name_no_server(self):
        """测试无服务器名的限定名称"""
        tool = MCPToolDefinition(
            name="read_file",
            description="Read a file",
        )

        assert tool.qualified_name == "read_file"


class TestMCPToolResult:
    """MCPToolResult 测试"""

    def test_text_content(self):
        """测试文本内容提取"""
        result = MCPToolResult(
            content=[
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
                {"type": "image", "data": "base64..."},
            ],
        )

        assert result.text_content == "Hello\nWorld"

    def test_empty_content(self):
        """测试空内容"""
        result = MCPToolResult(content=[])
        assert result.text_content == ""

    def test_is_error(self):
        """测试错误标志"""
        result = MCPToolResult(
            content=[{"type": "text", "text": "Error occurred"}],
            is_error=True,
        )

        assert result.is_error is True


@pytest.mark.asyncio
class TestStdioTransport:
    """StdioTransport 测试"""

    async def test_initial_state(self):
        """测试初始状态"""
        transport = StdioTransport(command="test")
        assert transport.is_connected is False

    async def test_connect_not_connected(self):
        """测试未连接状态"""
        transport = StdioTransport(command="nonexistent_command")

        with pytest.raises(Exception):
            await transport.send_request("test")

    @patch("asyncio.create_subprocess_exec")
    async def test_connect_success(self, mock_subprocess):
        """测试连接成功"""
        mock_process = AsyncMock()
        mock_process.stdin = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(return_value=b"")
        mock_subprocess.return_value = mock_process

        transport = StdioTransport(command="test")

        # Mock the initialize call
        with patch.object(transport, "_initialize", new_callable=AsyncMock):
            await transport.connect()

        assert transport.is_connected is True

    async def test_disconnect(self):
        """测试断开连接"""
        transport = StdioTransport(command="test")
        transport._connected = True
        transport._process = AsyncMock()
        transport._process.terminate = MagicMock()
        transport._process.wait = AsyncMock()

        await transport.disconnect()

        assert transport.is_connected is False


@pytest.mark.asyncio
class TestHTTPTransport:
    """HTTPTransport 测试"""

    async def test_initial_state(self):
        """测试初始状态"""
        transport = HTTPTransport(url="http://localhost:8080")
        assert transport.is_connected is False

    @patch("httpx.AsyncClient")
    async def test_connect_success(self, mock_client_class):
        """测试连接成功"""
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        # Mock initialize response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"protocolVersion": "2024-11-05"}}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        transport = HTTPTransport(url="http://localhost:8080/mcp")

        with patch.object(transport, "_initialize", new_callable=AsyncMock):
            await transport.connect()

        assert transport.is_connected is True

    async def test_send_request_not_connected(self):
        """测试未连接时发送请求"""
        transport = HTTPTransport(url="http://localhost:8080")

        with pytest.raises(MCPError, match="Not connected"):
            await transport.send_request("test")


@pytest.mark.asyncio
class TestMCPClient:
    """MCPClient 测试"""

    async def test_initial_state(self):
        """测试初始状态"""
        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
        )
        client = MCPClient(config)

        assert client.name == "test"
        assert client.status == MCPClientStatus.DISCONNECTED
        assert len(client.tools) == 0
        assert len(client.resources) == 0
        assert len(client.prompts) == 0
        assert client.instructions is None

    async def test_disabled_client(self):
        """测试禁用的客户端"""
        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
            enabled=False,
        )
        client = MCPClient(config)

        await client.connect()

        assert client.status == MCPClientStatus.DISCONNECTED

    @patch.object(StdioTransport, "connect", new_callable=AsyncMock)
    @patch.object(StdioTransport, "send_request", new_callable=AsyncMock)
    async def test_connect_stdio(self, mock_send_request, mock_connect):
        """测试 stdio 连接"""
        mock_connect.return_value = None
        mock_send_request.side_effect = [
            {"tools": [{"name": "tool1", "description": "Test tool"}]},  # tools/list
            {"resources": []},  # resources/list
            {"prompts": []},  # prompts/list
        ]

        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
        )
        client = MCPClient(config)

        await client.connect()

        assert client.status == MCPClientStatus.CONNECTED
        assert len(client.tools) == 1
        assert "test:tool1" in client.tools

    @patch.object(StdioTransport, "connect", new_callable=AsyncMock)
    @patch.object(StdioTransport, "send_request", new_callable=AsyncMock)
    async def test_call_tool(self, mock_send_request, mock_connect):
        """测试调用工具"""
        mock_connect.return_value = None
        mock_send_request.side_effect = [
            {"tools": [{"name": "tool1", "description": "Test tool"}]},  # tools/list
            {"resources": []},  # resources/list
            {"prompts": []},  # prompts/list
            {"content": [{"type": "text", "text": "result"}]},  # tools/call
        ]

        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
        )
        client = MCPClient(config)
        await client.connect()

        result = await client.call_tool("tool1", {"arg": "value"})

        assert result.text_content == "result"
        assert result.is_error is False


@pytest.mark.asyncio
class TestMCPManager:
    """MCPManager 测试"""

    async def test_add_server(self):
        """测试添加服务器"""
        manager = MCPManager()

        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
        )
        client = manager.add_server(config)

        assert "test" in manager.clients
        assert client.name == "test"

    async def test_remove_server(self):
        """测试移除服务器"""
        manager = MCPManager()

        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
        )
        manager.add_server(config)

        # 添加一些工具
        manager._all_tools["test:tool1"] = MCPToolDefinition(
            name="tool1",
            server_name="test",
        )

        manager.remove_server("test")

        assert "test" not in manager.clients
        assert "test:tool1" not in manager._all_tools

    async def test_get_status(self):
        """测试获取状态"""
        manager = MCPManager()

        config1 = MCPServerConfig(
            name="server1",
            transport_type=MCPTransportType.STDIO,
            command="test1",
        )
        config2 = MCPServerConfig(
            name="server2",
            transport_type=MCPTransportType.HTTP,
            url="http://localhost:8080",
        )

        manager.add_server(config1)
        manager.add_server(config2)

        status = manager.get_status()

        assert status["server1"] == MCPClientStatus.DISCONNECTED
        assert status["server2"] == MCPClientStatus.DISCONNECTED

    def test_from_config(self):
        """测试从配置创建"""
        config = {
            "filesystem": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            },
            "api": {
                "type": "http",
                "url": "http://localhost:8080/mcp",
            },
        }

        manager = MCPManager.from_config(config)

        assert len(manager.clients) == 2
        assert "filesystem" in manager.clients
        assert "api" in manager.clients

    async def test_call_tool_not_found(self):
        """测试调用不存在的工具"""
        manager = MCPManager()

        with pytest.raises(MCPError, match="Tool not found"):
            await manager.call_tool("nonexistent:tool")

    async def test_get_client(self):
        """测试获取客户端"""
        manager = MCPManager()

        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="test",
        )
        manager.add_server(config)

        client = manager.get_client("test")
        assert client is not None
        assert client.name == "test"

        assert manager.get_client("nonexistent") is None


class TestMCPError:
    """MCPError 测试"""

    def test_error_message(self):
        """测试错误消息"""
        error = MCPError("Test error")
        assert str(error) == "Test error"
        assert error.code is None

    def test_error_with_code(self):
        """测试带错误码的错误"""
        error = MCPError("Not found", code=-32001)
        assert str(error) == "Not found"
        assert error.code == -32001


@pytest.mark.asyncio
class TestIntegration:
    """集成测试"""

    async def test_full_workflow(self):
        """测试完整工作流"""
        # 创建管理器
        manager = MCPManager()

        # 添加服务器
        config = MCPServerConfig(
            name="test",
            transport_type=MCPTransportType.STDIO,
            command="echo",  # 使用 echo 作为测试命令
            enabled=False,  # 禁用以避免实际连接
        )
        client = manager.add_server(config)

        # 验证初始状态
        assert manager.get_status() == {"test": MCPClientStatus.DISCONNECTED}

        # 验证工具列表为空
        assert len(manager.tools) == 0

        # 验证客户端
        assert client.name == "test"
        assert client.status == MCPClientStatus.DISCONNECTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

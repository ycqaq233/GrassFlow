"""
GrassFlow MCP (Model Context Protocol) 客户端实现

参考 opencode 的 MCP 实现，支持：
- local (stdio) 传输
- remote (HTTP/SSE) 传输
- 工具发现和注册
- 资源和提示获取
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)


class MCPTransportType(Enum):
    """MCP 传输类型"""
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


class MCPClientStatus(Enum):
    """MCP 客户端状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPToolDefinition:
    """MCP 工具定义"""
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""

    @property
    def qualified_name(self) -> str:
        """返回限定名称: server_name:tool_name"""
        if self.server_name:
            return f"{self.server_name}:{self.name}"
        return self.name


@dataclass
class MCPResource:
    """MCP 资源"""
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_name: str = ""


@dataclass
class MCPPrompt:
    """MCP 提示"""
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)
    server_name: str = ""


@dataclass
class MCPToolResult:
    """MCP 工具调用结果"""
    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False

    @property
    def text_content(self) -> str:
        """获取文本内容"""
        texts = []
        for item in self.content:
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)


class MCPTransport(ABC):
    """MCP 传输抽象基类"""

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送请求"""
        pass

    @abstractmethod
    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送通知"""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        pass


class StdioTransport(MCPTransport):
    """Stdio 传输实现"""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._connected = False
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._request_id = 0

    async def connect(self) -> None:
        """启动子进程"""
        if self._connected:
            return

        try:
            cmd = [self.command] + self.args
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
                cwd=self.cwd,
            )
            self._connected = True
            self._reader_task = asyncio.create_task(self._read_responses())
            logger.info(f"Stdio transport connected: {self.command}")

            # 发送初始化请求
            await self._initialize()

        except Exception as e:
            logger.error(f"Failed to connect stdio transport: {e}")
            raise

    async def _initialize(self) -> None:
        """初始化 MCP 连接"""
        result = await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
            },
            "clientInfo": {
                "name": "grassflow",
                "version": "1.0.0",
            },
        })
        logger.info(f"MCP initialized: {result}")

        # 发送初始化完成通知
        await self.send_notification("notifications/initialized")

    async def _read_responses(self) -> None:
        """读取子进程响应"""
        if not self._process or not self._process.stdout:
            return

        buffer = ""
        while self._connected and self._process.stdout:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                buffer += line.decode("utf-8")
                if "\n" in buffer:
                    messages = buffer.split("\n")
                    buffer = messages.pop()

                    for msg_str in messages:
                        msg_str = msg_str.strip()
                        if not msg_str:
                            continue
                        try:
                            message = json.loads(msg_str)
                            self._handle_message(message)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON: {msg_str}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading response: {e}")
                break

        self._connected = False

    def _handle_message(self, message: dict[str, Any]) -> None:
        """处理收到的消息"""
        msg_id = message.get("id")
        if msg_id is not None and msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)
            if "error" in message:
                future.set_exception(MCPError(
                    message["error"].get("message", "Unknown error"),
                    message["error"].get("code"),
                ))
            else:
                future.set_result(message.get("result", {}))
        elif "method" in message:
            # 处理通知
            logger.debug(f"Received notification: {message['method']}")

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送 JSON-RPC 请求"""
        if not self._process or not self._process.stdin:
            raise MCPError("Not connected")

        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            request_str = json.dumps(request) + "\n"
            self._process.stdin.write(request_str.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise MCPError(f"Failed to send request: {e}")

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise MCPError(f"Request timeout: {method}")

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送 JSON-RPC 通知"""
        if not self._process or not self._process.stdin:
            raise MCPError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        try:
            notification_str = json.dumps(notification) + "\n"
            self._process.stdin.write(notification_str.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            raise MCPError(f"Failed to send notification: {e}")

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()
            self._process = None

        # 清理未完成的请求
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(MCPError("Connection closed"))
        self._pending_requests.clear()

        logger.info("Stdio transport disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None


class HTTPTransport(MCPTransport):
    """HTTP 传输实现"""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False
        self._session_id: str | None = None

    async def connect(self) -> None:
        """建立 HTTP 连接"""
        if self._connected:
            return

        try:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                headers=self.headers,
                timeout=self.timeout,
            )
            self._connected = True

            # 初始化
            await self._initialize()
            logger.info(f"HTTP transport connected: {self.url}")

        except Exception as e:
            logger.error(f"Failed to connect HTTP transport: {e}")
            raise

    async def _initialize(self) -> None:
        """初始化 MCP 连接"""
        result = await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
            },
            "clientInfo": {
                "name": "grassflow",
                "version": "1.0.0",
            },
        })
        logger.info(f"MCP initialized: {result}")

        # 发送初始化完成通知
        await self.send_notification("notifications/initialized")

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送 HTTP 请求"""
        if not self._client:
            raise MCPError("Not connected")

        request_id = str(uuid.uuid4())
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        try:
            response = await self._client.post(
                "/mcp",
                json=request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPError(
                    result["error"].get("message", "Unknown error"),
                    result["error"].get("code"),
                )
            return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise MCPError(f"HTTP error: {e.response.status_code}")
        except Exception as e:
            if isinstance(e, MCPError):
                raise
            raise MCPError(f"Request failed: {e}")

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送 HTTP 通知"""
        if not self._client:
            raise MCPError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        try:
            response = await self._client.post(
                "/mcp",
                json=notification,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("HTTP transport disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None


class SSETransport(MCPTransport):
    """SSE (Server-Sent Events) 传输实现"""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False
        self._endpoint_url: str | None = None
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._request_id = 0
        self._sse_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """建立 SSE 连接"""
        if self._connected:
            return

        try:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
            )
            self._connected = True

            # 连接到 SSE 端点获取消息端点 URL
            await self._connect_sse()

            # 初始化
            await self._initialize()
            logger.info(f"SSE transport connected: {self.url}")

        except Exception as e:
            logger.error(f"Failed to connect SSE transport: {e}")
            raise

    async def _connect_sse(self) -> None:
        """连接到 SSE 端点"""
        if not self._client:
            return

        try:
            # 发送 GET 请求建立 SSE 连接
            async with self._client.stream("GET", self.url) as response:
                response.raise_for_status()

                # 解析 SSE 事件获取端点 URL
                async for line in response.aiter_lines():
                    if line.startswith("event: endpoint"):
                        # 下一行包含端点 URL
                        continue
                    if line.startswith("data: "):
                        self._endpoint_url = line[6:].strip()
                        logger.info(f"SSE endpoint: {self._endpoint_url}")
                        break

        except Exception as e:
            raise MCPError(f"Failed to connect SSE: {e}")

    async def _initialize(self) -> None:
        """初始化 MCP 连接"""
        result = await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "roots": {"listChanged": True},
            },
            "clientInfo": {
                "name": "grassflow",
                "version": "1.0.0",
            },
        })
        logger.info(f"MCP initialized: {result}")

        # 发送初始化完成通知
        await self.send_notification("notifications/initialized")

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送请求"""
        if not self._client or not self._endpoint_url:
            raise MCPError("Not connected")

        self._request_id += 1
        request_id = str(self._request_id)

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        try:
            response = await self._client.post(
                self._endpoint_url,
                json=request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            result = response.json()
            if "error" in result:
                raise MCPError(
                    result["error"].get("message", "Unknown error"),
                    result["error"].get("code"),
                )
            return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise MCPError(f"HTTP error: {e.response.status_code}")
        except Exception as e:
            if isinstance(e, MCPError):
                raise
            raise MCPError(f"Request failed: {e}")

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """发送通知"""
        if not self._client or not self._endpoint_url:
            raise MCPError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        try:
            response = await self._client.post(
                self._endpoint_url,
                json=notification,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    async def disconnect(self) -> None:
        """断开连接"""
        self._connected = False

        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()
            self._client = None

        # 清理未完成的请求
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(MCPError("Connection closed"))
        self._pending_requests.clear()

        logger.info("SSE transport disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None


class MCPError(Exception):
    """MCP 错误"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class MCPServerConfig:
    """MCP 服务器配置"""

    def __init__(
        self,
        name: str,
        transport_type: MCPTransportType,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        enabled: bool = True,
    ):
        self.name = name
        self.transport_type = transport_type
        self.command = command
        self.args = args or []
        self.url = url
        self.env = env
        self.cwd = cwd
        self.headers = headers or {}
        self.timeout = timeout
        self.enabled = enabled

    @classmethod
    def from_dict(cls, name: str, config: dict[str, Any]) -> "MCPServerConfig":
        """从字典创建配置"""
        transport_type = MCPTransportType(config.get("type", "stdio"))

        return cls(
            name=name,
            transport_type=transport_type,
            command=config.get("command"),
            args=config.get("args", []),
            url=config.get("url"),
            env=config.get("env"),
            cwd=config.get("cwd"),
            headers=config.get("headers"),
            timeout=config.get("timeout", 30.0),
            enabled=config.get("enabled", True),
        )


class MCPClient:
    """MCP 客户端"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.status = MCPClientStatus.DISCONNECTED
        self._transport: MCPTransport | None = None
        self._tools: dict[str, MCPToolDefinition] = {}
        self._resources: dict[str, MCPResource] = {}
        self._prompts: dict[str, MCPPrompt] = {}
        self._instructions: str | None = None
        self._on_tools_changed: Callable[[], None] | None = None

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def tools(self) -> dict[str, MCPToolDefinition]:
        return self._tools.copy()

    @property
    def resources(self) -> dict[str, MCPResource]:
        return self._resources.copy()

    @property
    def prompts(self) -> dict[str, MCPPrompt]:
        return self._prompts.copy()

    @property
    def instructions(self) -> str | None:
        return self._instructions

    def on_tools_changed(self, callback: Callable[[], None]) -> None:
        """设置工具变更回调"""
        self._on_tools_changed = callback

    async def connect(self) -> None:
        """连接到 MCP 服务器"""
        if not self.config.enabled:
            logger.info(f"MCP server {self.name} is disabled")
            return

        if self.status == MCPClientStatus.CONNECTED:
            return

        self.status = MCPClientStatus.CONNECTING

        try:
            # 创建传输
            self._transport = self._create_transport()

            # 连接
            await self._transport.connect()

            # 获取工具列表
            await self._fetch_tools()

            # 获取资源列表
            await self._fetch_resources()

            # 获取提示列表
            await self._fetch_prompts()

            self.status = MCPClientStatus.CONNECTED
            logger.info(f"MCP client {self.name} connected")

        except Exception as e:
            self.status = MCPClientStatus.ERROR
            logger.error(f"Failed to connect MCP client {self.name}: {e}")
            raise

    def _create_transport(self) -> MCPTransport:
        """创建传输实例"""
        if self.config.transport_type == MCPTransportType.STDIO:
            if not self.config.command:
                raise MCPError("Command is required for stdio transport")
            return StdioTransport(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env,
                cwd=self.config.cwd,
            )
        elif self.config.transport_type == MCPTransportType.HTTP:
            if not self.config.url:
                raise MCPError("URL is required for HTTP transport")
            return HTTPTransport(
                url=self.config.url,
                headers=self.config.headers,
                timeout=self.config.timeout,
            )
        elif self.config.transport_type == MCPTransportType.SSE:
            if not self.config.url:
                raise MCPError("URL is required for SSE transport")
            return SSETransport(
                url=self.config.url,
                headers=self.config.headers,
                timeout=self.config.timeout,
            )
        else:
            raise MCPError(f"Unsupported transport type: {self.config.transport_type}")

    async def _fetch_tools(self) -> None:
        """获取工具列表"""
        if not self._transport:
            return

        try:
            result = await self._transport.send_request("tools/list")
            tools = result.get("tools", [])

            self._tools.clear()
            for tool_data in tools:
                tool = MCPToolDefinition(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                    server_name=self.name,
                )
                self._tools[tool.qualified_name] = tool

            logger.info(f"Discovered {len(self._tools)} tools from {self.name}")

        except Exception as e:
            logger.warning(f"Failed to fetch tools from {self.name}: {e}")

    async def _fetch_resources(self) -> None:
        """获取资源列表"""
        if not self._transport:
            return

        try:
            result = await self._transport.send_request("resources/list")
            resources = result.get("resources", [])

            self._resources.clear()
            for res_data in resources:
                resource = MCPResource(
                    uri=res_data.get("uri", ""),
                    name=res_data.get("name", ""),
                    description=res_data.get("description", ""),
                    mime_type=res_data.get("mimeType", ""),
                    server_name=self.name,
                )
                self._resources[resource.uri] = resource

            logger.info(f"Discovered {len(self._resources)} resources from {self.name}")

        except Exception as e:
            logger.warning(f"Failed to fetch resources from {self.name}: {e}")

    async def _fetch_prompts(self) -> None:
        """获取提示列表"""
        if not self._transport:
            return

        try:
            result = await self._transport.send_request("prompts/list")
            prompts = result.get("prompts", [])

            self._prompts.clear()
            for prompt_data in prompts:
                prompt = MCPPrompt(
                    name=prompt_data.get("name", ""),
                    description=prompt_data.get("description", ""),
                    arguments=prompt_data.get("arguments", []),
                    server_name=self.name,
                )
                self._prompts[prompt.name] = prompt

            logger.info(f"Discovered {len(self._prompts)} prompts from {self.name}")

        except Exception as e:
            logger.warning(f"Failed to fetch prompts from {self.name}: {e}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """调用工具"""
        if not self._transport:
            raise MCPError("Not connected")

        if self.status != MCPClientStatus.CONNECTED:
            raise MCPError(f"Client not connected: {self.status}")

        # 从限定名称中提取工具名
        if ":" in tool_name:
            _, tool_name = tool_name.split(":", 1)

        try:
            result = await self._transport.send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments or {},
            })

            return MCPToolResult(
                content=result.get("content", []),
                is_error=result.get("isError", False),
            )

        except Exception as e:
            logger.error(f"Failed to call tool {tool_name}: {e}")
            raise

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """读取资源"""
        if not self._transport:
            raise MCPError("Not connected")

        try:
            result = await self._transport.send_request("resources/read", {"uri": uri})
            return result
        except Exception as e:
            logger.error(f"Failed to read resource {uri}: {e}")
            raise

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> dict[str, Any]:
        """获取提示"""
        if not self._transport:
            raise MCPError("Not connected")

        try:
            result = await self._transport.send_request("prompts/get", {
                "name": name,
                "arguments": arguments or {},
            })
            return result
        except Exception as e:
            logger.error(f"Failed to get prompt {name}: {e}")
            raise

    async def disconnect(self) -> None:
        """断开连接"""
        if self._transport:
            await self._transport.disconnect()
            self._transport = None

        self.status = MCPClientStatus.DISCONNECTED
        logger.info(f"MCP client {self.name} disconnected")


class MCPManager:
    """MCP 管理器 - 管理多个 MCP 客户端"""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._all_tools: dict[str, MCPToolDefinition] = {}

    @property
    def clients(self) -> dict[str, MCPClient]:
        return self._clients.copy()

    @property
    def tools(self) -> dict[str, MCPToolDefinition]:
        return self._all_tools.copy()

    def add_server(self, config: MCPServerConfig) -> MCPClient:
        """添加 MCP 服务器"""
        client = MCPClient(config)
        self._clients[config.name] = client
        return client

    def remove_server(self, name: str) -> None:
        """移除 MCP 服务器"""
        if name in self._clients:
            client = self._clients[name]
            # 移除该服务器的工具
            for tool_name in list(self._all_tools.keys()):
                if self._all_tools[tool_name].server_name == name:
                    del self._all_tools[tool_name]
            del self._clients[name]

    async def connect_all(self) -> dict[str, MCPClientStatus]:
        """连接所有服务器"""
        results: dict[str, MCPClientStatus] = {}

        for name, client in self._clients.items():
            try:
                await client.connect()
                results[name] = client.status

                # 收集工具
                for tool_name, tool in client.tools.items():
                    self._all_tools[tool_name] = tool

            except Exception as e:
                results[name] = MCPClientStatus.ERROR
                logger.error(f"Failed to connect to {name}: {e}")

        return results

    async def connect_server(self, name: str) -> MCPClientStatus:
        """连接指定服务器"""
        if name not in self._clients:
            raise MCPError(f"Server not found: {name}")

        client = self._clients[name]
        try:
            await client.connect()

            # 收集工具
            for tool_name, tool in client.tools.items():
                self._all_tools[tool_name] = tool

            return client.status
        except Exception as e:
            logger.error(f"Failed to connect to {name}: {e}")
            return MCPClientStatus.ERROR

    async def disconnect_all(self) -> None:
        """断开所有服务器"""
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting {client.name}: {e}")

        self._all_tools.clear()

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """调用工具"""
        if qualified_name not in self._all_tools:
            raise MCPError(f"Tool not found: {qualified_name}")

        tool = self._all_tools[qualified_name]
        client = self._clients.get(tool.server_name)

        if not client:
            raise MCPError(f"Server not found: {tool.server_name}")

        return await client.call_tool(tool.name, arguments)

    def get_client(self, name: str) -> MCPClient | None:
        """获取客户端"""
        return self._clients.get(name)

    def get_status(self) -> dict[str, MCPClientStatus]:
        """获取所有客户端状态"""
        return {name: client.status for name, client in self._clients.items()}

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MCPManager":
        """从配置创建管理器"""
        manager = cls()

        for name, server_config in config.items():
            if isinstance(server_config, dict):
                config_obj = MCPServerConfig.from_dict(name, server_config)
                manager.add_server(config_obj)

        return manager

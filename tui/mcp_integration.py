"""
GrassFlow MCP (Model Context Protocol) 客户端集成

参考 hermes 的 MCP 实现架构，为 GrassFlow REPL 提供：
- MCP 服务器配置加载与管理
- stdio / HTTP / SSE 三种传输方式（全部完整实现）
- JSON-RPC 2.0 协议通信
- 动态工具发现（tools/list）
- 工具调用（tools/call）
- 自动重连（指数退避）
- 工具过滤（include / exclude）
- 传输类型自动检测（根据配置字段推断）

设计要点：
- 每个 MCP 服务器对应一个长生命周期 asyncio Task
- 不依赖 mcp 库，使用原生 asyncio + subprocess + httpx
- JSON-RPC 2.0 消息格式（Content-Length 头 + JSON 体用于 stdio）
- MCP 协议版本：2024-11-05

传输类型自动检测规则：
- 配置中存在 "command" 字段 → stdio 传输
- 配置中存在 "url" 字段 → HTTP 传输（Streamable HTTP）
- 配置中存在 "sse_url" 字段 → SSE 传输
- 显式指定 "transport" 字段时优先使用
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from core.tool_registry import (
    MCPToolAdapter,
    ToolDef,
    ToolRegistry,
    ToolSource,
    get_default_registry,
)

logger = logging.getLogger(__name__)

# ==================== stderr 日志 ====================

_mcp_stderr_log_fh = None

def _close_mcp_stderr_log():
    """Close the global MCP stderr log file handle (called via atexit)."""
    global _mcp_stderr_log_fh
    if _mcp_stderr_log_fh is not None:
        try:
            _mcp_stderr_log_fh.close()
        except Exception:
            pass
        _mcp_stderr_log_fh = None

def _get_mcp_stderr_log():
    """Return a file handle for MCP subprocess stderr.
    Falls back to os.devnull if log dir creation fails.
    """
    global _mcp_stderr_log_fh
    if _mcp_stderr_log_fh is not None:
        return _mcp_stderr_log_fh
    try:
        log_dir = Path.home() / '.Grass' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / 'mcp-stderr.log'
        _mcp_stderr_log_fh = open(log_path, 'a', encoding='utf-8', errors='replace', buffering=1)
        _mcp_stderr_log_fh.fileno()  # sanity check
        atexit.register(_close_mcp_stderr_log)
    except Exception:
        try:
            _mcp_stderr_log_fh = open(os.devnull, 'w', encoding='utf-8')
        except Exception:
            _mcp_stderr_log_fh = None
    return _mcp_stderr_log_fh

# ==================== 常量 ====================

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "GrassFlow"
MCP_CLIENT_VERSION = "0.1.0"

MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1.0  # 秒，指数退避基数


# ==================== 传输抽象层 ====================


class _Transport(ABC):
    """MCP 传输抽象基类

    所有传输方式（stdio、HTTP、SSE）的统一接口。
    """

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""

    @abstractmethod
    async def send_jsonrpc(self, message: Dict[str, Any],
                           timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """发送 JSON-RPC 请求并等待响应

        Args:
            message: JSON-RPC 消息（包含 jsonrpc, id, method, params 等）
            timeout: 等待响应的超时时间（秒）

        Returns:
            响应消息字典，超时返回 None。
            对于通知消息（无 id），返回 None 表示已发送。

        Raises:
            MCPConnectionError: 连接异常
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""


class _StdioTransport(_Transport):
    """Stdio 传输实现

    通过子进程的 stdin/stdout 进行 JSON-RPC 通信。
    使用 Content-Length 头 + JSON 体的消息格式。
    """

    def __init__(self, process: asyncio.subprocess.Process):
        self._process = process

    async def connect(self) -> None:
        """stdio 传输在创建子进程时已连接，无需额外操作"""

    async def disconnect(self) -> None:
        """终止子进程"""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None  # type: ignore[assignment]

    async def send_jsonrpc(self, message: Dict[str, Any],
                           timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """通过 stdin 发送 JSON-RPC 消息，从 stdout 读取响应"""
        if self._process is None or self._process.stdin is None:
            raise MCPConnectionError("stdio 传输未连接")

        # 发送消息
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self._process.stdin.write(header + body)
        await self._process.stdin.drain()

        # 如果是通知消息（无 id），不等待响应
        if "id" not in message:
            return None

        # 读取响应
        return await self._read_response(timeout, expected_id=message.get("id"))

    async def _read_response(self, timeout: float,
                             expected_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """从 stdout 读取一条 JSON-RPC 响应"""
        if self._process is None or self._process.stdout is None:
            return None

        loop = asyncio.get_running_loop()
        msg_deadline = loop.time() + timeout

        async def _read_line() -> Optional[bytes]:
            remaining = msg_deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=remaining  # type: ignore[arg-type]
            )
            if not line:
                return None
            return line.rstrip(b"\r\n")

        try:
            while True:
                # 读取 Content-Length 头
                content_length = -1
                while True:
                    line = await _read_line()
                    if line is None:
                        return None
                    if line == b"":
                        break
                    header_str = line.decode("utf-8").strip()
                    if header_str.lower().startswith("content-length:"):
                        content_length = int(header_str.split(":", 1)[1].strip())

                if content_length < 0:
                    logger.warning("收到无 Content-Length 的消息")
                    return None

                # 读取消息体
                body = b""
                remaining = content_length
                while remaining > 0:
                    time_left = msg_deadline - loop.time()
                    if time_left <= 0:
                        raise asyncio.TimeoutError()
                    chunk = await asyncio.wait_for(
                        self._process.stdout.read(remaining), timeout=time_left
                    )
                    if not chunk:
                        return None
                    body += chunk
                    remaining -= len(chunk)

                msg = json.loads(body.decode("utf-8"))

                # 跳过通知消息（无 id 字段），继续读取下一条
                if "id" not in msg:
                    logger.debug("跳过 MCP 通知: %s", msg.get("method", "unknown"))
                    continue

                # 校验响应 id
                if expected_id is not None and msg.get("id") != expected_id:
                    logger.warning(
                        "MCP 响应 id 不匹配: 期望 %d, 收到 %s",
                        expected_id, msg.get("id"),
                    )

                return msg

        except asyncio.TimeoutError:
            logger.warning("读取 MCP 消息超时 (%.1fs)", timeout)
            return None
        except json.JSONDecodeError as exc:
            logger.warning("MCP 消息 JSON 解析失败: %s", exc)
            return None

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None


class _HTTPTransport(_Transport):
    """HTTP 传输实现（Streamable HTTP）

    通过 HTTP POST 发送 JSON-RPC 请求，响应在同一 HTTP 响应中返回。
    支持自定义请求头（如 Authorization）。
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 timeout: float = 30.0):
        self._url = url.rstrip("/")
        self._base_headers = headers or {}
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """创建 HTTP 客户端并验证连接"""
        self._client = httpx.AsyncClient(
            base_url=self._url,
            headers=self._base_headers,
            timeout=httpx.Timeout(self._timeout, read=120.0),
            follow_redirects=True,
        )

    async def disconnect(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_jsonrpc(self, message: Dict[str, Any],
                           timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """通过 HTTP POST 发送 JSON-RPC 请求"""
        if not self._client:
            raise MCPConnectionError("HTTP 传输未连接")

        # 通知消息（无 id）不等待响应
        is_notification = "id" not in message

        try:
            response = await self._client.post(
                "/mcp",
                json=message,
                headers={"Content-Type": "application/json"},
                timeout=httpx.Timeout(timeout, read=120.0),
            )
            response.raise_for_status()

            if is_notification:
                return None

            result = response.json()
            return result

        except httpx.TimeoutException:
            if is_notification:
                logger.debug("HTTP 通知发送超时: %s", message.get("method"))
                return None
            logger.warning("HTTP 请求超时 (%.1fs): %s", timeout, message.get("method"))
            raise MCPConnectionError(
                f"HTTP 请求超时 ({timeout:.1f}s): {message.get('method')}"
            )
        except httpx.HTTPStatusError as exc:
            raise MCPConnectionError(
                f"HTTP 错误 {exc.response.status_code}: {exc.response.text[:200]}"
            )
        except Exception as exc:
            raise MCPConnectionError(f"HTTP 请求失败: {exc}")

    @property
    def is_connected(self) -> bool:
        return self._client is not None and not self._client.is_closed


class _MCPSSETransport(_Transport):
    """SSE (Server-Sent Events) 传输实现

    通过 SSE 端点获取服务端推送的响应和通知。
    请求通过 HTTP POST 发送到从 SSE 流中获取的端点 URL。
    支持自动重连。

    MCP SSE 传输协议流程：
    1. GET 请求 SSE 端点，建立长连接
    2. 服务端通过 SSE 事件推送 endpoint URL
    3. 客户端通过 HTTP POST 向 endpoint URL 发送 JSON-RPC 请求
    4. 服务端通过 SSE 事件推送响应
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 timeout: float = 30.0, sse_read_timeout: float = 300.0):
        self._url = url
        self._base_headers = headers or {}
        self._timeout = timeout
        self._sse_read_timeout = sse_read_timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._endpoint_url: Optional[str] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._request_id = 0
        self._listener_task: Optional[asyncio.Task] = None
        self._connected = False

    async def connect(self) -> None:
        """建立 SSE 连接并获取端点 URL"""
        self._client = httpx.AsyncClient(
            headers=self._base_headers,
            timeout=httpx.Timeout(self._timeout, read=self._sse_read_timeout),
            follow_redirects=True,
        )

        try:
            await self._connect_sse()
            self._connected = True
        except Exception:
            await self._client.aclose()
            self._client = None
            raise

    async def _connect_sse(self) -> None:
        """连接到 SSE 端点，获取 endpoint URL，然后启动监听任务"""
        if not self._client:
            raise MCPConnectionError("SSE HTTP 客户端未创建")

        logger.debug("连接 SSE 端点: %s", self._url)
        try:
            # 读取 endpoint URL（不关闭连接，后续由 listener 复用或重连）
            async with self._client.stream("GET", self._url) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("event: endpoint"):
                        continue
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        # 端点 URL 可能是相对路径或绝对路径
                        if raw.startswith("http://") or raw.startswith("https://"):
                            self._endpoint_url = raw
                        else:
                            # 相对路径，基于 SSE URL 构建完整 URL
                            base = self._url.rstrip("/")
                            self._endpoint_url = base + raw if raw.startswith("/") else base + "/" + raw
                        logger.info("SSE 端点 URL: %s", self._endpoint_url)
                        break

            if not self._endpoint_url:
                raise MCPConnectionError("SSE 端点未返回 endpoint URL")

            # 启动后台监听任务（会建立自己的 SSE 连接）
            self._listener_task = asyncio.create_task(
                self._listen_for_messages(), name="mcp-sse-listener"
            )

        except httpx.HTTPStatusError as exc:
            raise MCPConnectionError(
                f"SSE 连接失败 (HTTP {exc.response.status_code}): {exc.response.text[:200]}"
            )
        except MCPConnectionError:
            raise
        except Exception as exc:
            raise MCPConnectionError(f"SSE 连接失败: {exc}")

    async def _listen_for_messages(self) -> None:
        """后台任务：监听 SSE 流中的消息（指数退避重连）"""
        if not self._client:
            return

        # 基于 sse_read_timeout 计算单次读取超时（至少 60 秒）
        read_timeout = max(60.0, self._sse_read_timeout / 5)
        attempt = 0

        while self._connected:
            try:
                logger.debug("SSE 监听连接: %s", self._url)
                async with self._client.stream(
                    "GET", self._url, timeout=httpx.Timeout(
                        self._timeout, read=read_timeout,
                    ),
                ) as response:
                    response.raise_for_status()
                    # 连接成功，重置重连计数和 endpoint URL
                    attempt = 0
                    current_event = ""
                    async for line in response.aiter_lines():
                        if not self._connected:
                            break
                        if line.startswith("event: "):
                            event_type = line[7:].strip()
                            # 重新读取 endpoint URL（服务器可能轮换）
                            if event_type == "endpoint":
                                current_event = "endpoint"
                            else:
                                current_event = event_type
                        elif line.startswith("data: "):
                            data = line[6:].strip()
                            if current_event == "endpoint":
                                # 更新 endpoint URL
                                if data.startswith("http://") or data.startswith("https://"):
                                    self._endpoint_url = data
                                else:
                                    base = self._url.rstrip("/")
                                    self._endpoint_url = base + data if data.startswith("/") else base + "/" + data
                                logger.debug("SSE endpoint 更新: %s", self._endpoint_url)
                            elif current_event == "message":
                                try:
                                    msg = json.loads(data)
                                    self._handle_message(msg)
                                except json.JSONDecodeError:
                                    logger.warning("SSE 消息 JSON 解析失败: %s", data[:100])
                            current_event = ""

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._connected:
                    break
                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    logger.error("SSE 监听重连 %d 次后放弃: %s", attempt, exc)
                    break
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "SSE 监听异常，%.1fs 后重连 (%d/%d): %s",
                    delay, attempt, MAX_RECONNECT_ATTEMPTS, exc,
                )
                await asyncio.sleep(delay)

    def _handle_message(self, msg: Dict[str, Any]) -> None:
        """处理 SSE 流中收到的消息"""
        msg_id = msg.get("id")
        if msg_id is not None and str(msg_id) in self._pending_requests:
            future = self._pending_requests.pop(str(msg_id))
            if not future.done():
                if "error" in msg:
                    error = msg["error"]
                    future.set_exception(MCPConnectionError(
                        f"JSON-RPC 错误: {error.get('message', error)}"
                    ))
                else:
                    future.set_result(msg)
        elif "method" in msg:
            logger.debug("收到 SSE 通知: %s", msg["method"])

    async def send_jsonrpc(self, message: Dict[str, Any],
                           timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """通过 HTTP POST 发送请求，通过 SSE 流接收响应"""
        if not self._client or not self._endpoint_url:
            raise MCPConnectionError("SSE 传输未连接")

        is_notification = "id" not in message

        # 通知消息直接发送，不等待响应
        if is_notification:
            try:
                await self._client.post(
                    self._endpoint_url,
                    json=message,
                    headers={"Content-Type": "application/json"},
                )
            except Exception as exc:
                logger.warning("SSE 通知发送失败: %s", exc)
            return None

        # 请求消息：注册 Future，发送请求，等待 SSE 流中的响应
        # 仅在调用方未设置 id 时分配新 id
        if "id" not in message:
            self._request_id += 1
            message["id"] = str(self._request_id)
        request_id = str(message["id"])

        future: asyncio.Future[Dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            await self._client.post(
                self._endpoint_url,
                json=message,
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:
            self._pending_requests.pop(request_id, None)
            raise MCPConnectionError(f"SSE 请求发送失败: {exc}")

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            logger.warning("SSE 请求超时 (%.1fs): %s", timeout, message.get("method"))
            return None

    async def disconnect(self) -> None:
        """断开 SSE 连接"""
        self._connected = False

        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        # 清理未完成的请求
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(MCPConnectionError("SSE 连接已关闭"))
        self._pending_requests.clear()

        self._endpoint_url = None
        logger.debug("SSE 传输已断开")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None


# ==================== 数据模型 ====================


@dataclass
class MCPServerConfig:
    """单个 MCP 服务器的配置

    传输类型自动检测规则（当 transport 未显式指定时）：
    - 存在 "command" 字段 → stdio
    - 存在 "url" 字段 → http
    - 存在 "sse_url" 字段 → sse
    显式指定 "transport" 字段时优先使用。
    """

    name: str
    # stdio 传输
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    # HTTP / SSE 传输
    url: Optional[str] = None
    sse_url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    # 通用配置
    transport: str = "auto"  # auto / stdio / http / sse
    timeout: int = 120
    connect_timeout: int = 60
    keepalive_interval: int = 10
    enabled: bool = True
    # 工具过滤
    tools_include: Optional[List[str]] = None
    tools_exclude: Optional[List[str]] = None

    @property
    def effective_transport(self) -> str:
        """获取实际使用的传输类型（解析 auto 检测）"""
        _VALID_TRANSPORTS = {"stdio", "http", "sse"}
        if self.transport != "auto":
            if self.transport not in _VALID_TRANSPORTS:
                logger.warning(
                    "MCP 服务器 %r 指定了无效传输类型 %r，回退为 auto 检测",
                    self.name, self.transport,
                )
            else:
                return self.transport
        # 自动检测
        if self.sse_url:
            return "sse"
        if self.url:
            return "http"
        if self.command:
            return "stdio"
        return "stdio"  # 默认 fallback

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否被过滤规则允许"""
        if self.tools_include is not None:
            return tool_name in self.tools_include
        if self.tools_exclude is not None:
            return tool_name not in self.tools_exclude
        return True


@dataclass
class MCPTool:
    """从 MCP 服务器发现的工具"""

    name: str  # 格式: mcp_{server}_{tool}
    server_name: str
    description: str
    input_schema: Dict[str, Any]
    enabled: bool = True


@dataclass
class _ServerState:
    """MCP 服务器的运行时状态（内部使用）"""

    config: MCPServerConfig
    process: Optional[asyncio.subprocess.Process] = None
    transport: Optional[_Transport] = None
    task: Optional[asyncio.Task] = None
    tools: Dict[str, MCPTool] = field(default_factory=dict)
    request_id: int = 0
    connected: bool = False
    stopping: bool = False
    started: bool = False
    error_message: Optional[str] = None
    rpc_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connected_event: asyncio.Event = field(default_factory=asyncio.Event)

    def next_request_id(self) -> int:
        self.request_id += 1
        return self.request_id


# ==================== 异常 ====================


class MCPError(Exception):
    """MCP 通信异常"""


class MCPConnectionError(MCPError):
    """MCP 连接异常"""


class MCPToolCallError(MCPError):
    """MCP 工具调用异常"""


# ==================== MCP 管理器 ====================


class MCPManager:
    """MCP 服务器管理器

    负责：
    - 从配置字典加载 MCP 服务器定义
    - 启动 / 停止所有服务器进程
    - 工具发现与注册
    - 工具调用代理
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = config_dir
        self._servers: Dict[str, _ServerState] = {}
        self._on_ready_callback: Optional[Callable[[], None]] = None

    def set_on_ready_callback(self, callback: Callable[[], None]) -> None:
        """Set a callback to be invoked when all MCP servers have connected and
        their tools have been registered into the ToolRegistry.

        The callback fires once after start_all() completes its wait phase, and
        again each time a late-connecting server finishes its handshake.
        """
        self._on_ready_callback = callback

    # -------------------- 配置 --------------------

    def load_config(self, config: Dict[str, Any]) -> None:
        """从配置字典加载 mcp_servers

        Args:
            config: 完整配置字典，需包含 mcp_servers 键。
                    支持的配置格式：

                    stdio 传输:
                    {
                        "filesystem": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                        }
                    }

                    HTTP 传输:
                    {
                        "remote-server": {
                            "url": "http://localhost:8000/mcp",
                            "headers": {"Authorization": "Bearer xxx"},
                            "transport": "http"
                        }
                    }

                    SSE 传输:
                    {
                        "sse-server": {
                            "sse_url": "http://localhost:8000/sse",
                            "transport": "sse"
                        }
                    }

                    自动检测（推荐）:
                    {
                        "server1": {"command": "npx", "args": [...]},
                        "server2": {"url": "http://localhost:8000/mcp"},
                        "server3": {"sse_url": "http://localhost:8000/sse"}
                    }
        """
        mcp_servers = config.get("mcp_servers", {})
        if not isinstance(mcp_servers, dict):
            logger.warning("mcp_servers 配置格式错误，期望 dict，得到 %s", type(mcp_servers).__name__)
            return

        for name, srv_cfg in mcp_servers.items():
            if not isinstance(srv_cfg, dict):
                logger.warning("MCP 服务器 %r 配置格式错误，跳过", name)
                continue

            # 兼容 "mcpServers" 格式（与 hermes/opencode 一致）
            server_config = MCPServerConfig(
                name=name,
                command=srv_cfg.get("command"),
                args=srv_cfg.get("args", []),
                env=srv_cfg.get("env", {}),
                cwd=srv_cfg.get("cwd"),
                url=srv_cfg.get("url"),
                sse_url=srv_cfg.get("sse_url"),
                headers=srv_cfg.get("headers", {}),
                transport=srv_cfg.get("transport", "auto"),
                timeout=srv_cfg.get("timeout", 120),
                connect_timeout=srv_cfg.get("connect_timeout", 60),
                keepalive_interval=srv_cfg.get("keepalive_interval", 10),
                enabled=srv_cfg.get("enabled", True),
                tools_include=srv_cfg.get("tools_include"),
                tools_exclude=srv_cfg.get("tools_exclude"),
            )

            if not server_config.enabled:
                logger.info("MCP 服务器 %r 已禁用，跳过", name)
                continue

            effective = server_config.effective_transport

            # 校验必要字段
            if effective == "stdio" and not server_config.command:
                logger.warning("MCP 服务器 %r 使用 stdio 传输但未指定 command，跳过", name)
                continue
            if effective == "http" and not server_config.url:
                logger.warning("MCP 服务器 %r 使用 http 传输但未指定 url，跳过", name)
                continue
            if effective == "sse" and not server_config.sse_url:
                logger.warning("MCP 服务器 %r 使用 sse 传输但未指定 sse_url，跳过", name)
                continue

            self._servers[name] = _ServerState(config=server_config)
            logger.info("已加载 MCP 服务器配置: %r (transport=%s)", name, effective)

    # -------------------- 生命周期 --------------------

    async def start_all(self) -> None:
        """启动所有已启用的 MCP 服务器

        启动流程：
        1. 为每个启用的服务器创建后台任务 (_run_server_loop)
        2. 等待每个服务器的 connected_event（握手 + 工具发现完成）
        3. 注册已发现的 MCP 工具到 ToolRegistry
        4. 触发 on_ready 回调（如果有）
        """
        if not self._servers:
            logger.info("没有配置 MCP 服务器")
            return

        tasks = []
        for name, state in self._servers.items():
            if state.config.enabled:
                state.connected_event.clear()
                task = asyncio.create_task(
                    self._run_server_loop(name),
                    name=f"mcp-server-{name}",
                )
                state.task = task
                tasks.append(task)

        if tasks:
            # Wait for each server's connected_event (set after handshake +
            # tool discovery), with a per-server timeout.
            connect_timeout = 15.0
            events = [
                state.connected_event
                for state in self._servers.values()
                if state.config.enabled
            ]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[e.wait() for e in events], return_exceptions=True),
                    timeout=connect_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "MCP servers did not all connect within %.0fs — "
                    "remaining servers will register tools as they connect",
                    connect_timeout,
                )

            # Count how many servers actually connected
            connected = sum(
                1 for state in self._servers.values()
                if state.connected_event.is_set()
            )
            total = len(tasks)
            logger.info("MCP 服务器启动完成: %d/%d 已连接", connected, total)

            # Register all currently discovered MCP tools into the ToolRegistry.
            # _run_server_loop already calls this per-server, but we do a
            # catch-all pass here in case any were missed.
            self.register_tools_to_registry()

            # Fire the on-ready callback so the REPL can update its state
            if self._on_ready_callback:
                try:
                    self._on_ready_callback()
                except Exception as cb_err:
                    logger.warning("MCP on_ready callback error: %s", cb_err)

    async def stop_all(self) -> None:
        """停止所有 MCP 服务器"""
        for name in list(self._servers.keys()):
            await self._stop_server(name)

    # -------------------- 服务器生命周期（内部） --------------------

    async def _run_server_loop(self, name: str) -> None:
        """单个 MCP 服务器的主循环（含自动重连）"""
        state = self._servers.get(name)
        if not state:
            return

        config = state.config
        attempt = 0
        state.started = True

        while attempt < MAX_RECONNECT_ATTEMPTS and not state.stopping:
            try:
                transport_type = config.effective_transport

                if transport_type == "stdio":
                    await self._start_stdio_server(name, config)
                elif transport_type in ("http", "sse"):
                    await self._start_remote_server(name, config, transport_type)
                else:
                    logger.error("不支持的 MCP 传输类型: %r", transport_type)
                    return

                # 连接成功，重置重连计数
                attempt = 0
                state.connected = True
                state.error_message = None

                # Register tools immediately after handshake+discovery completes.
                # This ensures tools are in the registry before start_all() returns.
                self.register_tools_to_registry()

                # Signal that this server is connected and tools are registered.
                # start_all() waits for this event before returning.
                if not state.connected_event.is_set():
                    state.connected_event.set()

                # 等待连接结束（或被停止）
                if state.process:
                    # stdio 传输：等待子进程退出
                    await state.process.wait()
                else:
                    # HTTP/SSE 传输：等待停止信号
                    while not state.stopping and state.transport and state.transport.is_connected:
                        await asyncio.sleep(1.0)

                state.connected = False

                if state.stopping:
                    break

                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    state.error_message = "连接反复断开，重连失败"
                    logger.error("MCP 服务器 %r 连接反复断开，重连 %d 次后放弃", name, attempt)
                    break
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("MCP 服务器 %r 连接断开，%.1fs 后重连 (%d/%d)", name, delay, attempt, MAX_RECONNECT_ATTEMPTS)
                await asyncio.sleep(delay)

            except Exception as exc:
                state.connected = False
                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    state.error_message = str(exc)
                    logger.error("MCP 服务器 %r 重连 %d 次后放弃: %s", name, attempt, exc)
                    break
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("MCP 服务器 %r 连接失败 (%d/%d)，%.1fs 后重试: %s",
                               name, attempt, MAX_RECONNECT_ATTEMPTS, delay, exc)
                await asyncio.sleep(delay)

    async def _start_stdio_server(self, name: str, config: MCPServerConfig) -> None:
        """通过 stdio 启动 MCP 服务器子进程"""
        command = config.command
        if not command:
            raise MCPConnectionError(f"服务器 {name!r} 未指定 command")

        # 在 PATH 中查找可执行文件
        if not Path(command).is_absolute():
            resolved = shutil.which(command)
            if resolved:
                command = resolved

        cmd_parts = [command] + config.args
        # 只记录命令名，不记录参数（参数可能含 API key 等敏感信息）
        logger.info("启动 MCP 服务器 %r: %s", name, command)

        # 合并环境变量
        env = os.environ.copy()
        env.update(config.env)

        errlog = _get_mcp_stderr_log()
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=errlog if errlog is not None else asyncio.subprocess.DEVNULL,
            env=env,
            cwd=config.cwd,
        )

        state = self._servers[name]
        state.process = process
        state.transport = _StdioTransport(process)

        try:
            # MCP 握手：initialize -> notifications/initialized
            await self._do_handshake(name, state.transport, config)

            # 工具发现
            await self._discover_tools(name, state.transport, config)
        except Exception:
            # Kill leaked process on handshake/discovery failure
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except Exception:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            state.process = None
            state.transport = None
            raise

        logger.info("MCP 服务器 %r 就绪，发现 %d 个工具", name, len(state.tools))

    async def _start_remote_server(self, name: str, config: MCPServerConfig,
                                   transport_type: str) -> None:
        """通过 HTTP 或 SSE 启动 MCP 服务器

        Args:
            name: 服务器名称
            config: 服务器配置
            transport_type: 传输类型 ("http" 或 "sse")
        """
        state = self._servers[name]

        if transport_type == "http":
            url = config.url
            if not url:
                raise MCPConnectionError(f"服务器 {name!r} 未指定 url")
            transport = _HTTPTransport(
                url=url,
                headers=config.headers or None,
                timeout=float(config.connect_timeout),
            )
            logger.info("连接 MCP 服务器 %r (HTTP): %s", name, url)
        elif transport_type == "sse":
            sse_url = config.sse_url
            if not sse_url:
                raise MCPConnectionError(f"服务器 {name!r} 未指定 sse_url")
            transport = _MCPSSETransport(
                url=sse_url,
                headers=config.headers or None,
                timeout=float(config.connect_timeout),
            )
            logger.info("连接 MCP 服务器 %r (SSE): %s", name, sse_url)
        else:
            raise MCPConnectionError(f"不支持的远程传输类型: {transport_type}")

        state.transport = transport

        try:
            await transport.connect()

            # MCP 握手
            await self._do_handshake(name, transport, config)

            # 工具发现
            await self._discover_tools(name, transport, config)
        except Exception:
            await transport.disconnect()
            state.transport = None
            raise

        logger.info("MCP 服务器 %r 就绪 (%s)，发现 %d 个工具",
                     name, transport_type, len(state.tools))

    async def _stop_server(self, name: str) -> None:
        """停止单个 MCP 服务器"""
        state = self._servers.get(name)
        if not state:
            return

        state.stopping = True

        # 断开传输连接
        if state.transport:
            try:
                await state.transport.disconnect()
            except Exception as exc:
                logger.warning("MCP 服务器 %r 传输断开异常: %s", name, exc)
            state.transport = None

        # 终止子进程（stdio 传输额外保障）
        if state.process and state.process.returncode is None:
            try:
                state.process.terminate()
                try:
                    await asyncio.wait_for(state.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    state.process.kill()
                    await state.process.wait()
            except ProcessLookupError:
                pass

        # 取消任务
        if state.task and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass

        state.connected = False
        state.process = None
        state.task = None
        logger.info("MCP 服务器 %r 已停止", name)

    # -------------------- JSON-RPC 协议 --------------------

    async def _do_handshake(self, name: str, transport: _Transport,
                            config: MCPServerConfig) -> None:
        """执行 MCP 握手：initialize + notifications/initialized"""
        state = self._servers[name]

        # 1) 发送 initialize 请求
        init_request = {
            "jsonrpc": "2.0",
            "id": state.next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": MCP_CLIENT_NAME,
                    "version": MCP_CLIENT_VERSION,
                },
            },
        }
        async with state.rpc_lock:
            response = await transport.send_jsonrpc(
                init_request, timeout=config.connect_timeout
            )
        if response is None:
            raise MCPConnectionError(f"服务器 {name!r} initialize 无响应")
        if "error" in response:
            raise MCPConnectionError(
                f"服务器 {name!r} initialize 失败: {response['error']}"
            )

        logger.debug("MCP 服务器 %r initialize 响应: %s", name,
                      json.dumps(response.get("result", {}), ensure_ascii=False)[:200])

        # 2) 发送 notifications/initialized
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        async with state.rpc_lock:
            await transport.send_jsonrpc(initialized_notification)
        logger.debug("MCP 服务器 %r 握手完成", name)

    async def _discover_tools(self, name: str, transport: _Transport,
                              config: MCPServerConfig) -> None:
        """通过 tools/list 发现服务器提供的工具"""
        state = self._servers[name]
        state.tools.clear()  # Clear stale tools before rediscovery

        list_request = {
            "jsonrpc": "2.0",
            "id": state.next_request_id(),
            "method": "tools/list",
        }
        async with state.rpc_lock:
            response = await transport.send_jsonrpc(
                list_request, timeout=config.timeout
            )
        if response is None:
            logger.warning("MCP 服务器 %r tools/list 无响应", name)
            return
        if "error" in response:
            logger.warning("MCP 服务器 %r tools/list 失败: %s", name, response["error"])
            return

        result = response.get("result", {})
        tools_list = result.get("tools", [])

        for tool_def in tools_list:
            tool_name_raw = tool_def.get("name", "")
            if not tool_name_raw:
                continue

            # 检查过滤规则
            if not config.is_tool_allowed(tool_name_raw):
                logger.debug("MCP 工具 %s/%s 被过滤规则排除", name, tool_name_raw)
                continue

            # 注册工具，名称格式: mcp_{server}_{tool}
            qualified_name = f"mcp_{name}_{tool_name_raw}"
            tool = MCPTool(
                name=qualified_name,
                server_name=name,
                description=tool_def.get("description", ""),
                input_schema=tool_def.get("inputSchema", {}),
                enabled=True,
            )
            state.tools[qualified_name] = tool

        logger.debug("MCP 服务器 %r 发现工具: %s", name,
                      [t.name for t in state.tools.values()])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用 MCP 工具

        Args:
            tool_name: 工具名称（格式: mcp_{server}_{tool}）
            arguments: 工具参数

        Returns:
            工具返回的 result 内容

        Raises:
            MCPToolCallError: 工具调用失败
            MCPConnectionError: 服务器未连接
        """
        # 查找工具所在的服务器
        target_state: Optional[_ServerState] = None
        for state in self._servers.values():
            if tool_name in state.tools:
                target_state = state
                break

        if target_state is None:
            raise MCPToolCallError(f"未找到工具: {tool_name}")

        if not target_state.connected or target_state.transport is None:
            raise MCPConnectionError(
                f"MCP 服务器 {target_state.config.name!r} 未连接"
            )

        tool = target_state.tools[tool_name]
        # 去掉 mcp_{server}_ 前缀，得到原始工具名
        raw_tool_name = tool.name[len(f"mcp_{tool.server_name}_"):]

        call_request = {
            "jsonrpc": "2.0",
            "id": target_state.next_request_id(),
            "method": "tools/call",
            "params": {
                "name": raw_tool_name,
                "arguments": arguments,
            },
        }

        async with target_state.rpc_lock:
            response = await target_state.transport.send_jsonrpc(
                call_request, timeout=target_state.config.timeout
            )
        if response is None:
            raise MCPToolCallError(f"工具 {tool_name} 调用超时")
        if "error" in response:
            error = response["error"]
            raise MCPToolCallError(
                f"工具 {tool_name} 调用失败: {error.get('message', error)}"
            )

        return response.get("result", {})

    # -------------------- 查询接口 --------------------

    def get_all_tools(self) -> List[MCPTool]:
        """获取所有已发现的工具"""
        tools: List[MCPTool] = []
        for state in self._servers.values():
            tools.extend(state.tools.values())
        return tools

    def register_tools_to_registry(self, registry: Optional[ToolRegistry] = None) -> int:
        """Register all discovered MCP tools into the ToolRegistry.
        Returns the number of tools registered.
        """
        if registry is None:
            registry = get_default_registry()

        count = 0
        for state in self._servers.values():
            for tool in state.tools.values():
                if registry.has(tool.name):
                    continue
                adapter = MCPToolAdapter(
                    server_name=tool.server_name,
                    tool_id=tool.name,
                    description=tool.description,
                    parameters=tool.input_schema,
                    mcp_client=self,
                )
                tool_def = adapter.to_tool_def()
                try:
                    registry.register_tool_def(tool_def)
                    count += 1
                except Exception as e:
                    logger.warning("Failed to register MCP tool %s: %s", tool.name, e)
        logger.info("Registered %d MCP tools into ToolRegistry", count)
        return count

    def get_tool(self, tool_name: str) -> Optional[MCPTool]:
        """按名称获取工具"""
        for state in self._servers.values():
            tool = state.tools.get(tool_name)
            if tool is not None:
                return tool
        return None

    def get_server_status(self, name: str) -> Optional[Dict[str, Any]]:
        """获取单个服务器的状态"""
        state = self._servers.get(name)
        if state is None:
            return None
        return {
            "name": name,
            "transport": state.config.effective_transport,
            "connected": state.connected,
            "tools_count": len(state.tools),
            "tools": [t.name for t in state.tools.values()],
        }

    def get_tools_summary(self) -> str:
        """生成用于 /mcp 命令的工具摘要文本"""
        if not self._servers:
            return "  No MCP servers configured."

        lines: List[str] = []
        lines.append("  MCP servers:")
        lines.append("")

        for name, state in self._servers.items():
            transport = state.config.effective_transport
            if state.connected:
                status_icon = "✅"
                status_text = "connected"
            elif state.started and state.error_message:
                status_icon = "❌"
                status_text = f"failed: {state.error_message}"
            elif state.started:
                status_icon = "❌"
                status_text = "failed"
            else:
                status_icon = "⏳"
                status_text = "not started"

            lines.append(f"    {status_icon} {name} ({transport}) - {status_text}")

            if state.tools:
                for tool in state.tools.values():
                    desc = tool.description[:60] + "..." if len(tool.description) > 60 else tool.description
                    lines.append(f"       - {tool.name}: {desc}")

        total_tools = sum(len(s.tools) for s in self._servers.values())
        connected = sum(1 for s in self._servers.values() if s.connected)
        lines.append("")
        lines.append(f"  {len(self._servers)} servers total, {connected} connected, {total_tools} tools")

        return "\n".join(lines)

    @property
    def is_running(self) -> bool:
        """是否有任何服务器正在运行"""
        return any(s.connected for s in self._servers.values())

    @property
    def server_names(self) -> List[str]:
        """所有已配置的服务器名称"""
        return list(self._servers.keys())

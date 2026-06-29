"""
GrassFlow MCP (Model Context Protocol) 客户端集成

使用官方 mcp Python SDK 提供：
- MCP 服务器配置加载与管理
- stdio / HTTP / SSE 三种传输方式（基于 mcp SDK）
- 动态工具发现（tools/list）
- 工具调用（tools/call）
- 自动重连（指数退避）
- 工具过滤（include / exclude）
- 传输类型自动检测（根据配置字段推断）

设计要点：
- 每个 MCP 服务器对应一个 _MCPServer 实例 + 长生命周期 asyncio Task
- 使用 mcp SDK 的 stdio_client / streamablehttp_client / sse_client 传输
- 通过 ClientSession 管理握手、工具发现和工具调用

传输类型自动检测规则：
- 配置中存在 "command" 字段 → stdio 传输
- 配置中存在 "url" 字段 → HTTP 传输（Streamable HTTP）
- 配置中存在 "sse_url" 字段 → SSE 传输
- 显式指定 "transport" 字段时优先使用
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import logging
import os
import shutil
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client

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

# Circuit breaker 常量
BREAKER_THRESHOLD = 3      # 连续失败次数触发熔断
BREAKER_COOLDOWN = 60.0    # 冷却时间（秒）

# 安全环境变量白名单（只传递这些变量到子进程，防止泄露 secrets）
_SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR",
})

_SAFE_ENV_KEYS_CASE_INSENSITIVE = frozenset({
    # Windows process/location vars
    "ALLUSERSPROFILE",
    "APPDATA",
    "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)",
    "COMMONPROGRAMW6432",
    "COMPUTERNAME",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PUBLIC",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
})


# ==================== 安全辅助函数 ====================


def _build_safe_env(user_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """构建过滤后的环境变量字典，用于 stdio 子进程。

    只传递安全的基础变量（PATH、HOME 等）和 XDG_* 变量，
    加上用户在服务器配置中显式指定的 env。
    防止意外泄露 API key、token 等 secrets 到 MCP 子进程。
    """
    env: Dict[str, str] = {}
    for key, value in os.environ.items():
        if (
            key in _SAFE_ENV_KEYS
            or key.upper() in _SAFE_ENV_KEYS_CASE_INSENSITIVE
            or key.startswith("XDG_")
        ):
            env[key] = value
    if user_env:
        env.update(user_env)
    return env


def _resolve_command(command: str, env: Dict[str, str]) -> tuple[str, Dict[str, str]]:
    """解析 stdio MCP 命令路径，支持 npx/npm/node 和 Windows .cmd 扩展名。

    主要确保存 bare ``npx``/``npm``/``node`` 命令在过滤 PATH 后仍能正常工作。
    """
    resolved_command = os.path.expanduser(str(command).strip())
    resolved_env = dict(env or {})

    if os.sep not in resolved_command and "/" not in resolved_command:
        path_arg = resolved_env.get("PATH")
        which_hit = shutil.which(resolved_command, path=path_arg)
        if which_hit:
            resolved_command = which_hit
        elif resolved_command in {"npx", "npm", "node"}:
            # 在常见位置查找 Node 工具
            home = os.path.expanduser("~")
            candidates = [
                os.path.join(home, ".local", "bin", resolved_command),
                os.path.join(os.sep, "usr", "local", "bin", resolved_command),
            ]
            # Windows: 尝试 .cmd 扩展名
            if os.name == "nt":
                for candidate in list(candidates):
                    candidates.append(candidate + ".cmd")
                # npm 全局安装路径
                appdata = os.environ.get("APPDATA", "")
                if appdata:
                    npm_global = os.path.join(appdata, "npm", resolved_command)
                    candidates.append(npm_global)
                    candidates.append(npm_global + ".cmd")

            for candidate in candidates:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    resolved_command = candidate
                    break

    # 将命令所在目录加入 PATH（确保子进程能找到同目录的 node 等）
    command_dir = os.path.dirname(resolved_command)
    if command_dir and "PATH" in resolved_env:
        existing = resolved_env.get("PATH", "")
        if command_dir not in existing.split(os.pathsep):
            resolved_env["PATH"] = command_dir + os.pathsep + existing

    return resolved_command, resolved_env


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


# ==================== 异常 ====================


class MCPError(Exception):
    """MCP 通信异常"""


class MCPConnectionError(MCPError):
    """MCP 连接异常"""


class MCPToolCallError(MCPError):
    """MCP 工具调用异常"""


# ==================== MCP 服务器实例 ====================


class _MCPServer:
    """单个 MCP 服务器的运行时实例

    封装了与 MCP 服务器的完整生命周期：
    连接 → 握手 → 工具发现 → 工具调用 → 断开
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools: Dict[str, MCPTool] = {}
        self.connected: bool = False
        self.started: bool = False
        self.stopping: bool = False
        self.error_message: Optional[str] = None
        self._ready: asyncio.Event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        # RPC 序列化锁 — 防止并发 stdio 调用交错 JSON-RPC 消息
        self._rpc_lock: asyncio.Lock = asyncio.Lock()
        # Circuit breaker 状态
        self.failure_count: int = 0
        self.breaker_open: bool = False
        self.breaker_opened_at: float = 0.0

    async def start(self) -> None:
        """启动服务器，根据 transport 类型分发到对应的运行方法"""
        self.started = True
        transport = self.config.effective_transport
        try:
            if transport == "stdio":
                await self._run_stdio()
            elif transport == "http":
                await self._run_http()
            elif transport == "sse":
                await self._run_sse()
            else:
                raise MCPConnectionError(f"不支持的传输类型: {transport}")
        except Exception as exc:
            self.error_message = str(exc)
            self.connected = False
            raise

    async def _run_stdio(self) -> None:
        """使用 mcp SDK 的 stdio_client 运行 stdio 传输"""
        command = self.config.command
        if not command:
            raise MCPConnectionError(f"服务器 {self.config.name!r} 未指定 command")

        safe_env = _build_safe_env(self.config.env or None)
        command, safe_env = _resolve_command(command, safe_env)

        server_params = StdioServerParameters(
            command=command,
            args=self.config.args,
            env=safe_env if safe_env else None,
        )

        errlog = _get_mcp_stderr_log()
        logger.info("启动 MCP 服务器 %r (stdio): %s", self.config.name, command)

        async with stdio_client(server_params, errlog=errlog) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                self.session = session
                await session.initialize()
                await self._discover_tools()
                self.connected = True
                self._ready.set()
                logger.info(
                    "MCP 服务器 %r 就绪，发现 %d 个工具",
                    self.config.name, len(self.tools),
                )
                # 保持运行直到被停止
                await self._wait_until_stopped()

        self.connected = False

    async def _run_http(self) -> None:
        """使用 mcp SDK 的 streamablehttp_client 运行 HTTP 传输"""
        url = self.config.url
        if not url:
            raise MCPConnectionError(f"服务器 {self.config.name!r} 未指定 url")

        headers = dict(self.config.headers) if self.config.headers else {}
        logger.info("连接 MCP 服务器 %r (HTTP): %s", self.config.name, url)

        async with streamablehttp_client(url, headers=headers or None) as (read, write, _):
            async with ClientSession(read, write) as session:
                self.session = session
                await session.initialize()
                await self._discover_tools()
                self.connected = True
                self._ready.set()
                logger.info(
                    "MCP 服务器 %r 就绪 (HTTP)，发现 %d 个工具",
                    self.config.name, len(self.tools),
                )
                await self._wait_until_stopped()

        self.connected = False

    async def _run_sse(self) -> None:
        """使用 mcp SDK 的 sse_client 运行 SSE 传输"""
        sse_url = self.config.sse_url
        if not sse_url:
            raise MCPConnectionError(f"服务器 {self.config.name!r} 未指定 sse_url")

        headers = dict(self.config.headers) if self.config.headers else {}
        logger.info("连接 MCP 服务器 %r (SSE): %s", self.config.name, sse_url)

        async with sse_client(sse_url, headers=headers or None) as (read, write):
            async with ClientSession(read, write) as session:
                self.session = session
                await session.initialize()
                await self._discover_tools()
                self.connected = True
                self._ready.set()
                logger.info(
                    "MCP 服务器 %r 就绪 (SSE)，发现 %d 个工具",
                    self.config.name, len(self.tools),
                )
                await self._wait_until_stopped()

        self.connected = False

    async def _wait_until_stopped(self) -> None:
        """阻塞直到 stop() 被调用"""
        await self._stop_event.wait()

    async def _discover_tools(self) -> None:
        """使用 mcp SDK 的 session.list_tools() 发现工具"""
        if self.session is None:
            return

        self.tools.clear()
        tools_result = await self.session.list_tools()
        tools_list = tools_result.tools if hasattr(tools_result, "tools") else []

        for tool_def in tools_list:
            tool_name_raw = tool_def.name if hasattr(tool_def, "name") else ""
            if not tool_name_raw:
                continue

            # 检查过滤规则
            if not self.config.is_tool_allowed(tool_name_raw):
                logger.debug(
                    "MCP 工具 %s/%s 被过滤规则排除",
                    self.config.name, tool_name_raw,
                )
                continue

            # 注册工具，名称格式: mcp_{server}_{tool}
            qualified_name = f"mcp_{self.config.name}_{tool_name_raw}"
            description = tool_def.description if hasattr(tool_def, "description") else ""
            input_schema = (
                tool_def.inputSchema
                if hasattr(tool_def, "inputSchema")
                else {}
            )

            tool = MCPTool(
                name=qualified_name,
                server_name=self.config.name,
                description=description or "",
                input_schema=input_schema or {},
                enabled=True,
            )
            self.tools[qualified_name] = tool

        logger.debug(
            "MCP 服务器 %r 发现工具: %s",
            self.config.name, [t.name for t in self.tools.values()],
        )

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用 MCP 工具

        Args:
            tool_name: 完整工具名（格式: mcp_{server}_{tool}）
            arguments: 工具参数

        Returns:
            工具返回的结果

        Raises:
            MCPToolCallError: 工具调用失败
            MCPConnectionError: 服务器未连接
        """
        # Circuit breaker 检查
        if self.breaker_open:
            import time
            elapsed = time.monotonic() - self.breaker_opened_at
            if elapsed < BREAKER_COOLDOWN:
                raise MCPToolCallError(
                    f"server unreachable — circuit breaker open "
                    f"(cooldown {BREAKER_COOLDOWN - elapsed:.0f}s remaining)"
                )
            # 冷却期已过，设为 half-open（允许一次尝试）
            logger.info(
                "MCP 服务器 %r circuit breaker half-open，允许一次尝试",
                self.config.name,
            )

        if self.session is None or not self.connected:
            raise MCPConnectionError(
                f"MCP 服务器 {self.config.name!r} 未连接"
            )

        tool = self.tools.get(tool_name)
        if tool is None:
            raise MCPToolCallError(f"未找到工具: {tool_name}")

        # 去掉 mcp_{server}_ 前缀，得到原始工具名
        raw_tool_name = tool_name[len(f"mcp_{self.config.name}_"):]

        try:
            async with self._rpc_lock:
                result = await asyncio.wait_for(
                    self.session.call_tool(raw_tool_name, arguments),
                    timeout=self.config.timeout,
                )
        except asyncio.TimeoutError:
            self._record_failure()
            raise MCPToolCallError(
                f"工具 {tool_name} 调用超时 ({self.config.timeout}s)"
            )
        except Exception as exc:
            self._record_failure()
            raise MCPToolCallError(f"工具 {tool_name} 调用失败: {exc}")

        # MCP CallToolResult 有 .content 和 .isError 属性
        if hasattr(result, "isError") and result.isError:
            error_text = ""
            for block in (result.content or []):
                if hasattr(block, "text"):
                    error_text += block.text
            self._record_failure()
            raise MCPToolCallError(
                f"工具 {tool_name} 返回错误: {error_text or 'unknown error'}"
            )

        # 调用成功，重置 circuit breaker
        self._record_success()

        # 提取内容
        if hasattr(result, "content"):
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    parts.append(f"[{getattr(block, 'type', 'binary')} data]")
            return "\n".join(parts) if parts else str(result)

        return result

    def _record_success(self) -> None:
        """记录调用成功，重置 circuit breaker 状态"""
        self.failure_count = 0
        if self.breaker_open:
            logger.info(
                "MCP 服务器 %r circuit breaker 已关闭（调用成功）",
                self.config.name,
            )
        self.breaker_open = False

    def _record_failure(self) -> None:
        """记录调用失败，检查是否需要打开 circuit breaker"""
        import time
        self.failure_count += 1
        if self.failure_count >= BREAKER_THRESHOLD and not self.breaker_open:
            self.breaker_open = True
            self.breaker_opened_at = time.monotonic()
            logger.warning(
                "MCP 服务器 %r circuit breaker 已打开（连续失败 %d 次），"
                "冷却 %.0f 秒后重试",
                self.config.name, self.failure_count, BREAKER_COOLDOWN,
            )

    def reset_breaker(self) -> None:
        """手动重置 circuit breaker 状态"""
        self.failure_count = 0
        self.breaker_open = False
        self.breaker_opened_at = 0.0
        logger.info("MCP 服务器 %r circuit breaker 已手动重置", self.config.name)

    async def stop(self) -> None:
        """停止服务器"""
        self.stopping = True
        self._stop_event.set()

        # 取消后台任务
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self.connected = False
        self.session = None
        logger.info("MCP 服务器 %r 已停止", self.config.name)


# ==================== MCP 管理器 ====================


class MCPManager:
    """MCP 服务器管理器

    负责：
    - 从配置字典加载 MCP 服务器定义
    - 启动 / 停止所有服务器进程
    - 工具发现与注册
    - 工具调用代理
    """

    def __init__(self, config_dir: Optional[Path] = None,
                 startup_timeout: float = 30.0) -> None:
        self._config_dir = config_dir
        self._servers: Dict[str, _MCPServer] = {}
        self._on_ready_callback: Optional[Callable[[], None]] = None
        self._startup_timeout = startup_timeout
        # 收集启动阶段的错误（服务器名 → 错误信息）
        self._startup_errors: Dict[str, str] = {}
        # MCP 专用事件循环引用（由 agent_integration 设置）
        self._mcp_loop: Optional[asyncio.AbstractEventLoop] = None

    def set_on_ready_callback(self, callback: Callable[[], None]) -> None:
        """Set a callback to be invoked when all MCP servers have connected and
        their tools have been registered into the ToolRegistry.

        The callback fires once after start_all() completes its wait phase, and
        again each time a late-connecting server finishes its handshake.
        """
        self._on_ready_callback = callback

    def set_mcp_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """存储 MCP 后台事件循环引用。

        agent_integration 启动 MCP 后台线程后必须调用此方法，
        以便 call_tool_sync 能在正确的事件循环上调度协程。
        """
        self._mcp_loop = loop

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

            self._servers[name] = _MCPServer(config=server_config)
            logger.info("已加载 MCP 服务器配置: %r (transport=%s)", name, effective)

    # -------------------- 生命周期 --------------------

    async def start_all(self) -> None:
        """启动所有已启用的 MCP 服务器

        启动流程：
        1. 为每个启用的服务器创建后台任务 (_run_server_loop)
        2. 等待每个服务器的 _ready event（握手 + 工具发现完成）
        3. 注册已发现的 MCP 工具到 ToolRegistry
        4. 触发 on_ready 回调（如果有）
        """
        if not self._servers:
            logger.info("没有配置 MCP 服务器")
            return

        # 为每个服务器创建启动任务
        tasks = []
        for name, server in self._servers.items():
            if server.config.enabled:
                server._ready.clear()
                server._stop_event.clear()
                task = asyncio.create_task(
                    self._run_server_loop(name),
                    name=f"mcp-server-{name}",
                )
                server._task = task
                tasks.append((name, task))

        if tasks:
            # 等待所有服务器的 _ready event（带超时）
            ready_events = [
                server._ready
                for server in self._servers.values()
                if server.config.enabled
            ]
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *[e.wait() for e in ready_events],
                        return_exceptions=True,
                    ),
                    timeout=self._startup_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "MCP servers did not all connect within %.0fs — "
                    "remaining servers will register tools as they connect",
                    self._startup_timeout,
                )
                # 记录超时的服务器
                for name, server in self._servers.items():
                    if server.config.enabled and not server._ready.is_set():
                        self._startup_errors[name] = "startup timeout"
                        server.error_message = "startup timeout"

            # 收集启动阶段的错误
            for name, server in self._servers.items():
                if server.config.enabled and server.error_message:
                    self._startup_errors[name] = server.error_message

            # 统计连接结果
            connected = sum(
                1 for server in self._servers.values()
                if server._ready.is_set()
            )
            total = len(tasks)
            logger.info("MCP 服务器启动完成: %d/%d 已连接", connected, total)

            # 注册所有已发现的 MCP 工具到 ToolRegistry
            self.register_tools_to_registry()

            # 触发 on-ready 回调
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
        server = self._servers.get(name)
        if not server:
            return

        attempt = 0

        while attempt < MAX_RECONNECT_ATTEMPTS and not server.stopping:
            try:
                await server.start()
                # start() 正常返回表示 stop() 被调用或连接断开
                if server.stopping:
                    break
                # 连接意外断开，准备重连
                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    server.error_message = "连接反复断开，重连失败"
                    self._startup_errors[name] = server.error_message
                    logger.error(
                        "MCP 服务器 %r 连接反复断开，重连 %d 次后放弃",
                        name, attempt,
                    )
                    break
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "MCP 服务器 %r 连接断开，%.1fs 后重连 (%d/%d)",
                    name, delay, attempt, MAX_RECONNECT_ATTEMPTS,
                )
                await asyncio.sleep(delay)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    server.error_message = str(exc)
                    self._startup_errors[name] = server.error_message
                    logger.error(
                        "MCP 服务器 %r 重连 %d 次后放弃: %s",
                        name, attempt, exc,
                    )
                    break
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "MCP 服务器 %r 连接失败 (%d/%d)，%.1fs 后重试: %s",
                    name, attempt, MAX_RECONNECT_ATTEMPTS, delay, exc,
                )
                await asyncio.sleep(delay)

    async def _stop_server(self, name: str) -> None:
        """停止单个 MCP 服务器"""
        server = self._servers.get(name)
        if not server:
            return

        await server.stop()

        # 取消后台任务
        if server._task and not server._task.done():
            server._task.cancel()
            try:
                await server._task
            except asyncio.CancelledError:
                pass
            server._task = None

    # -------------------- 工具调用 --------------------

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
        target_server: Optional[_MCPServer] = None
        for server in self._servers.values():
            if tool_name in server.tools:
                target_server = server
                break

        if target_server is None:
            raise MCPToolCallError(f"未找到工具: {tool_name}")

        return await target_server.call_tool(tool_name, arguments)

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any],
                              timeout: float = 120.0) -> Any:
        """异步调用 MCP 工具（推荐方式）。

        将 session.call_tool() 调度到 MCP 后台事件循环执行，
        然后用 asyncio.wrap_future 异步等待结果，不阻塞主线程事件循环。

        Args:
            tool_name: 工具名称（格式: mcp_{server}_{tool}）
            arguments: 工具参数
            timeout: 超时秒数

        Returns:
            工具返回的结果
        """
        loop = self._mcp_loop
        if loop is None or not loop.is_running():
            raise MCPConnectionError("MCP 事件循环未运行")

        async def _call() -> Any:
            return await self.call_tool(tool_name, arguments)

        future = asyncio.run_coroutine_threadsafe(_call(), loop)
        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            future.cancel()
            raise MCPToolCallError(
                f"MCP 工具 {tool_name} 调用超时 ({timeout}s)"
            )

    def call_tool_sync(self, tool_name: str, arguments: Dict[str, Any],
                       timeout: float = 120.0) -> Any:
        """同步调用 MCP 工具（仅用于非 async 上下文，如线程中）。

        警告：此方法会阻塞当前线程。在 async 上下文中请使用 call_tool_async。
        """
        loop = self._mcp_loop
        if loop is None or not loop.is_running():
            raise MCPConnectionError("MCP 事件循环未运行")

        async def _call() -> Any:
            return await self.call_tool(tool_name, arguments)

        future = asyncio.run_coroutine_threadsafe(_call(), loop)
        start_time = _time.monotonic()

        while True:
            remaining = timeout - (_time.monotonic() - start_time)
            if remaining <= 0:
                future.cancel()
                raise MCPToolCallError(
                    f"MCP 工具 {tool_name} 调用超时 ({timeout}s)"
                )
            try:
                return future.result(timeout=min(0.1, remaining))
            except concurrent.futures.TimeoutError:
                continue

    # -------------------- 查询接口 --------------------

    def get_all_tools(self) -> List[MCPTool]:
        """获取所有已发现的工具"""
        tools: List[MCPTool] = []
        for server in self._servers.values():
            tools.extend(server.tools.values())
        return tools

    def register_tools_to_registry(self, registry: Optional[ToolRegistry] = None) -> int:
        """Register all discovered MCP tools into the ToolRegistry.
        Returns the number of tools registered.
        """
        if registry is None:
            registry = get_default_registry()

        count = 0
        for server in self._servers.values():
            for tool in server.tools.values():
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
        for server in self._servers.values():
            tool = server.tools.get(tool_name)
            if tool is not None:
                return tool
        return None

    def get_server_status(self, name: str) -> Optional[Dict[str, Any]]:
        """获取单个服务器的状态"""
        server = self._servers.get(name)
        if server is None:
            return None
        return {
            "name": name,
            "transport": server.config.effective_transport,
            "connected": server.connected,
            "tools_count": len(server.tools),
            "tools": [t.name for t in server.tools.values()],
        }

    def get_startup_errors(self) -> Dict[str, str]:
        """获取启动阶段的错误信息

        Returns:
            字典，键为服务器名称，值为错误信息。
        """
        return dict(self._startup_errors)

    def get_all_server_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有服务器的状态（包括 disabled 的）

        Returns:
            字典，键为服务器名称，值为状态字典。
        """
        result = {}
        for name, server in self._servers.items():
            result[name] = {
                "name": name,
                "transport": server.config.effective_transport,
                "enabled": server.config.enabled,
                "connected": server.connected,
                "tools_count": len(server.tools),
                "error": server.error_message,
            }
        return result

    def get_tools_summary(self) -> str:
        """生成用于 /mcp 命令的工具摘要文本（包括 disabled 服务器）"""
        if not self._servers:
            return "  No MCP servers configured."

        lines: List[str] = []
        lines.append("  MCP servers:")
        lines.append("")

        for name, server in self._servers.items():
            transport = server.config.effective_transport
            if not server.config.enabled:
                status_icon = "⏸️"
                status_text = "disabled"
            elif server.connected:
                status_icon = "✅"
                status_text = "connected"
            elif server.started and server.error_message:
                status_icon = "❌"
                status_text = f"failed: {server.error_message}"
            elif server.started:
                status_icon = "❌"
                status_text = "failed"
            else:
                status_icon = "⏳"
                status_text = "not started"

            lines.append(f"    {status_icon} {name} ({transport}) - {status_text}")

            if server.tools:
                for tool in server.tools.values():
                    desc = (
                        tool.description[:60] + "..."
                        if len(tool.description) > 60
                        else tool.description
                    )
                    lines.append(f"       - {tool.name}: {desc}")

        total = len(self._servers)
        enabled = sum(1 for s in self._servers.values() if s.config.enabled)
        connected = sum(1 for s in self._servers.values() if s.connected)
        total_tools = sum(len(s.tools) for s in self._servers.values())
        lines.append("")
        lines.append(
            f"  {total} servers ({enabled} enabled), "
            f"{connected} connected, {total_tools} tools"
        )

        return "\n".join(lines)

    @property
    def is_running(self) -> bool:
        """是否有任何服务器正在运行"""
        return any(s.connected for s in self._servers.values())

    @property
    def server_names(self) -> List[str]:
        """所有已配置的服务器名称"""
        return list(self._servers.keys())

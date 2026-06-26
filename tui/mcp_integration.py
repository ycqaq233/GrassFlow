"""
GrassFlow MCP (Model Context Protocol) 客户端集成

参考 hermes 的 MCP 实现架构，为 GrassFlow REPL 提供：
- MCP 服务器配置加载与管理
- stdio / HTTP / SSE 三种传输方式（stdio 完整实现，HTTP/SSE 骨架）
- JSON-RPC 2.0 协议通信
- 动态工具发现（tools/list）
- 工具调用（tools/call）
- 自动重连（指数退避）
- 工具过滤（include / exclude）

设计要点：
- 每个 MCP 服务器对应一个长生命周期 asyncio Task
- 不依赖 mcp 库，使用原生 asyncio + subprocess
- JSON-RPC 2.0 消息格式（Content-Length 头 + JSON 体）
- MCP 协议版本：2024-11-05
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ==================== 数据模型 ====================


@dataclass
class MCPServerConfig:
    """单个 MCP 服务器的配置"""

    name: str
    # stdio 传输
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    # HTTP / SSE 传输
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    # 通用配置
    transport: str = "stdio"  # stdio / http / sse
    timeout: int = 120
    connect_timeout: int = 60
    keepalive_interval: int = 10
    enabled: bool = True
    # 工具过滤
    tools_include: Optional[List[str]] = None
    tools_exclude: Optional[List[str]] = None

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
    task: Optional[asyncio.Task] = None
    tools: Dict[str, MCPTool] = field(default_factory=dict)
    request_id: int = 0
    connected: bool = False
    stopping: bool = False
    rpc_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

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

    # -------------------- 配置 --------------------

    def load_config(self, config: Dict[str, Any]) -> None:
        """从配置字典加载 mcp_servers

        Args:
            config: 完整配置字典，需包含 mcp_servers 键。
                    格式示例：
                    {
                        "mcp_servers": {
                            "filesystem": {
                                "command": "npx",
                                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                                "transport": "stdio"
                            }
                        }
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
                headers=srv_cfg.get("headers", {}),
                transport=srv_cfg.get("transport", "stdio"),
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

            # 校验必要字段
            if server_config.transport == "stdio" and not server_config.command:
                logger.warning("MCP 服务器 %r 使用 stdio 传输但未指定 command，跳过", name)
                continue
            if server_config.transport in ("http", "sse") and not server_config.url:
                logger.warning("MCP 服务器 %r 使用 %s 传输但未指定 url，跳过", name, server_config.transport)
                continue

            self._servers[name] = _ServerState(config=server_config)
            logger.info("已加载 MCP 服务器配置: %r (transport=%s)", name, server_config.transport)

    # -------------------- 生命周期 --------------------

    async def start_all(self) -> None:
        """启动所有已启用的 MCP 服务器"""
        if not self._servers:
            logger.info("没有配置 MCP 服务器")
            return

        tasks = []
        for name, state in self._servers.items():
            if state.config.enabled:
                task = asyncio.create_task(
                    self._run_server_loop(name),
                    name=f"mcp-server-{name}",
                )
                state.task = task
                tasks.append(task)

        if tasks:
            # 等待所有服务器完成初始化（或失败），设置超时
            done, pending = await asyncio.wait(tasks, timeout=10.0)
            failed = 0
            for t in done:
                if t.exception():
                    logger.error("MCP 服务器启动失败: %s", t.exception())
                    failed += 1
            # pending 的任务仍在后台运行（长生命周期）
            ready = len(done) - failed + len(pending)
            logger.info("MCP 服务器启动完成: %d/%d 就绪", ready, len(tasks))
            # Register discovered MCP tools into the global tool registry
            self.register_tools_to_registry()

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

        while attempt < MAX_RECONNECT_ATTEMPTS and not state.stopping:
            try:
                if config.transport == "stdio":
                    await self._start_stdio_server(name, config)
                elif config.transport in ("http", "sse"):
                    await self._start_http_server(name, config)
                else:
                    logger.error("不支持的 MCP 传输类型: %r", config.transport)
                    return

                # 连接成功，重置重连计数
                attempt = 0
                state.connected = True

                # Re-register tools after reconnect
                self.register_tools_to_registry()

                # 等待进程结束（或被停止）
                if state.process:
                    await state.process.wait()

                state.connected = False

                if state.stopping:
                    break

                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    logger.error("MCP 服务器 %r 进程反复退出，重连 %d 次后放弃", name, attempt)
                    break
                delay = RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("MCP 服务器 %r 进程退出，%.1fs 后重连 (%d/%d)", name, delay, attempt, MAX_RECONNECT_ATTEMPTS)
                await asyncio.sleep(delay)

            except Exception as exc:
                state.connected = False
                attempt += 1
                if attempt >= MAX_RECONNECT_ATTEMPTS:
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
        logger.info("启动 MCP 服务器 %r: %s", name, " ".join(cmd_parts))

        # 合并环境变量
        env = os.environ.copy()
        env.update(config.env)

        errlog = _get_mcp_stderr_log()
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=errlog.fileno() if errlog is not None else asyncio.subprocess.DEVNULL,
            env=env,
            cwd=config.cwd,
        )

        state = self._servers[name]
        state.process = process

        try:
            # MCP 握手：initialize -> notifications/initialized
            await self._do_handshake(name, process, config)

            # 工具发现
            await self._discover_tools(name, process, config)
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
            raise

        logger.info("MCP 服务器 %r 就绪，发现 %d 个工具", name, len(state.tools))

    async def _start_http_server(self, name: str, config: MCPServerConfig) -> None:
        """通过 HTTP/SSE 启动 MCP 服务器（骨架实现）

        TODO: 实现 HTTP/SSE 传输
        - HTTP: POST JSON-RPC 消息到 config.url
        - SSE: 建立 SSE 连接接收服务端推送
        """
        logger.warning("MCP 服务器 %r: HTTP/SSE 传输尚未实现（骨架）", name)
        # 模拟连接成功，等待停止信号
        state = self._servers[name]
        state.connected = True
        await asyncio.sleep(float("inf"))

    async def _stop_server(self, name: str) -> None:
        """停止单个 MCP 服务器"""
        state = self._servers.get(name)
        if not state:
            return

        state.stopping = True

        # 终止子进程
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

    async def _do_handshake(self, name: str, process: asyncio.subprocess.Process,
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
            await self._send_message(process, init_request)
            response = await self._read_message(process, timeout=config.connect_timeout, expected_id=init_request['id'])
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
            await self._send_message(process, initialized_notification)
        logger.debug("MCP 服务器 %r 握手完成", name)

    async def _discover_tools(self, name: str, process: asyncio.subprocess.Process,
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
            await self._send_message(process, list_request)
            response = await self._read_message(process, timeout=config.timeout, expected_id=list_request['id'])
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

        if not target_state.connected or target_state.process is None:
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
            await self._send_message(target_state.process, call_request)
            response = await self._read_message(
                target_state.process, timeout=target_state.config.timeout,
                expected_id=call_request['id']
            )
        if response is None:
            raise MCPToolCallError(f"工具 {tool_name} 调用超时")
        if "error" in response:
            error = response["error"]
            raise MCPToolCallError(
                f"工具 {tool_name} 调用失败: {error.get('message', error)}"
            )

        return response.get("result", {})

    # -------------------- IO 操作 --------------------

    @staticmethod
    async def _send_message(process: asyncio.subprocess.Process,
                            message: Dict[str, Any]) -> None:
        """通过 stdin 发送 JSON-RPC 消息（Content-Length 头 + JSON 体）"""
        if process.stdin is None:
            raise MCPConnectionError("进程 stdin 不可用")

        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")

        process.stdin.write(header + body)
        await process.stdin.drain()

    @staticmethod
    async def _read_message(process: asyncio.subprocess.Process,
                            timeout: float = 30.0,
                            expected_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """从 stdout 读取一条 JSON-RPC 消息

        协议格式：
            Content-Length: <length>\r\n
            \r\n
            <JSON body>

        Returns:
            解析后的 JSON 字典，超时或 EOF 返回 None
        """
        if process.stdout is None:
            return None

        loop = asyncio.get_running_loop()
        msg_deadline = loop.time() + timeout

        async def _read_line() -> Optional[bytes]:
            """读取一行（以 \\r\\n 结尾），使用 deadline 累计超时"""
            remaining = msg_deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            line = await asyncio.wait_for(
                process.stdout.readline(), timeout=remaining  # type: ignore[arg-type]
            )
            if not line:
                return None  # EOF
            return line.rstrip(b"\r\n")

        try:
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

            # 读取消息体 -- 使用剩余 deadline
            body = b""
            remaining = content_length
            while remaining > 0:
                time_left = msg_deadline - loop.time()
                if time_left <= 0:
                    raise asyncio.TimeoutError()
                chunk = await asyncio.wait_for(
                    process.stdout.read(remaining), timeout=time_left
                )
                if not chunk:
                    return None  # EOF
                body += chunk
                remaining -= len(chunk)

            msg = json.loads(body.decode("utf-8"))

            # Skip notifications (no id field) -- read next message
            if 'id' not in msg:
                logger.debug("Skipping MCP notification: %s", msg.get('method', 'unknown'))
                return await MCPManager._read_message(
                    process, timeout=max(0, msg_deadline - loop.time()), expected_id=expected_id
                )

            # Validate response id matches request
            if expected_id is not None and msg.get('id') != expected_id:
                logger.warning(
                    "MCP response id mismatch: expected %d, got %s",
                    expected_id, msg.get('id')
                )

            return msg

        except asyncio.TimeoutError:
            logger.warning("读取 MCP 消息超时 (%.1fs)", timeout)
            return None
        except json.JSONDecodeError as exc:
            logger.warning("MCP 消息 JSON 解析失败: %s", exc)
            return None

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
            "transport": state.config.transport,
            "connected": state.connected,
            "tools_count": len(state.tools),
            "tools": [t.name for t in state.tools.values()],
        }

    def get_tools_summary(self) -> str:
        """生成用于 /mcp 命令的工具摘要文本"""
        if not self._servers:
            return "未配置 MCP 服务器。"

        lines: List[str] = []
        lines.append("MCP 服务器状态:")
        lines.append("-" * 50)

        for name, state in self._servers.items():
            status = "已连接" if state.connected else "未连接"
            transport = state.config.transport
            lines.append(f"  {name} ({transport}) — {status}")

            if state.tools:
                for tool in state.tools.values():
                    desc = tool.description[:60] + "..." if len(tool.description) > 60 else tool.description
                    lines.append(f"    - {tool.name}: {desc}")
            else:
                lines.append("    (无工具)")

        total_tools = sum(len(s.tools) for s in self._servers.values())
        lines.append("-" * 50)
        lines.append(f"共 {len(self._servers)} 个服务器，{total_tools} 个工具")

        return "\n".join(lines)

    @property
    def is_running(self) -> bool:
        """是否有任何服务器正在运行"""
        return any(s.connected for s in self._servers.values())

    @property
    def server_names(self) -> List[str]:
        """所有已配置的服务器名称"""
        return list(self._servers.keys())

# MCP 集成重构计划 — 基于官方 mcp SDK

## TL;DR

> **快速总结**: GrassFlow 的 MCP 集成是从零手写的（asyncio + subprocess + httpx），协议实现存在多处 bug，导致服务器无法连接。hermes 使用官方 `mcp` Python SDK (v1.26.0)，代码量少 10 倍且功能更完整。本次重构将切换到官方 SDK，保持现有 API 接口不变。
>
> **交付物**:
> - `requirements.txt` 添加 `mcp>=1.26.0` 依赖
> - 重写 `tui/mcp_integration.py` 的传输层，使用 `mcp` SDK 的 `stdio_client`、`streamablehttp_client`、`sse_client`
> - 保持 `MCPManager` 公开 API 不变（`load_config`、`start_all`、`stop_all`、`call_tool`、`get_tools_summary` 等）
> - 新增 circuit breaker、keepalive、环境变量过滤等 hermes 已有功能
>
> **预估工作量**: Large
> **并行执行**: YES - 3 waves
> **关键路径**: Install Dep → Rewrite Transport → Integration Test

---

## Context

### 问题背景

GrassFlow TUI 启动后，`/mcp` 命令显示所有服务器都是 "disabled" 或 "not started"，没有任何服务器成功连接。

### 调查发现

**根因**: GrassFlow 手写了 MCP 协议实现（`tui/mcp_integration.py`，1358 行），存在以下问题：

| 问题 | 影响 | hermes 的做法 |
|------|------|--------------|
| 手写 Content-Length 帧解析 | 可能存在边界条件 bug | 用 `mcp` SDK 的 `stdio_client` |
| 手写 HTTP/SSE 传输 | 不支持 Streamable HTTP 新协议 | 用 SDK 的 `streamablehttp_client` |
| 手写 JSON-RPC 握手 | 协议版本过旧 (2024-11-05) | SDK 自动处理 (2025-03-26) |
| 无 circuit breaker | 坏服务器会无限重试 | 3 次失败后熔断 60 秒 |
| 无 keepalive | HTTP/SSE 连接会变陈旧 | 定期 ping 保活 |
| 无环境变量过滤 | 子进程继承所有环境变量（含 API key） | 白名单过滤安全变量 |
| 无 schema normalization | 某些 MCP 服务器的 JSON Schema 不兼容 | 自动修复 definitions->$defs 等 |
| 无动态工具发现 | 服务器增删工具后需重启 | 监听 tools/list_changed 通知 |

### hermes MCP 架构要点

| 组件 | 文件 | 说明 |
|------|------|------|
| MCP 客户端核心 | `tools/mcp_tool.py` (4746 行) | 服务器生命周期、传输管理、工具发现、调用分发 |
| MCP 配置 CLI | `hermes_cli/mcp_config.py` | `hermes mcp add/remove/list/test` |
| 后台启动 | `hermes_cli/mcp_startup.py` | 非阻塞后台发现线程 |
| 安全扫描 | `hermes_cli/mcp_security.py` | IOC 黑名单、数据泄露检测 |
| OAuth | `tools/mcp_oauth.py` | OAuth 2.1 PKCE 令牌存储 |

**关键架构差异**:
- hermes 用 `mcp` SDK (v1.26.0) 作为可选依赖
- 专用后台事件循环线程（`mcp-event-loop`）
- `run_coroutine_threadsafe()` 跨线程调度工具调用
- 环境变量白名单过滤（只传 PATH、HOME 等安全变量）
- 命令解析：`npx`/`npm`/`node` 多路径查找

---

## Work Objectives

### 核心目标
1. 将 MCP 传输层从手写实现切换到 `mcp` 官方 SDK
2. 保持 `MCPManager` 公开 API 不变，最小化对其他模块的影响
3. 实现 hermes 已有的关键功能：circuit breaker、keepalive、环境变量过滤
4. 确保 MCP 服务器能实际连接并注册工具

### 完成定义
- [ ] `mcp>=1.26.0` 已安装并可导入
- [ ] playwright (stdio) 和 tavily-search (stdio) 服务器能成功连接
- [ ] `/mcp` 命令显示至少 2 个服务器为 "connected"
- [ ] MCP 工具已注册到 ToolRegistry，Agent 可调用
- [ ] circuit breaker 在连续失败后触发
- [ ] 环境变量过滤防止 API key 泄露

### Must Have
- 使用 `mcp` SDK 的传输层
- stdio / HTTP / SSE 三种传输方式
- 启动超时可配置
- 错误收集和状态查询
- 环境变量过滤

### Must NOT Have
- 不改变 `MCPManager` 的公开 API（`load_config`、`start_all`、`stop_all`、`call_tool`、`get_tools_summary` 等）
- 不改变配置文件格式（`~/.Grass/config.json` 的 `mcp_servers` 结构）
- 不实现 OAuth 2.1（MVP 不需要）
- 不实现 sampling/elicitation（MVP 不需要）
- 不实现安全扫描（后续迭代）

---

## Verification Strategy

### QA 场景

```gherkin
Scenario: MCP 服务器成功连接
  Given ~/.Grass/config.json 中 playwright 服务器 enabled=true, transport=stdio
  When TUI 启动并初始化 MCP
  Then playwright 服务器状态为 "connected"
  And playwright 的工具已注册到 ToolRegistry

Scenario: /mcp 命令显示正确状态
  Given TUI 已启动，2 个 MCP 服务器已连接
  When 用户输入 /mcp
  Then 显示表格包含每个服务器的状态
  And 至少 2 个服务器显示 "✅ connected"

Scenario: Circuit breaker 触发
  Given 一个 MCP 服务器连续调用失败 3 次
  When 第 4 次调用该服务器的工具
  Then 返回 "server unreachable" 错误
  And 不发起实际的 MCP 请求

Scenario: 环境变量过滤
  Given 系统环境变量中包含 OPENAI_API_KEY
  When 启动 stdio MCP 服务器子进程
  Then 子进程的环境变量中不包含 OPENAI_API_KEY
  And 子进程的环境变量中包含 PATH
```

---

## Execution Strategy

### 并行执行波次

```
Wave 1 (立即开始 — 依赖安装 + 传输层重写):
├── Task 1: 安装 mcp SDK + 更新 requirements.txt [quick]
├── Task 2: 重写传输层 — 使用 mcp SDK 的 stdio/http/sse 客户端 [large]
└── Task 3: 添加环境变量过滤 + 命令解析增强 [medium]

Wave 2 (Wave 1 完成后 — 高级功能):
├── Task 4: Circuit breaker 实现 [medium]
├── Task 5: Keepalive 机制 [medium]
└── Task 6: 更新 /mcp 命令显示 + 错误诊断增强 [medium]

Wave 3 (Wave 2 完成后 — 集成验证):
└── Task 7: 端到端集成测试 [medium]
```

### 依赖矩阵
- **Task 1**: 无依赖 → Wave 1
- **Task 2**: 依赖 Task 1 → Wave 1
- **Task 3**: 依赖 Task 1 → Wave 1
- **Task 4**: 依赖 Task 2 → Wave 2
- **Task 5**: 依赖 Task 2 → Wave 2
- **Task 6**: 依赖 Task 2 → Wave 2
- **Task 7**: 依赖 Task 2-6 → Wave 3

---

## TODOs

- [ ] 1. 安装 mcp SDK + 更新 requirements.txt

  **What to do**:
  - 在项目虚拟环境中安装 `mcp>=1.26.0`：`pip install "mcp>=1.26.0"`
  - 验证安装成功：`python -c "from mcp import ClientSession, StdioServerParameters; print('OK')"`
  - 更新 `requirements.txt`，添加 `mcp>=1.26.0`
  - 检查可用的传输客户端：
    ```python
    from mcp.client.stdio import stdio_client  # stdio
    from mcp.client.streamable_http import streamablehttp_client  # HTTP
    from mcp.client.sse import sse_client  # SSE
    ```

  **Must NOT do**:
  - 不要固定版本号为 `==1.26.0`，使用 `>=1.26.0` 允许兼容更新

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的依赖安装和验证

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 2, 3, 4, 5, 6, 7
  - **Blocked By**: None

  **References**:
  - `requirements.txt` — 当前依赖列表
  - hermes `pyproject.toml:197` — `mcp = ["mcp==1.26.0", "starlette==1.0.1"]`

  **Acceptance Criteria**:
  - [ ] `mcp>=1.26.0` 已安装
  - [ ] `from mcp import ClientSession, StdioServerParameters` 成功
  - [ ] `from mcp.client.stdio import stdio_client` 成功
  - [ ] `requirements.txt` 已更新

  **QA Scenarios**:
  ```
  Scenario: mcp SDK 安装成功
    Given 项目虚拟环境已激活
    When 运行 pip install "mcp>=1.26.0"
    Then 安装成功（exit code 0）
    And python -c "from mcp import ClientSession" 无错误
  ```

  **Commit**: YES
  - Message: `deps: add mcp>=1.26.0 for official MCP protocol support`
  - Files: `requirements.txt`

---

- [ ] 2. 重写传输层 — 使用 mcp SDK 的 stdio/http/sse 客户端

  **What to do**:

  这是核心任务。需要重写 `tui/mcp_integration.py` 的传输层，同时保持 `MCPManager` 的公开 API 不变。

  **架构参考**: hermes `tools/mcp_tool.py` 的 `_run_stdio` (line 1752)、`_run_http` (line 1954)、`_run_sse` (line 1998)

  **具体改动**:

  a) **删除** `_Transport` ABC 及其三个实现类（`_StdioTransport`、`_HTTPTransport`、`_MCPSSETransport`）

  b) **新增** `_MCPServer` 内部类，使用 `mcp` SDK：

  ```python
  class _MCPServer:
      """单个 MCP 服务器的运行时状态（基于 mcp SDK）"""

      def __init__(self, config: MCPServerConfig):
          self.config = config
          self.session: Optional[ClientSession] = None
          self.tools: Dict[str, MCPTool] = {}
          self.connected = False
          self.error_message: Optional[str] = None
          self._task: Optional[asyncio.Task] = None
          self._ready = asyncio.Event()

      async def start(self):
          """根据 transport 类型启动服务器"""
          transport = self.config.effective_transport
          if transport == "stdio":
              await self._run_stdio()
          elif transport == "http":
              await self._run_http()
          elif transport == "sse":
              await self._run_sse()

      async def _run_stdio(self):
          """使用 mcp SDK 的 stdio_client"""
          from mcp import ClientSession, StdioServerParameters
          from mcp.client.stdio import stdio_client

          safe_env = _build_safe_env(self.config.env)
          server_params = StdioServerParameters(
              command=self.config.command,
              args=self.config.args,
              env=safe_env,
          )

          errlog = _get_mcp_stderr_log()
          async with stdio_client(server_params, errlog=errlog) as (read, write):
              async with ClientSession(read, write) as session:
                  await session.initialize()
                  self.session = session
                  await self._discover_tools()
                  self.connected = True
                  self._ready.set()
                  # 保持连接直到进程退出或被停止
                  await self._wait_for_disconnect()

      async def _run_http(self):
          """使用 mcp SDK 的 streamablehttp_client"""
          from mcp import ClientSession
          from mcp.client.streamable_http import streamablehttp_client

          async with streamablehttp_client(self.config.url, headers=self.config.headers) as (read, write, _):
              async with ClientSession(read, write) as session:
                  await session.initialize()
                  self.session = session
                  await self._discover_tools()
                  self.connected = True
                  self._ready.set()
                  await self._wait_for_disconnect()

      async def _run_sse(self):
          """使用 mcp SDK 的 sse_client"""
          from mcp import ClientSession
          from mcp.client.sse import sse_client

          async with sse_client(self.config.sse_url, headers=self.config.headers) as (read, write):
              async with ClientSession(read, write) as session:
                  await session.initialize()
                  self.session = session
                  await self._discover_tools()
                  self.connected = True
                  self._ready.set()
                  await self._wait_for_disconnect()

      async def _discover_tools(self):
          """通过 SDK 的 list_tools() 发现工具"""
          result = await self.session.list_tools()
          for tool_def in result.tools:
              if not self.config.is_tool_allowed(tool_def.name):
                  continue
              qualified_name = f"mcp_{self.config.name}_{tool_def.name}"
              self.tools[qualified_name] = MCPTool(
                  name=qualified_name,
                  server_name=self.config.name,
                  description=tool_def.description or "",
                  input_schema=tool_def.inputSchema if hasattr(tool_def, 'inputSchema') else {},
              )

      async def call_tool(self, tool_name: str, arguments: dict) -> Any:
          """通过 SDK 的 call_tool() 调用工具"""
          raw_name = tool_name[len(f"mcp_{self.config.name}_"):]
          result = await self.session.call_tool(raw_name, arguments)
          return result

      async def stop(self):
          """停止服务器"""
          if self.session:
              # SDK 会处理清理
              pass
          self.connected = False
  ```

  c) **修改** `MCPManager` 类：
  - 将 `_servers: Dict[str, _ServerState]` 改为 `_servers: Dict[str, _MCPServer]`
  - `start_all()` 使用 `asyncio.gather` 并行启动所有服务器
  - `call_tool()` 查找服务器并调用 `server.call_tool()`
  - 保持所有公开方法签名不变

  d) **新增** `_build_safe_env()` 函数（参考 hermes `tools/mcp_tool.py:356`）：
  ```python
  _SAFE_ENV_VARS = {
      "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
      "TMPDIR", "TEMP", "TMP", "XDG_RUNTIME_DIR",
      "SystemRoot", "SYSTEMROOT", "COMSPEC", "PATHEXT",  # Windows
  }

  def _build_safe_env(user_env: dict = None) -> dict:
      """构建安全的环境变量（白名单过滤）"""
      safe = {}
      for key in _SAFE_ENV_VARS:
          if key in os.environ:
              safe[key] = os.environ[key]
      if user_env:
          safe.update(user_env)
      return safe
  ```

  e) **新增** `_resolve_command()` 函数（参考 hermes `tools/mcp_tool.py:508`）：
  ```python
  def _resolve_command(command: str) -> str:
      """解析命令路径，支持 npx/npm/node 多路径查找"""
      if Path(command).is_absolute():
          return command
      resolved = shutil.which(command)
      if resolved:
          return resolved
      # npx/npm 特殊处理
      if command in ("npx", "npm", "node"):
          for candidate in [
              Path.home() / "AppData" / "Roaming" / "npm" / f"{command}.cmd",
              Path("D:/Program Files/nodejs") / f"{command}.cmd",
          ]:
              if candidate.exists():
                  return str(candidate)
      return command
  ```

  **Must NOT do**:
  - 不改变 `MCPManager` 的公开方法签名
  - 不改变 `MCPServerConfig` 数据模型
  - 不改变配置文件格式
  - 不在本任务中实现 circuit breaker（Task 4）
  - 不在本任务中实现 keepalive（Task 5）

  **Recommended Agent Profile**:
  - **Category**: `high`
    - Reason: 核心架构重写，需要理解 mcp SDK API 和现有代码结构
  - **Skills**: [`tdd`, `diagnose`]
    - TDD: 先写测试再改代码
    - Diagnose: 如果连接失败需要系统化排查

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 3 并行)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 4, 5, 6, 7
  - **Blocked By**: Task 1

  **References**:
  - `tui/mcp_integration.py` — 当前实现（将被重写）
  - hermes `tools/mcp_tool.py:1752-1850` — `_run_stdio` 实现
  - hermes `tools/mcp_tool.py:1954-2100` — `_run_http` 实现
  - hermes `tools/mcp_tool.py:1998-2050` — `_run_sse` 实现
  - hermes `tools/mcp_tool.py:356-400` — `_build_safe_env` 环境变量过滤
  - hermes `tools/mcp_tool.py:508-570` — `_resolve_stdio_command` 命令解析
  - hermes `tools/mcp_tool.py:4027-4130` — `register_mcp_servers` 并行启动

  **Acceptance Criteria**:
  - [ ] `_Transport` ABC 及其实现类已删除
  - [ ] 新的 `_MCPServer` 类使用 `mcp` SDK
  - [ ] `MCPManager` 公开 API 不变
  - [ ] stdio 传输使用 `mcp.client.stdio.stdio_client`
  - [ ] HTTP 传输使用 `mcp.client.streamable_http.streamablehttp_client`
  - [ ] SSE 传输使用 `mcp.client.sse.sse_client`
  - [ ] 环境变量白名单过滤已实现
  - [ ] 命令解析支持 npx/npm/node 多路径

  **QA Scenarios**:
  ```
  Scenario: stdio 服务器连接成功
    Given playwright 服务器配置正确 (transport=stdio, command=npx)
    When MCPManager.start_all() 执行
    Then playwright 服务器状态为 connected
    And 工具已发现并注册

  Scenario: 环境变量过滤
    Given 系统环境变量包含 SECRET_KEY=xxx
    When 启动 stdio MCP 服务器
    Then 子进程环境变量不包含 SECRET_KEY
    And 子进程环境变量包含 PATH
  ```

  **Commit**: YES
  - Message: `refactor(mcp): rewrite transport layer using official mcp SDK`
  - Files: `tui/mcp_integration.py`

---

- [ ] 3. 添加环境变量过滤 + 命令解析增强

  **What to do**:
  - 实现 `_build_safe_env()` 函数（白名单过滤环境变量）
  - 实现 `_resolve_command()` 函数（npx/npm/node 多路径查找）
  - 这两个函数在 Task 2 中会被使用，但可以独立实现和测试

  **参考 hermes**:
  - `tools/mcp_tool.py:356-400` — `_build_safe_env`
  - `tools/mcp_tool.py:508-570` — `_resolve_stdio_command`

  **Must NOT do**:
  - 不实现 malware 检查（后续迭代）
  - 不实现安全扫描（后续迭代）

  **Recommended Agent Profile**:
  - **Category**: `medium`
    - Reason: 需要理解 Windows/跨平台环境变量差异

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 2 并行)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: Task 1

  **References**:
  - hermes `tools/mcp_tool.py:356-400` — `_build_safe_env` 实现
  - hermes `tools/mcp_tool.py:508-570` — `_resolve_stdio_command` 实现

  **Acceptance Criteria**:
  - [ ] `_build_safe_env()` 白名单只包含安全变量
  - [ ] `_resolve_command()` 支持 npx/npm/node 多路径查找
  - [ ] Windows 路径（`.cmd` 扩展名）正确处理

  **QA Scenarios**:
  ```
  Scenario: 环境变量白名单过滤
    Given os.environ 包含 PATH, HOME, OPENAI_API_KEY
    When 调用 _build_safe_env()
    Then 返回的 dict 包含 PATH, HOME
    And 返回的 dict 不包含 OPENAI_API_KEY

  Scenario: npx 命令解析
    Given 系统安装了 Node.js
    When 调用 _resolve_command("npx")
    Then 返回 npx 的完整路径
  ```

  **Commit**: YES
  - Message: `feat(mcp): add safe env filtering and command resolution`
  - Files: `tui/mcp_integration.py`

---

- [ ] 4. Circuit breaker 实现

  **What to do**:
  - 参考 hermes `tools/mcp_tool.py:2427` 的 circuit breaker 实现
  - 在 `_MCPServer` 中添加 circuit breaker 状态：
    - `failure_count: int = 0`
    - `breaker_open: bool = False`
    - `breaker_opened_at: float = 0`
    - `BREAKER_THRESHOLD = 3`（连续失败次数）
    - `BREAKER_COOLDOWN = 60.0`（冷却时间秒）
  - `call_tool()` 在调用前检查 breaker 状态：
    - 如果 breaker 打开且冷却期未过，直接返回 "server unreachable"
    - 如果 breaker 打开且冷却期已过，设为 half-open，允许一次尝试
    - 调用成功重置失败计数，调用失败递增计数
    - 连续失败 3 次打开 breaker

  **Must NOT do**:
  - 不实现 sampling rate limiting（后续迭代）

  **Recommended Agent Profile**:
  - **Category**: `medium`
    - Reason: 逻辑清晰，需要在 _MCPServer 中添加状态管理

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 5, 6 并行)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:
  - hermes `tools/mcp_tool.py:2427-2500` — circuit breaker 实现
  - `tui/mcp_integration.py` — _MCPServer 类（Task 2 重写后）

  **Acceptance Criteria**:
  - [ ] 连续 3 次调用失败后 breaker 打开
  - [ ] breaker 打开后 60 秒内调用返回 "server unreachable"
  - [ ] 冷却期过后下一次调用作为 half-open 探测
  - [ ] 调用成功重置 breaker

  **QA Scenarios**:
  ```
  Scenario: Circuit breaker 触发
    Given 一个 MCP 服务器连续调用失败 3 次
    When 第 4 次调用
    Then 返回 "server unreachable" 错误
    And 不发起实际 MCP 请求

  Scenario: Circuit breaker 冷却恢复
    Given circuit breaker 已打开
    When 等待 60 秒后再次调用
    Then 允许一次尝试（half-open 状态）
  ```

  **Commit**: YES
  - Message: `feat(mcp): add circuit breaker for failed servers`
  - Files: `tui/mcp_integration.py`

---

- [ ] 5. Keepalive 机制

  **What to do**:
  - 参考 hermes `tools/mcp_tool.py:1630` 的 keepalive 实现
  - 在 `_MCPServer` 中添加 keepalive 任务：
    - 定期发送 `session.send_ping()`（如果服务器支持）
    - 如果服务器不支持 ping（返回 -32601），fallback 到 `session.list_tools()`
    - 默认间隔 180 秒，可通过 `keepalive_interval` 配置
  - 在 `_run_http()` 和 `_run_sse()` 中启动 keepalive 任务

  **Must NOT do**:
  - 不为 stdio 传输实现 keepalive（子进程 stdin/stdout 的 liveness 由进程退出检测）

  **Recommended Agent Profile**:
  - **Category**: `medium`
    - Reason: 需要理解 async 任务管理和 MCP 协议

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 4, 6 并行)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:
  - hermes `tools/mcp_tool.py:1630-1700` — keepalive 实现
  - `tui/mcp_integration.py` — _MCPServer 类

  **Acceptance Criteria**:
  - [ ] HTTP/SSE 传输有定期 keepalive 探测
  - [ ] keepalive 间隔可配置（默认 180 秒）
  - [ ] 服务器不支持 ping 时 fallback 到 list_tools

  **QA Scenarios**:
  ```
  Scenario: Keepalive 定期发送
    Given HTTP MCP 服务器已连接，keepalive_interval=10
    When 等待 15 秒
    Then 至少发送了 1 次 keepalive 探测
  ```

  **Commit**: YES
  - Message: `feat(mcp): add keepalive for HTTP/SSE transports`
  - Files: `tui/mcp_integration.py`

---

- [ ] 6. 更新 /mcp 命令显示 + 错误诊断增强

  **What to do**:
  - 更新 `_cmd_mcp()` 显示更多信息：
    - 每个服务器的 transport 类型
    - 工具数量
    - Circuit breaker 状态
    - 最后错误信息
    - 连接时长
  - 添加 `/mcp test <server>` 子命令：测试单个服务器连接
  - 添加 `/mcp restart <server>` 子命令：重启单个服务器
  - 在启动失败时提供诊断建议：
    - "npx not found" → "Install Node.js"
    - "connection refused" → "Check if the server is running"
    - "startup timeout" → "Increase mcp.startup_timeout in config"

  **Must NOT do**:
  - 不实现 `hermes mcp add` 交互式配置（后续迭代）
  - 不实现 MCP 服务器目录/市场（后续迭代）

  **Recommended Agent Profile**:
  - **Category**: `medium`
    - Reason: 需要理解命令注册机制和 Rich 渲染

  **Parallelization**:
  - **Can Run In Parallel**: YES (与 Task 4, 5 并行)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:
  - `tui/slash_commands.py:1045-1071` — 当前 `_cmd_mcp` 实现
  - hermes `hermes_cli/mcp_config.py` — hermes MCP CLI 命令

  **Acceptance Criteria**:
  - [ ] `/mcp` 显示完整状态表格（transport、tools、breaker、error）
  - [ ] `/mcp test <name>` 能测试单个服务器连接
  - [ ] 启动失败时显示诊断建议

  **QA Scenarios**:
  ```
  Scenario: /mcp 显示详细状态
    Given 2 个服务器已连接，1 个 disabled
    When 用户输入 /mcp
    Then 表格显示 transport 类型、工具数量、连接状态
    And disabled 服务器显示为灰色
  ```

  **Commit**: YES
  - Message: `feat(mcp): enhance /mcp command with diagnostics`
  - Files: `tui/slash_commands.py`, `tui/mcp_integration.py`

---

- [ ] 7. 端到端集成测试

  **What to do**:
  - 编写集成测试 `tests/test_mcp_integration.py`
  - 测试场景：
    1. mcp SDK 导入成功
    2. 配置加载：验证 config.json 被正确解析
    3. 环境变量过滤：验证 _build_safe_env 白名单
    4. 命令解析：验证 _resolve_command npx 路径
    5. Circuit breaker：验证 3 次失败后触发
    6. /mcp 命令：验证输出包含服务器状态
  - 运行测试确认通过

  **Recommended Agent Profile**:
  - **Category**: `medium`
    - Reason: 需要理解测试框架和 mock 策略

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential)
  - **Blocks**: None
  - **Blocked By**: Task 2, 3, 4, 5, 6

  **Acceptance Criteria**:
  - [ ] `tests/test_mcp_integration.py` 存在
  - [ ] 所有测试通过
  - [ ] 覆盖：配置解析、环境变量过滤、circuit breaker、命令解析

  **QA Scenarios**:
  ```
  Scenario: 集成测试全部通过
    Given 测试文件已编写
    When 运行 pytest tests/test_mcp_integration.py
    Then 所有测试通过 (exit code 0)
  ```

  **Commit**: YES
  - Message: `test(mcp): add integration tests for MCP SDK integration`
  - Files: `tests/test_mcp_integration.py`

---

## Final Verification Wave

- [ ] F1. **代码审查** — `ultraworker`
  检查所有修改的文件：mcp SDK 用法是否正确、环境变量过滤是否完整、circuit breaker 逻辑是否正确。

- [ ] F2. **端到端验证** — `unspecified-high`
  启动 GrassFlow TUI，验证：MCP 服务器连接成功、/mcp 命令显示正确、工具可被 Agent 调用。

---

## Commit Strategy

- **Task 1**: `deps: add mcp>=1.26.0 for official MCP protocol support` → `requirements.txt`
- **Task 2**: `refactor(mcp): rewrite transport layer using official mcp SDK` → `tui/mcp_integration.py`
- **Task 3**: `feat(mcp): add safe env filtering and command resolution` → `tui/mcp_integration.py`
- **Task 4**: `feat(mcp): add circuit breaker for failed servers` → `tui/mcp_integration.py`
- **Task 5**: `feat(mcp): add keepalive for HTTP/SSE transports` → `tui/mcp_integration.py`
- **Task 6**: `feat(mcp): enhance /mcp command with diagnostics` → `tui/slash_commands.py`, `tui/mcp_integration.py`
- **Task 7**: `test(mcp): add integration tests for MCP SDK integration` → `tests/test_mcp_integration.py`

---

## Success Criteria

### 验证命令
```bash
# 1. mcp SDK 安装验证
python -c "from mcp import ClientSession; print('OK')"
# 预期: OK

# 2. MCP 服务器连接验证
# 启动 TUI REPL，输入 /mcp
# 预期: playwright 显示 "✅ connected"，工具已注册

# 3. 测试通过
pytest tests/test_mcp_integration.py -v
# 预期: 全部通过
```

### 最终检查清单
- [ ] mcp SDK 已安装
- [ ] stdio 传输使用 mcp SDK
- [ ] HTTP 传输使用 mcp SDK
- [ ] SSE 传输使用 mcp SDK
- [ ] 环境变量白名单过滤
- [ ] npx/npm/node 命令多路径解析
- [ ] Circuit breaker 实现
- [ ] Keepalive 实现
- [ ] /mcp 命令增强
- [ ] 集成测试通过

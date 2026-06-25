# GrassFlow 多 Agent 工作流计划

## 目标
完成 GrassFlow 剩余 4 个阶段，参考 opencode/hermes 实现，不重复造轮子。

## 参考源码位置
- **opencode**: `E:/opencode-desktop/opencode-dev/opencode-dev/packages/`
  - `core/` - 核心模块
  - `llm/` - LLM 协议抽象
  - `opencode/` - 主应用
  - `tui/` - TUI 界面
  - `protocol/` - 协议定义
  - `schema/` - Schema 定义

---

## Phase 1: 基础架构（并行 4 个 Agent）

### Agent 1.1: LLM 协议抽象层
**参考**: `opencode/packages/llm/` 和 `opencode/packages/protocol/`
**任务**:
- 实现四维模型：Protocol + Endpoint + Auth + Framing
- 支持 OpenAI Chat / Anthropic Messages 协议
- 统一的流式响应处理

**输出**: `core/llm_protocol.py`

### Agent 1.2: 工具注册表
**参考**: `opencode/packages/opencode/src/tool/`
**任务**:
- 统一工具注册接口
- 自注册模式（AST 扫描）
- 工具调用入口

**输出**: `core/tool_registry.py`

### Agent 1.3: Skills 系统
**参考**: `opencode/packages/opencode/src/skill/`
**任务**:
- YAML + Markdown 格式解析
- 多目录发现机制
- 渐进式披露（列表 → 详情 → 文件）

**输出**: `core/skills.py`

### Agent 1.4: 错误分类器
**参考**: hermes 的 FailoverReason 枚举
**任务**:
- 结构化错误枚举
- 重试/fallback 逻辑

**输出**: `core/error_classifier.py`

---

## Phase 2: 会话系统（并行 3 个 Agent）

### Agent 2.1: REPL 会话管理
**参考**: `opencode/packages/opencode/src/session/`
**任务**:
- 会话创建、恢复、持久化
- SQLite 存储

**输出**: `tui/session.py`

### Agent 2.2: 上下文压缩
**参考**: `opencode/packages/opencode/src/session/compaction.ts`
**任务**:
- token 超限检测
- 摘要 Agent 压缩旧消息

**输出**: `tui/context_compressor.py`

### Agent 2.3: REPL 主循环
**参考**: `opencode/packages/tui/`
**任务**:
- 输入处理
- 消息渲染
- 中断处理

**输出**: `tui/repl.py`

---

## Phase 3: 工具系统（并行 3 个 Agent）

### Agent 3.1: 内置工具
**参考**: `opencode/packages/opencode/src/tool/`
**任务**:
- shell, read, write, glob, grep 工具
- 统一接口

**输出**: `tools/` 目录

### Agent 3.2: MCP 客户端
**参考**: `opencode/packages/opencode/src/mcp/`
**任务**:
- MCP 协议实现
- 工具发现和注册

**输出**: `core/mcp_client.py`

### Agent 3.3: 权限控制
**参考**: `opencode/packages/opencode/src/permission/`
**任务**:
- allow/deny/ask 三级权限
- 用户审批流程

**输出**: `core/permission.py`

---

## Phase 4: Agent 组件系统（并行 2 个 Agent）

### Agent 4.1: 组件运行时
**任务**:
- 将 DSL v2 AST 转换为可执行组件
- 组件实例化
- 端口映射

**输出**: `core/agent_component.py`

### Agent 4.2: 组件注册表
**任务**:
- 组件发现机制（文件系统）
- 组件注册和查询

**输出**: `core/component_registry.py`

---

## Phase 5: 高级特性（并行 2 个 Agent）

### Agent 5.1: 熔断器 + Doom Loop
**参考**: hermes 的熔断器实现
**任务**:
- 连续失败触发熔断
- Doom Loop 检测（同一工具相同参数 3 次）

**输出**: `core/circuit_breaker.py`, `core/doom_loop.py`

### Agent 5.2: 渐进式披露 + AI 工作流生成
**任务**:
- Skills 三层架构
- AI 自动生成 DSL

**输出**: 增强现有系统

---

## 执行策略

1. **Phase 1 和 Phase 2 并行** - Phase 2 依赖 Phase 1 的 LLM 协议，但可以先用现有实现
2. **Phase 3 和 Phase 4 并行** - 独立模块
3. **Phase 5 最后** - 依赖前面的模块

## 成功标准

- [ ] LLM 协议抽象层支持 2+ provider
- [ ] 工具注册表支持自注册
- [ ] Skills 系统可发现和加载技能
- [ ] REPL 会话可保持上下文
- [ ] 内置工具 5+ 个
- [ ] MCP Client 可连接外部服务
- [ ] Agent 组件可实例化和执行
- [ ] 熔断器在连续失败时触发

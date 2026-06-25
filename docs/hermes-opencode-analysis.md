# Hermes Agent vs OpenCode 架构分析报告

> 分析日期：2026-06-25
> 目的：为 GrassFlow 项目提供架构参考

---

## 一、项目概览

### Hermes Agent (v0.17.0)
- **开发者**: Nous Research
- **定位**: 生产级自我改进型 AI Agent
- **技术栈**: Python 3.11-3.13 + TypeScript (TUI) + FastAPI
- **规模**: cli.py 15487行, run_agent.py 5574行, 107个文件
- **核心能力**: 内置学习循环、跨会话记忆搜索、20+平台网关、26+模型提供者、40+工具

### OpenCode
- **定位**: AI 编程助手
- **技术栈**: TypeScript + Bun + Effect-TS + SolidJS + OpenTUI + SQLite
- **规模**: ~20个包 monorepo
- **核心能力**: 四维 LLM 协议抽象、统一工具注册表、Skills 系统、MCP 集成

---

## 二、架构对比

### 2.1 REPL/会话模型

| 特性 | Hermes | OpenCode | GrassFlow (现状) |
|------|--------|----------|-----------------|
| 会话保持 | ✅ SQLite 持久化 | ✅ SQLite + Drizzle | ❌ 无会话 |
| 上下文压缩 | ✅ 压缩器抽象 | ✅ Compaction Agent | ❌ 无 |
| 中断处理 | ✅ 后台线程 + 标志位 | ✅ AbortSignal | ❌ 无 |
| 断点恢复 | ✅ /resume 命令 | ✅ Session fork/revert | ❌ 无 |

### 2.2 工具系统

| 特性 | Hermes | OpenCode | GrassFlow (现状) |
|------|--------|----------|-----------------|
| 工具注册 | 自注册 (AST扫描) | 统一注册表 | 无工具系统 |
| MCP 集成 | ✅ 双向 (Client+Server) | ✅ Local+Remote | ❌ 无 |
| 权限控制 | ✅ 审批流程 | ✅ allow/deny/ask | ❌ 无 |
| 并发安全 | ✅ 路径重叠检测 | ✅ Doom Loop 检测 | ❌ 无 |

### 2.3 Skills 系统

| 特性 | Hermes | OpenCode | GrassFlow (现状) |
|------|--------|----------|-----------------|
| 格式 | SKILL.md (YAML+MD) | SKILL.md (YAML+MD) | ❌ 无 |
| 发现机制 | 10+源适配器 | 多目录+URL | ❌ 无 |
| 渐进式披露 | ✅ 三层架构 | ✅ 列表→详情→文件 | ❌ 无 |
| 双触发 | ✅ AI自动+手动 | ✅ AI自动+/command | ❌ 无 |

---

## 三、Hermes Agent 核心设计

### 3.1 三线程模型

| 线程 | 职责 |
|------|------|
| **主线程** | prompt_toolkit UI 事件循环 |
| **process_loop** | 消费用户输入、执行命令、运行 Agent |
| **spinner_loop** | 驱动 UI 刷新（状态栏动画） |

### 3.2 输入路由状态机

| 当前状态 | 输入目标 |
|---------|---------|
| sudo 密码提示 | `_sudo_state["response_queue"]` |
| 审批选择 | `_approval_state["response_queue"]` |
| Agent 运行中 + interrupt | `_interrupt_queue` |
| Agent 运行中 + queue | `_pending_input` (排队) |
| Agent 运行中 + steer | `agent.steer()` (注入) |
| Agent 空闲 | `_pending_input` (立即处理) |

### 3.3 对话主循环

```
Prologue (一次性设置)
  → 系统提示词构建 / 预压缩 / 插件钩子 / 记忆预取
  ↓
主循环 (while iterations < max and budget > 0)
  → 中断检查 → 预算消费 → /steer 排空
  → 消息准备 (注入上下文、缓存控制、消毒)
  → 重试子循环 (错误分类 → 退避 → fallback 链 → 凭证轮换)
    → API 调用 (流式优先, 后台线程执行, 可中断)
    → 响应验证 (多 api_mode 分支)
  → 工具执行循环 (顺序/并发, 守卫检查, 中断传播)
  ↓
Epilogue (后处理)
  → 会话持久化 / 记忆同步 / 后台审查
```

### 3.4 Skills 渐进式披露

| 层级 | 工具 | 内容 | Token 消耗 |
|------|------|------|-----------|
| 第一层 | `skills_list` | name + description | 最小 |
| 第二层 | `skill_view` | SKILL.md 完整内容 | 中等 |
| 第三层 | `skill_view + file_path` | 支持文件按需加载 | 按需 |

### 3.5 MCP 客户端架构

- **连接生命周期**: 连接 → 发现工具 → 注册 → 等待 → 断开 → 重连（指数退避）
- **传输支持**: Stdio / HTTP / SSE
- **熔断器**: 连续 3 次失败触发，60 秒冷却后半开探测
- **Keepalive**: 优先 ping，不支持则降级到 list_tools

### 3.6 错误分类体系

```python
class FailoverReason(Enum):
    RATE_LIMITED = "rate_limited"
    AUTH_EXPIRED = "auth_expired"
    CONTEXT_OVERFLOW = "context_overflow"
    PROVIDER_ERROR = "provider_error"
    NETWORK_ERROR = "network_error"
    # ...
```

---

## 四、OpenCode 核心设计

### 4.1 四维 LLM 协议抽象

```
Route = Protocol + Endpoint + Auth + Framing
```

- **Protocol**: 语义 API 契约（请求 body schema + 流式响应状态机）
- **Endpoint**: 请求地址
- **Auth**: 认证方式
- **Framing**: 响应帧解码（SSE / AWS event stream）

**支持的协议**: AnthropicMessages, OpenAIChat, OpenAIResponses, OpenAICompatibleChat, BedrockConverse, Gemini

### 4.2 流式处理管线

```
HTTP Response Bytes
  → Framing.sse (UTF-8 解码 + SSE 帧解析)
  → Protocol.stream.event (JSON → 类型化事件)
  → Protocol.stream.step (状态机: 状态 + 事件 → LLMEvent[])
  → 应用层处理 (text-delta/tool-call/tool-result/...)
```

### 4.3 System Prompt 可组合 Source 系统

- 每个 Source 有 `key`、`load`、`baseline`、`update` 方法
- 支持增量更新（只发送 diff）
- 内置 Source：`core/environment`（工作目录、git 状态）、`core/date`

### 4.4 工具系统

**统一注册表**:
- 内置工具：shell, read, edit, write, glob, grep, webfetch, websearch, task, skill, apply_patch, question, lsp, plan, todo
- 插件工具：扫描 `{tool,tools}/*.{js,ts}` 文件
- MCP 工具：运行时动态注册

**横切关注点** (自动添加):
1. 参数验证 -- Schema 解码，失败自动让 LLM 重写
2. 输出截断 -- 超大输出自动截断

**权限系统**:
- 规则模型：`{ permission, pattern, action }` -- `"allow"` / `"deny"` / `"ask"`
- 用户可回复 `"once"` / `"always"` / `"reject"`
- `"always"` 保存权限，后续自动批准

### 4.5 MCP 集成

```json
{
  "mcp": {
    "my-server": {
      "type": "local",
      "command": ["node", "server.js"]
    },
    "remote-server": {
      "type": "remote",
      "url": "https://example.com/mcp"
    }
  }
}
```

**额外能力**:
- 当 MCP server 支持 resources 时，自动添加 3 个合成工具
- MCP server instructions 可注入 system prompt

### 4.6 Doom Loop 检测

- 同一工具被相同参数调用 3 次
- 自动询问用户是否继续
- 防止 Agent 陷入死循环

---

## 五、对 GrassFlow 的启发

### 5.1 高优先级借鉴

#### 1. LLM 协议抽象 (来自 OpenCode)

```python
class LLMRoute:
    protocol: Protocol     # OpenAI Chat / Anthropic Messages
    endpoint: str          # API 地址
    auth: AuthProvider     # API Key / OAuth
    framing: Framing       # SSE / JSON Lines
```

**好处**: 添加新 provider 只需定义 endpoint 和 auth，协议代码完全复用

#### 2. 统一工具注册表 (来自两者)

```python
class ToolRegistry:
    def register(self, tool_class):
        # AST 扫描自动发现
        pass
    
    def resolve(self, name, args):
        # 统一调用入口
        pass
```

**好处**: 内置工具、插件工具、MCP 工具在同一个 Registry 中管理

#### 3. Skills 系统 (来自两者)

```markdown
---
name: workflow-creator
description: 创建 GrassFlow 工作流
slash: true
---

# 技能内容
使用 DSL 语法创建工作流...
```

**好处**: 降低编写门槛，支持自动发现和双触发

#### 4. 结构化错误分类 (来自 Hermes)

```python
class FailoverReason(Enum):
    RATE_LIMITED = "rate_limited"
    AUTH_EXPIRED = "auth_expired"
    CONTEXT_OVERFLOW = "context_overflow"
    # ...
```

**好处**: 让重试/fallback 逻辑不再依赖字符串匹配

### 5.2 中优先级借鉴

#### 5. 会话持久化 + 断点恢复

- SQLite 存储会话历史
- 支持从断点恢复执行
- 执行历史可搜索

#### 6. 上下文压缩

- 检测 token 超限
- 用专门 Agent 摘要旧消息
- 保留最近 N 轮完整对话

#### 7. MCP 集成模式

- Local (stdio) + Remote (HTTP/SSE)
- 工具命名空间化
- 动态 tool list 更新

#### 8. 可中断 API 调用

- 后台线程执行 HTTP
- 主线程监控中断标志
- 单个 Agent 中断不影响其他

#### 9. 熔断器机制

- 连续 N 次失败触发
- 冷却期后半开探测
- 防止级联故障

### 5.3 低优先级但值得记住

#### 10. Doom Loop 检测

- 同一工具相同参数调用 3 次
- 自动询问用户是否继续

#### 11. 渐进式披露

- GUI 面板只显示最小信息
- 点击展开完整配置
- 按需加载工具定义

---

## 六、GrassFlow 差异化优势强化

| GrassFlow 优势 | 借鉴来源 | 强化方向 |
|---------------|---------|---------|
| **DAG 拓扑排序** | Hermes 并发安全规则 | 为 DAG 节点定义冲突检测 |
| **声明式 DSL** | Skills YAML frontmatter | Agent 定义标准化格式 |
| **多 Agent 并行** | Hermes 可中断 API | 精细资源控制 |
| **GUI + TUI 双模式** | OpenCode Client-Server | HTTP API + WebSocket |
| **监控 Agent** | Hermes curator | 从执行历史中学习 |

---

## 七、新架构建议

```
GrassFlow 新架构:

┌─────────────────────────────────────────────────────────────┐
│                    REPL 会话层                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Session Manager (SQLite 持久化)                        ││
│  │  Context Compressor (token 检测 + 摘要)                 ││
│  │  Input Router (状态机: 空闲/运行中/审批/中断)            ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    AI 对话引擎                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  LLM Protocol Layer (四维抽象)                          ││
│  │  Tool Executor (并发安全 + 权限控制)                    ││
│  │  Error Classifier (结构化错误)                          ││
│  │  Circuit Breaker (熔断器)                               ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    工具系统                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Tool Registry (自注册 + 统一入口)                      ││
│  │  Skills Manager (渐进式披露)                            ││
│  │  MCP Client/Server (双向集成)                           ││
│  │  Workflow Executor (DAG 编排)                           ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│                    TUI 界面层                                │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Rich TUI (消息渲染 + 状态栏)                           ││
│  │  Workflow Editor (交互式编辑)                           ││
│  │  Monitor Panel (实时监控)                               ││
│  │  Dialog System (权限审批 + 技能选择)                    ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 八、实现建议

### 阶段 1: 基础架构 (1-2周)
1. 实现 LLM 协议抽象层 (参考 OpenCode 四维模型)
2. 实现工具注册表 (参考 Hermes 自注册)
3. 实现 Skills 系统 (两者参考)
4. 实现结构化错误分类 (参考 Hermes)

### 阶段 2: 会话系统 (2-3周)
1. 实现 REPL 会话管理
2. 实现上下文压缩
3. 实现会话持久化
4. 实现断点恢复

### 阶段 3: MCP 集成 (1-2周)
1. 实现 MCP Client
2. 实现 MCP Server (暴露工作流为工具)
3. 实现工具权限控制

### 阶段 4: 高级特性 (2-3周)
1. 实现熔断器
2. 实现 Doom Loop 检测
3. 实现渐进式披露
4. 实现 AI 自动创建工作流

---

## 九、总结

### Hermes Agent 的优势
- 生产级成熟度高
- 三线程模型稳定
- 安全防护完善
- 插件架构灵活

### OpenCode 的优势
- 四维 LLM 抽象优雅
- Effect-TS 类型安全
- Skills 系统设计精巧
- Client-Server 架构清晰

### GrassFlow 的定位
- **多 Agent 编排** (核心差异化)
- **声明式 DSL** (降低门槛)
- **GUI + TUI 双模式** (覆盖更多用户)
- **监控 Agent** (质量保障)

### 借鉴策略
1. **工程实践** 直接复用 (错误分类、抖动退避、熔断器)
2. **架构模式** 适配后使用 (自注册、插件化、渐进式披露)
3. **强化差异化** (DAG 编排、声明式 DSL、监控 Agent)
4. **避免过度复杂** (Hermes 的 cli.py 15487行是反模式)

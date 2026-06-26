# OpenCode CLI 架构深度分析

## 1. 整体程序结构

### 1.1 项目组织

OpenCode 是一个 **TypeScript monorepo** 项目，使用 **Bun** 作为运行时和包管理器，**Turbo** 做构建编排。

```
packages/
├── opencode/      # 主应用（CLI命令、服务器、MCP、Provider等核心逻辑）
├── core/          # 共享核心库（独立于主应用的底层能力）
├── schema/        # 数据模型 Schema 定义（使用 Effect Schema）
├── cli/           # CLI 入口（旧版/管理用，Effect-based）
├── tui/           # 终端 UI（SolidJS + OpenTUI）
├── llm/           # LLM 抽象层（AI SDK 封装）
├── server/        # HTTP API 服务器
├── sdk/           # TypeScript SDK
├── desktop/       # Electron 桌面应用
├── app/           # Web 应用前端
├── plugin/        # 插件系统
└── ...            # 其他辅助包
```

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| **运行时** | Bun (非 Node.js) |
| **语言** | TypeScript 严格模式 |
| **效果系统** | Effect-TS（核心抽象层） |
| **CLI 框架** | yargs |
| **TUI 框架** | SolidJS + @opentui/solid（自研 TUI 渲染引擎） |
| **数据验证** | Effect Schema（类似 Zod） |
| **数据库** | SQLite (via drizzle-orm + @effect/sql-sqlite-bun) |
| **HTTP 框架** | Hono |
| **LLM 抽象** | Vercel AI SDK (ai 包) |
| **MCP** | @modelcontextprotocol/sdk |

### 1.3 入口点

主入口在 `packages/opencode/src/index.ts`，使用 **yargs** 构建 CLI 命令树：

```typescript
// packages/opencode/src/index.ts
const cli = yargs(args)
  .command(RunCommand)       // opencode run [message]
  .command(TuiThreadCommand) // opencode tui
  .command(McpCommand)       // opencode mcp ...
  .command(ProvidersCommand) // opencode providers
  .command(AgentCommand)     // opencode agent
  .command(ModelsCommand)    // opencode models
  // ... 20+ 子命令
```

每个命令通过 `effectCmd()` 包装器接入 Effect 运行时。

---

## 2. CLI/TUI 实现

### 2.1 TUI 技术栈

OpenCode 的 TUI **不是** 传统的 Ink (React for CLI) 方案，而是使用自研的 **OpenTUI** 框架：

- `@opentui/core` - 终端渲染引擎（60fps，支持鼠标、Kitty 键盘协议）
- `@opentui/solid` - SolidJS 绑定层（JSX → 终端元素）
- `@opentui/keymap` - 键绑定系统

### 2.2 TUI 应用结构

TUI 入口在 `packages/tui/src/app.tsx`，采用 **SolidJS 组件树** 架构：

```tsx
// 简化的组件层级
<ExitProvider>
  <RouteProvider>           // 路由：home | session | plugin
    <SDKProvider>            // HTTP SDK 连接
      <SyncProvider>         // 数据同步
        <ThemeProvider>      // 主题系统
          <DialogProvider>   // 弹窗管理
            <App />
          </DialogProvider>
        </ThemeProvider>
      </SyncProvider>
    </SDKProvider>
  </RouteProvider>
</ExitProvider>
```

### 2.3 关键 TUI 组件

| 组件 | 文件 | 功能 |
|------|------|------|
| `DialogModel` | `component/dialog-model.tsx` | 模型选择弹窗 |
| `DialogAgent` | `component/dialog-agent.tsx` | Agent 切换弹窗 |
| `DialogMcp` | `component/dialog-mcp.tsx` | MCP 服务器管理 |
| `DialogSessionList` | `component/dialog-session-list.tsx` | 会话列表 |
| `DialogProvider` | `component/dialog-provider.tsx` | Provider 连接 |
| `CommandPaletteDialog` | `component/command-palette.tsx` | 命令面板（Ctrl+P） |
| `Session` | `routes/session/index.tsx` | 会话主界面 |

### 2.4 Slash Commands 系统

Slash commands 通过 **命令注册模式** 实现。在 `app.tsx` 中定义命令列表：

```typescript
const appCommands = [
  {
    name: "model.list",
    title: "Switch model",
    slashName: "models",     // 用户输入 /models 触发
    slashAliases: ["mo"],    // 支持别名
    run: () => dialog.replace(() => <DialogModel />),
  },
  {
    name: "session.list",
    slashName: "sessions",
    slashAliases: ["resume", "continue"],
    run: () => dialog.replace(() => <DialogSessionList />),
  },
  {
    name: "agent.list",
    slashName: "agents",
    run: () => dialog.replace(() => <DialogAgent />),
  },
  // ... 更多命令
]
```

命令通过 `useBindings()` hook 注册到 keymap 系统，支持：
- `slashName` - 主名称（`/models`）
- `slashAliases` - 别名（`/mo`）
- `category` - 分类（用于命令面板分组）
- `suggested` - 是否在命令面板中优先推荐

### 2.5 键绑定系统

键绑定通过 `OpencodeKeymapProvider` 管理：

```typescript
useBindings(() => ({
  mode: OPENCODE_BASE_MODE,
  bindings: tuiConfig.keybinds.gather("app", appBindingCommands),
}))
```

支持分层绑定：`app` > `app.global` > `app_exit`，以及模式切换。

---

## 3. MCP Server 支持

### 3.1 MCP 架构

MCP 实现在 `packages/opencode/src/mcp/index.ts`，是一个完整的 **Effect Service**：

```typescript
export class Service extends Context.Service<Service, Interface>()("@opencode/MCP") {}
```

### 3.2 MCP 配置格式

配置在 `opencode.json` 中的 `mcp` 字段：

```json
{
  "mcp": {
    "my-server": {
      "type": "local",
      "command": ["node", "server.js"],
      "cwd": "./mcp-servers",
      "environment": { "API_KEY": "xxx" },
      "timeout": 30000
    },
    "remote-server": {
      "type": "remote",
      "url": "https://mcp.example.com/sse",
      "headers": { "Authorization": "Bearer xxx" },
      "oauth": { "clientId": "...", "scope": "..." }
    }
  }
}
```

### 3.3 MCP 连接流程

```
配置读取 → 类型判断(local/remote)
  → local: StdioClientTransport (子进程)
  → remote: StreamableHTTPClientTransport → 失败回退 → SSEClientTransport
  → OAuth 认证流程（可选）
  → 获取工具列表
  → 注册到 ToolRegistry
  → 监听 ToolListChanged 通知
```

### 3.4 MCP 工具集成

MCP 工具通过 `McpCatalog.convertTool()` 转换为 AI SDK 的 `Tool` 格式，然后注入到 LLM 调用中。工具名格式为 `{serverName}_{toolName}`。

---

## 4. Provider 系统

### 4.1 Provider 数据模型

```typescript
// packages/schema/src/provider.ts
export const Info = Schema.Struct({
  id: ID,                    // "anthropic", "openai", "google", etc.
  integrationID: Schema.optional(Integration.ID),
  name: Schema.String,
  disabled: Schema.Boolean,
  api: Schema.Union([AISDK, Native]),  // 两种 API 类型
  request: Request,           // headers + body 模板
})
```

**两种 API 类型**：
- `AISDK` - 使用 Vercel AI SDK 的 provider 包（如 `@ai-sdk/anthropic`）
- `Native` - 原生 HTTP 调用

### 4.2 内置 Provider ID

```typescript
export const ID = Schema.String.pipe(
  Schema.brand("ProviderV2.ID"),
  withStatics((schema) => ({
    opencode: schema.make("opencode"),
    anthropic: schema.make("anthropic"),
    openai: schema.make("openai"),
    google: schema.make("google"),
    googleVertex: schema.make("google-vertex"),
    githubCopilot: schema.make("github-copilot"),
    amazonBedrock: schema.make("amazon-bedrock"),
    azure: schema.make("azure"),
    openrouter: schema.make("openrouter"),
    mistral: schema.make("mistral"),
    gitlab: schema.make("gitlab"),
  })),
)
```

### 4.3 Model 定义

```typescript
// packages/schema/src/model.ts
export const Info = Schema.Struct({
  id: ID,               // "claude-sonnet-4-20250514"
  name: Schema.String,  // 显示名
  family: Family,        // 模型家族分组
  api: Api,              // API 调用配置
  capabilities: Capabilities,  // 能力标记
  cost: Cost,            // 价格信息
  variants: Schema.optional(Schema.Array(Variant)),  // 变体（如 reasoning effort）
})
```

### 4.4 Provider 配置

用户可在 `opencode.json` 中自定义 provider：

```json
{
  "provider": {
    "custom-llm": {
      "name": "My Custom LLM",
      "api": {
        "type": "native",
        "settings": { "baseUrl": "https://api.example.com" }
      },
      "request": {
        "headers": { "Authorization": "Bearer ${env:API_KEY}" }
      }
    }
  }
}
```

---

## 5. 会话管理

### 5.1 Session 数据模型

会话存储在 **SQLite** 数据库中，使用 drizzle-orm：

```typescript
// 核心字段
SessionTable {
  id: string           // ULID
  title: string
  directory: string    // 工作目录
  project_id: string
  workspace_id: string?
  agent: string?       // 使用的 agent
  model: json?         // 使用的模型
  cost: number
  tokens: json         // token 统计
  time_created: number
  time_updated: number
}
```

### 5.2 Session 操作

```typescript
interface Interface {
  list(input?: ListInput): Effect<SessionSchema.Info[]>
  create(input: CreateInput): Effect<SessionSchema.Info>
  get(sessionID): Effect<SessionSchema.Info>
  messages(input): Effect<SessionMessage.Message[]>
  prompt(input): Effect<SessionInput.Admitted>    // 发送消息
  switchAgent(input): Effect<void>                // 切换 Agent
  switchModel(input): Effect<void>                // 切换模型
  compact(input): Effect<void>                    // 压缩上下文
  interrupt(sessionID): Effect<void>              // 中断执行
  revert: { stage, clear, commit }               // 回滚
}
```

### 5.3 会话恢复

通过 `--continue` / `--session` / `--fork` 参数：

```bash
opencode run --continue           # 继续最近会话
opencode run --session <id>       # 恢复指定会话
opencode run --continue --fork    # fork 后继续
```

TUI 中通过 `DialogSessionList` 组件实现交互式选择。

---

## 6. Agent 系统

### 6.1 Agent 定义

```typescript
// packages/core/src/config/agent.ts
export class Info {
  model?: string           // 默认模型
  variant?: string         // 模型变体
  request?: Request        // 请求覆盖
  system?: string          // 系统提示词
  description?: string     // 描述
  mode?: "subagent" | "primary" | "all"  // Agent 模式
  hidden?: boolean
  color?: string
  steps?: number           // 最大步数
  disabled?: boolean
  permissions?: Permission.Ruleset  // 权限规则
}
```

### 6.2 内置 Agent

- `build` - 默认主 Agent
- 支持自定义 Agent 通过配置或 `.opencode/agents/` 目录

### 6.3 Subagent 机制

Agent 可以声明为 `mode: "subagent"`，作为工具被主 Agent 调用。主 Agent 通过 `task` 工具派发子任务。

---

## 7. 工具系统

### 7.1 Tool 定义模式

```typescript
// packages/core/src/tool/tool.ts
export function make<Input, Output>(config: {
  description: string
  input: Input              // Effect Schema
  output: Output            // Effect Schema
  execute: (input, context) => Effect<Output, ToolFailure>
  toModelOutput?: (input, output) => Content[]
}): Definition<Input, Output>
```

### 7.2 内置工具

| 工具 | 文件 | 功能 |
|------|------|------|
| `bash` | `tool/bash.ts` | Shell 命令执行 |
| `read` | `tool/read.ts` | 文件读取 |
| `write` | `tool/write.ts` | 文件写入 |
| `edit` | `tool/edit.ts` | 文件编辑 |
| `glob` | `tool/glob.ts` | 文件搜索 |
| `grep` | `tool/grep.ts` | 内容搜索 |
| `skill` | `tool/skill.ts` | 技能加载 |
| `todowrite` | `tool/todowrite.ts` | 任务列表 |
| `webfetch` | `tool/webfetch.ts` | 网页抓取 |
| `websearch` | `tool/websearch.ts` | 网页搜索 |
| `question` | `tool/question.ts` | 向用户提问 |

### 7.3 工具注册

工具通过 `ToolRegistry` 注册，支持：
- 动态注册/注销（Scope-based）
- 权限控制（Permission.Ruleset）
- Schema 验证（输入输出自动校验）
- 输出截断（ToolOutputStore）

---

## 8. Skills 系统

### 8.1 Skill 定义

Skill 是 **Markdown 文件**，带有 frontmatter 元数据：

```markdown
---
name: tdd
description: Test-driven development workflow
slash: true
---

# TDD Skill

When developing with TDD:
1. Write failing test first
2. Implement minimal code to pass
3. Refactor
...
```

### 8.2 Skill 来源

```typescript
export type Source =
  | { type: "directory"; path: string }   // 本地目录
  | { type: "url"; url: string }           // 远程 URL
  | { type: "embedded"; skill: Info }      // 内嵌定义
```

### 8.3 Skill 发现机制

1. **配置文件** - `opencode.json` 中的 `skills` 字段指定额外路径/URL
2. **目录扫描** - 扫描 `{*.md,**/SKILL.md}` 文件
3. **远程拉取** - 从 URL 下载 `index.json` + skill 文件
4. **权限过滤** - 根据 Agent 的 permissions 过滤可用 skill

### 8.4 Skill 作为工具

Skill 通过 `skill` 工具被 LLM 调用，加载后将内容注入到对话上下文中。

---

## 9. 配置系统

### 9.1 配置层级

```
全局配置: ~/.config/opencode/opencode.jsonc
    ↓ 合并
项目配置: ./opencode.jsonc (项目根目录)
    ↓ 合并
目录配置: .opencode/opencode.jsonc (向上搜索)
    ↓ 合并
环境变量: OPENCODE_CONFIG_CONTENT, OPENCODE_CONFIG
    ↓ 合并
远程配置: .well-known/opencode (企业部署)
```

### 9.2 配置结构（关键字段）

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-20250514",
  "shell": "/bin/bash",
  "agent": {
    "build": { "model": "...", "system": "..." },
    "custom-agent": { "mode": "primary", "description": "..." }
  },
  "mcp": { /* MCP 服务器配置 */ },
  "provider": { /* 自定义 Provider */ },
  "commands": { /* 自定义斜杠命令 */ },
  "permissions": { /* 工具权限规则 */ },
  "skills": ["./skills", "https://example.com/skills"],
  "plugins": ["@opencode-ai/plugin-github"],
  "compaction": { "auto": true, "threshold": 80000 },
  "experimental": { /* 实验性功能 */ }
}
```

### 9.3 配置特性

- **JSONC 支持** - 支持注释和尾逗号
- **变量替换** - `${env:VAR}`, `${file:path}` 等
- **热更新** - 文件变更自动重载
- **Schema 验证** - 编辑器自动补全
- **V1 迁移** - 自动迁移旧版配置格式

---

## 10. 可移植到 Python 的设计

### 10.1 推荐移植的架构模式

| 模式 | 说明 | Python 实现建议 |
|------|------|----------------|
| **Effect Service 模式** | 依赖注入 + 生命周期管理 | `dataclass` + `contextmanager` 或 `inject` 库 |
| **Schema-first 数据模型** | 用 Schema 定义一切数据结构 | Pydantic v2 或 msgspec |
| **Tool 注册模式** | 统一的工具定义 + Schema 验证 | 装饰器 + Pydantic |
| **Command 注册模式** | 声明式命令定义 | Click/Typer 或自定义注册器 |
| **Skill 发现机制** | Markdown + frontmatter | Python-Markdown + frontmatter 解析 |
| **配置层级合并** | 多级配置 + 环境变量覆盖 | pydantic-settings 或 dynaconf |
| **Session 事件流** | Server-Sent Events 实时推送 | asyncio + SSE |

### 10.2 关键设计决策

1. **Effect-TS → Python 的映射**
   - Effect 的 `Service` 模式 ≈ Python 的 Protocol + 依赖注入
   - Effect 的 `Schema` ≈ Pydantic BaseModel
   - Effect 的 `Layer` ≈ Python 的 contextmanager 组合

2. **TUI 框架选择**
   - OpenTUI 是自研的 SolidJS TUI 引擎，Python 无法直接复用
   - 建议使用 **Textual**（Python TUI 框架，支持 CSS-like 布局）
   - 或继续使用 **Rich** + 自定义组件

3. **MCP 集成**
   - Python 有官方 MCP SDK：`mcp` 包
   - 可直接使用 `StdioClientTransport` 和 `SSEClientTransport`

4. **LLM 抽象层**
   - OpenCode 使用 Vercel AI SDK
   - Python 建议使用 **LiteLLM**（已集成在 GrassFlow 计划中）

### 10.3 GrassFlow 可借鉴的具体实现

1. **命令注册系统** - OpenCode 的 `appCommands` 模式非常适合 GrassFlow 的 slash commands
2. **Skill 系统** - Markdown + frontmatter 的 skill 定义可以直接复用
3. **MCP 配置格式** - local/remote 两种类型的配置结构
4. **Session 恢复** - `--continue` / `--session` / `--fork` 的 CLI 参数设计
5. **Provider 抽象** - AISDK/Native 两种 API 类型的设计思路
6. **工具权限系统** - Permission.Ruleset 的规则匹配模式

---

## 11. 总结

OpenCode 是一个架构非常成熟的 AI 编码助手，其核心特点：

1. **Effect-TS 贯穿全局** - 所有副作用都通过 Effect 管理，提供出色的错误处理和资源安全
2. **SolidJS TUI** - 自研终端渲染引擎，60fps 流畅体验
3. **声明式配置** - Schema-first 的数据模型，编辑器友好
4. **插件化架构** - MCP、Provider、Plugin、Skill 四层扩展机制
5. **会话持久化** - SQLite 存储，支持完整的会话生命周期管理

对于 GrassFlow 项目，最值得借鉴的是其 **Skill 系统**、**MCP 配置格式** 和 **Tool 注册模式**，这些可以直接用 Python 实现。

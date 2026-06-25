# OpenCode TUI 源码分析

## 1. 总体架构概览

OpenCode 的 TUI 采用 **TypeScript + SolidJS** 构建，运行在自定义的终端渲染框架 `@opentui` 之上。整个项目是一个 monorepo，TUI 相关代码主要分布在以下包中：

| 包名 | 职责 |
|------|------|
| `packages/tui/` | TUI 核心实现（路由、组件、上下文、插件） |
| `packages/cli/` | CLI 入口，启动 TUI |
| `packages/opencode/` | 业务逻辑层（命令、配置、会话管理等） |
| `packages/ui/` | 共享 UI 组件（主要用于桌面/Web 端，非 TUI） |
| `packages/session-ui/` | 会话 UI 组件（Markdown 渲染、文件展示等） |
| `packages/core/` | 核心共享逻辑（配置、工具、数据库等） |

---

## 2. TUI 框架：@opentui

### 2.1 框架组成

TUI 不使用 Ink、Blessed 或其他常见框架，而是使用自研的 `@opentui` 框架套件：

```
@opentui/core     — 底层渲染引擎（CLI Renderer）
@opentui/solid    — SolidJS 绑定层（类似 ink 对 React 的绑定）
@opentui/keymap   — 键盘映射系统
opentui-spinner   — 加载动画组件
```

### 2.2 渲染机制

- **渲染器创建**：通过 `createCliRenderer()` 创建终端渲染器，配置包括：
  - `targetFps: 60` — 60FPS 渲染
  - `externalOutputMode: "passthrough"` — 外部输出透传
  - `exitOnCtrlC: false` — 自定义 Ctrl+C 处理
  - `useKittyKeyboard: {}` — 支持 Kitty 键盘协议
  - `useMouse: true` — 鼠标支持（可配置）

- **SolidJS 绑定**：`@opentui/solid` 提供 `render()` 函数，类似 React 的 `ReactDOM.render()`，将 SolidJS 组件树渲染到终端。

- **内置原语**：框架提供类似 HTML 的原语元素：
  - `<box>` — 布局容器（类似 div）
  - `<text>` — 文本渲染
  - `<scrollbox>` — 可滚动容器
  - `<code>` — 代码块（带语法高亮）
  - `<markdown>` — Markdown 渲染
  - `<diff>` — Diff 渲染（支持 split/unified 视图）
  - `<line_number>` — 行号显示
  - `<span>` — 行内样式

- **布局系统**：采用 Flexbox 布局（`flexDirection`, `flexGrow`, `flexShrink`, `alignItems` 等），与 CSS Flexbox 类似。

---

## 3. CLI 入口流程

### 3.1 启动链

```
packages/cli/src/index.ts
  → Runtime.run(Commands, Handlers)
    → handlers["$"] (default handler)
      → packages/cli/src/commands/handlers/default.ts
        → Daemon.Service → 获取 transport
        → import("../../tui") → runTui(transport)
          → packages/cli/src/tui.ts
            → TuiConfig.resolve() → 配置解析
            → run({ url, args, config, fetch, pluginHost })
              → packages/tui/src/app.tsx → run() (Effect)
                → createCliRenderer() → 创建渲染器
                → render(<App />, renderer) → 渲染应用
```

### 3.2 关键文件

- **`packages/cli/src/index.ts`**：CLI 主入口，使用 Effect 框架的命令行解析
- **`packages/cli/src/commands/commands.ts`**：命令定义（`api`, `debug`, `migrate`, `service`, `serve`）
- **`packages/cli/src/commands/handlers/default.ts`**：默认处理器，启动 TUI
- **`packages/cli/src/tui.ts`**：TUI 启动桥接，调用 `@opencode-ai/tui` 的 `run()`
- **`packages/cli/src/services/daemon.ts`**：守护进程服务，管理后台服务器

---

## 4. TUI 应用结构

### 4.1 入口文件 (`packages/tui/src/index.tsx`)

仅导出 `run` 函数和 `TuiInput` 类型。

### 4.2 核心文件 (`packages/tui/src/app.tsx`)

`run()` 函数是一个 Effect generator，负责：

1. 创建 `CliRenderer` 渲染器
2. 注册键盘映射（`registerOpencodeKeymap`）
3. 初始化插件运行时
4. 渲染整个 Provider 树
5. 等待关闭信号

### 4.3 Provider 层级

应用采用深层嵌套的 Context Provider 模式：

```
ExitProvider
  EpilogueProvider
    ErrorBoundary
      TuiPathsProvider (cwd, home, state, worktree)
        TuiTerminalEnvironmentProvider (platform, multiplexer, displayServer)
          TuiStartupProvider (initialRoute, skipInitialLoading)
            ClipboardProvider
              OpencodeKeymapProvider
                ArgsProvider
                  KVProvider (键值存储)
                    ToastProvider
                      RouteProvider
                        TuiConfigProvider
                          PluginRuntimeProvider
                            SDKProvider (url, fetch, events)
                              ProjectProvider
                                SyncProvider
                                  DataProvider
                                    ThemeProvider
                                      LocalProvider
                                        PromptStashProvider
                                          DialogProvider
                                            FrecencyProvider
                                              PromptHistoryProvider
                                                PromptRefProvider
                                                  EditorContextProvider
                                                    LocationProvider
                                                      <App />
```

### 4.4 路由系统

路由通过 `RouteProvider` 管理，支持三种路由类型：

```typescript
type Route = HomeRoute | SessionRoute | PluginRoute

// HomeRoute: 主页（Logo + Prompt）
// SessionRoute: 会话页面（消息列表 + Prompt）
// PluginRoute: 插件自定义页面
```

路由状态使用 SolidJS Store 管理，通过 `useRoute()` 和 `useRouteData()` 访问。

### 4.5 App 组件

`App` 组件是顶层渲染组件，负责：

- 注册全局命令（`appCommands`）：session.list, session.new, model.list, agent.list, theme.switch 等
- 注册全局快捷键绑定
- 处理事件（session.deleted, session.error, installation.update-available）
- 根据路由渲染不同页面：

```tsx
<Switch>
  <Match when={route.data.type === "home"}>
    <Home />
  </Match>
  <Match when={route.data.type === "session"}>
    <Session />
  </Match>
</Switch>
{plugin()}  // 插件路由
```

---

## 5. 页面组件

### 5.1 Home 页面 (`packages/tui/src/routes/home.tsx`)

- 居中显示 Logo
- 底部显示 Prompt 输入框
- 支持插槽（`home_logo`, `home_prompt`, `home_prompt_right`, `home_bottom`, `home_footer`）
- Prompt 最大宽度可配置（固定值或 `auto` 按终端宽度 70% 缩放）

### 5.2 Session 页面 (`packages/tui/src/routes/session/index.tsx`)

这是最复杂的页面，包含：

- **消息列表**：使用 `<scrollbox>` 渲染，支持粘性滚动（`stickyScroll`, `stickyStart="bottom"`）
- **消息类型**：
  - `UserMessage` — 用户消息（左侧彩色边框）
  - `AssistantMessage` — 助手消息（包含多个 Part）
  - `TextPart` — 文本部分（Markdown 渲染）
  - `ToolPart` — 工具调用（多种显示模式）
  - `ReasoningPart` — 思考过程（可折叠）
- **工具显示**：
  - `InlineTool` — 单行工具显示
  - `BlockTool` — 块级工具显示（带代码/Diff）
  - 特化组件：`Shell`, `Read`, `Write`, `Edit`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `Task`, `ApplyPatch`, `TodoWrite`, `Question`, `Skill`
- **侧边栏**：显示文件变更、MCP 状态、TODO 等
- **权限提示**：`PermissionPrompt`, `QuestionPrompt`
- **子代理**：`SubagentFooter`, `Task` 工具显示

---

## 6. 上下文系统

### 6.1 核心 Context

| Context | 文件 | 用途 |
|---------|------|------|
| `RouteProvider` | `context/route.tsx` | 路由状态管理 |
| `SDKProvider` | `context/sdk.tsx` | API 客户端 |
| `SyncProvider` | `context/sync.tsx` | 数据同步（session, message, part 等） |
| `ThemeProvider` | `context/theme.tsx` | 主题管理（dark/light） |
| `ProjectProvider` | `context/project.tsx` | 项目/工作区管理 |
| `LocalProvider` | `context/local.tsx` | 本地状态（agent, model 选择） |
| `DialogProvider` | `ui/dialog.tsx` | 对话框栈管理 |
| `KVProvider` | `context/kv.tsx` | 键值持久存储 |
| `ArgsProvider` | `context/args.tsx` | CLI 参数 |
| `ClipboardProvider` | `context/clipboard.tsx` | 剪贴板操作 |
| `ExitProvider` | `context/exit.tsx` | 退出处理 |
| `EpilogueProvider` | `context/epilogue.tsx` | 退出时的消息 |
| `EditorContextProvider` | `context/editor.ts` | 外部编辑器集成 |
| `LocationProvider` | `context/location.tsx` | 当前目录/工作区位置 |
| `PromptRefProvider` | `context/prompt.tsx` | Prompt 输入框引用 |
| `PluginRuntimeProvider` | `plugin/runtime.tsx` | 插件运行时 |

### 6.2 数据同步 (`SyncProvider`)

`SyncProvider` 是数据层的核心，管理以下数据：

```typescript
{
  session: Session[]          // 会话列表
  message: Record<string, Message[]>  // 消息（按 sessionID 索引）
  part: Record<string, Part[]>        // 消息部分（按 messageID 索引）
  provider: Provider[]        // LLM 提供商列表
  agent: Agent[]              // Agent 列表
  config: Config              // 服务器配置
  permission: Record<string, PermissionRequest[]>  // 权限请求
  question: Record<string, QuestionRequest[]>      // 问题请求
  session_status: Record<string, SessionStatus>    // 会话状态
  // ... 更多
}
```

通过 SDK 与后端服务器通信，支持事件订阅（SSE/WebSocket）。

---

## 7. 键盘映射系统

### 7.1 架构

使用 `@opentui/keymap` 库，提供：

- **键绑定注册**：`useBindings()` hook
- **命令系统**：命令名 → 处理函数
- **模式栈**：`createOpencodeModeStack()` 支持多层模式（如 modal 叠加在 base 上）
- **Leader 键**：支持 Vim 风格的 leader 键序列（默认超时 2000ms）
- **命令面板**：`CommandPaletteDialog` 展示所有可用命令

### 7.2 命令分类

- **Session 命令**：share, rename, timeline, fork, compact, undo, redo, export 等
- **Model 命令**：list, cycle_recent, cycle_favorite 等
- **Agent 命令**：list, cycle 等
- **System 命令**：theme.switch, help.show, app.exit, app.debug 等
- **Input 命令**：move, select, delete, word, undo/redo 等

### 7.3 Slash 命令

支持 `/` 前缀命令（如 `/sessions`, `/models`, `/agents`, `/help`），通过 `useCommandSlashes()` 获取。

---

## 8. 插件系统

### 8.1 插件运行时 (`packages/tui/src/plugin/runtime.tsx`)

```typescript
type TuiPluginHost = {
  start(input: { api, config, runtime, dispose }): Promise<void>
  dispose(): Promise<void>
}
```

### 8.2 插槽系统 (`packages/tui/src/plugin/slots.tsx`)

支持在预定义位置注入插件内容：

- `home_logo`, `home_prompt`, `home_prompt_right`, `home_bottom`, `home_footer`
- `session_prompt`, `session_prompt_right`
- `app`, `app_bottom`

使用 `<pluginRuntime.Slot name="..." />` 渲染。

### 8.3 插件路由

插件可以注册自定义路由，通过 `pluginRuntime.routes` 管理。

---

## 9. 配置系统

### 9.1 TUI 配置 (`packages/tui/src/config/index.tsx`)

```typescript
type Info = {
  $schema?: string
  theme?: string
  keybinds?: KeybindOverrides
  plugin?: PluginSpec[]
  plugin_enabled?: Record<string, boolean>
  leader_timeout?: number
  attention?: AttentionConfig
  prompt?: { max_height?: number; max_width?: number | "auto" }
  scroll_speed?: number
  scroll_acceleration?: { enabled: boolean }
  diff_style?: "auto" | "stacked"
  mouse?: boolean
}
```

### 9.2 配置解析

`TuiConfig.resolve()` 将用户配置与默认值合并，生成 `Resolved` 配置。

---

## 10. 对话框系统

### 10.1 架构 (`packages/tui/src/ui/dialog.tsx`)

- **栈式管理**：`DialogProvider` 维护一个对话框栈
- **方法**：
  - `replace(element)` — 替换当前对话框
  - `clear()` — 关闭所有对话框
  - `stack` — 获取当前栈
  - `setSize(size)` — 设置对话框大小（medium/large/xlarge）
- **内置对话框**：
  - `DialogAlert` — 提示框
  - `DialogConfirm` — 确认框
  - `DialogSelect` — 选择列表
  - `DialogPrompt` — 输入框
  - `DialogHelp` — 帮助信息
  - `DialogExportOptions` — 导出选项

### 10.2 业务对话框

- `DialogModel` — 模型选择
- `DialogAgent` — Agent 选择
- `DialogMcp` — MCP 管理
- `DialogSessionList` — 会话列表
- `DialogSessionRename` — 会话重命名
- `DialogTimeline` — 消息时间线
- `DialogThemeList` — 主题列表
- `DialogProvider` — 提供商连接
- `DialogStatus` — 状态查看
- `CommandPaletteDialog` — 命令面板

---

## 11. 主题系统

### 11.1 主题结构 (`packages/tui/src/context/theme.tsx`)

主题包含颜色变量：

```typescript
{
  background, backgroundPanel, backgroundElement, backgroundMenu,
  text, textMuted, textInverted,
  primary, secondary, accent,
  border, borderActive,
  error, warning, success, info,
  diffAdded, diffRemoved, diffAddedBg, diffRemovedBg, diffContextBg,
  markdownText,
  // ...
}
```

支持 dark/light 模式切换，可锁定模式。

---

## 12. 关键依赖

| 依赖 | 用途 |
|------|------|
| `solid-js` | 响应式 UI 框架 |
| `@opentui/core` | 终端渲染引擎 |
| `@opentui/solid` | SolidJS 终端绑定 |
| `@opentui/keymap` | 键盘映射 |
| `effect` | Effect-TS 函数式框架 |
| `@opencode-ai/core` | 核心业务逻辑 |
| `@opencode-ai/sdk` | API 客户端 |
| `@opencode-ai/plugin` | 插件系统 |
| `clipboardy` | 剪贴板操作 |
| `strip-ansi` | ANSI 转义码处理 |
| `diff` | Diff 计算 |
| `fuzzysort` | 模糊搜索 |
| `open` | 打开外部链接 |

---

## 13. 文件结构总结

```
packages/tui/src/
├── index.tsx              # 导出入口
├── app.tsx                # 主应用（run + App 组件）
├── runtime.tsx            # 路径工具函数
├── keymap.tsx             # 键盘映射系统
├── logo.ts                # Logo 渲染
├── config/
│   ├── index.tsx          # TUI 配置定义与解析
│   └── keybind.ts         # 键绑定配置
├── context/               # Context Providers
│   ├── args.tsx           # CLI 参数
│   ├── clipboard.tsx      # 剪贴板
│   ├── data.tsx           # 数据层
│   ├── editor.ts          # 编辑器集成
│   ├── epilogue.tsx       # 退出消息
│   ├── event.ts           # 事件系统
│   ├── exit.tsx           # 退出处理
│   ├── kv.tsx             # 键值存储
│   ├── local.tsx          # 本地状态
│   ├── location.tsx       # 位置信息
│   ├── project.tsx        # 项目管理
│   ├── prompt.tsx         # Prompt 引用
│   ├── route.tsx          # 路由管理
│   ├── runtime.tsx        # 运行时环境
│   ├── sdk.tsx            # SDK 客户端
│   ├── sync.tsx           # 数据同步
│   └── theme.tsx          # 主题管理
├── routes/                # 页面路由
│   ├── home.tsx           # 主页
│   └── session/           # 会话页面
│       ├── index.tsx      # 会话主组件
│       ├── footer.tsx     # 底部栏
│       ├── sidebar.tsx    # 侧边栏
│       ├── permission.tsx # 权限提示
│       ├── question.tsx   # 问题提示
│       └── ...
├── component/             # 组件
│   ├── prompt/            # Prompt 输入组件
│   │   ├── index.tsx      # 主 Prompt
│   │   ├── autocomplete.tsx
│   │   ├── history.tsx
│   │   └── ...
│   ├── dialog-*.tsx       # 各种对话框
│   ├── spinner.tsx        # 加载动画
│   └── ...
├── ui/                    # 基础 UI 组件
│   ├── dialog.tsx         # 对话框系统
│   ├── dialog-alert.tsx
│   ├── dialog-confirm.tsx
│   ├── dialog-select.tsx
│   ├── toast.tsx          # Toast 通知
│   ├── border.ts          # 边框样式
│   ├── link.tsx           # 链接组件
│   └── spinner.ts         # Spinner 样式
├── plugin/                # 插件系统
│   ├── runtime.tsx        # 插件运行时
│   ├── api.ts             # 插件 API
│   ├── adapters.tsx       # 适配器
│   ├── slots.tsx          # 插槽系统
│   └── command-shim.ts    # 命令垫片
├── feature-plugins/       # 内置功能插件
│   ├── builtins.ts
│   ├── home/              # 主页插件
│   ├── sidebar/           # 侧边栏插件
│   └── system/            # 系统插件（diff, notifications, which-key）
├── prompt/                # Prompt 相关
│   ├── display.ts
│   ├── frecency.tsx
│   ├── history.tsx
│   ├── part.ts
│   ├── stash.tsx
│   └── traits.ts
├── theme/                 # 主题定义
│   └── index.ts
└── util/                  # 工具函数
    ├── error.ts
    ├── format.ts
    ├── locale.ts
    ├── model.ts
    ├── path.ts
    ├── persistence.ts
    ├── scroll.ts
    ├── selection.ts
    ├── session.ts
    └── ...
```

---

## 14. 对 GrassFlow 的参考价值

### 14.1 可借鉴的设计

1. **Provider 层级模式**：深层嵌套的 Context Provider 提供清晰的关注点分离
2. **路由系统**：简单的类型路由（home/session/plugin）适合 TUI 场景
3. **对话框栈**：栈式对话框管理，支持 ESC/CTRL+C 关闭
4. **键盘映射**：完整的键绑定系统，支持 Leader 键、模式栈、命令面板
5. **插槽系统**：插件可通过命名插槽注入 UI
6. **数据同步**：SDK + 事件订阅的实时数据同步模式

### 14.2 差异化方向

1. **DSL 驱动**：GrassFlow 的 DSL 语法是核心差异点
2. **DAG 可视化**：需要在 TUI 中展示 DAG 图（可用 ASCII art 或简化视图）
3. **Python 技术栈**：使用 Python Rich 库而非 TypeScript
4. **编排 vs 对话**：GrassFlow 关注多 Agent 编排，而非单 Agent 对话

### 14.3 技术选型建议

对于 GrassFlow TUI（Python）：

| OpenCode (TS) | GrassFlow (Python) 对应 |
|---------------|------------------------|
| SolidJS | Rich Live/Layout |
| @opentui/core | Rich Console + 自定义渲染器 |
| @opentui/keymap | 键盘事件处理（readchar/keyboard） |
| Context Provider | 类实例 + 依赖注入 |
| Route Provider | 状态机（FSM） |
| Dialog Stack | 类似栈管理 |
| SDK + Events | HTTP Client + WebSocket |

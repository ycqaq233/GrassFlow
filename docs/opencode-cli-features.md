# OpenCode CLI 功能完整提取

> 来源: https://opencode.ai/docs/zh-cn (中文文档)
> 提取日期: 2026-06-25

---

## 1. 产品概述

OpenCode 是一个开源的 AI 编码代理，提供三种使用方式：
- **终端界面 (TUI)** — 交互式终端界面
- **桌面应用 (Desktop)** — 桌面客户端
- **IDE 扩展** — 编辑器集成

---

## 2. 交互模式

### 2.1 Plan 模式（计划模式）
- 不会进行任何修改，只会建议"如何"实现功能
- 使用 **Tab** 键在 Plan 和 Build 模式之间切换
- 右下角显示模式指示器

### 2.2 Build 模式（构建模式）
- 默认模式，允许执行所有工具操作
- 使用 **Tab** 键切换回 Build 模式后可让 Agent 开始实施

---

## 3. TUI 内置 Slash 命令

| 命令 | 别名 | 快捷键 | 描述 |
|------|------|--------|------|
| `/connect` | — | — | 添加 LLM 提供商，配置 API 密钥 |
| `/compact` | `/summarize` | `ctrl+x c` | 压缩当前会话上下文 |
| `/details` | — | — | 切换工具执行详情显示 |
| `/editor` | — | `ctrl+x e` | 打开外部编辑器编写消息 |
| `/exit` | `/quit`, `/q` | `ctrl+x q` | 退出 OpenCode |
| `/export` | — | `ctrl+x x` | 导出当前对话为 Markdown 并在编辑器中打开 |
| `/help` | — | — | 显示帮助对话框 |
| `/init` | — | — | 引导创建或更新 `AGENTS.md` 文件 |
| `/models` | — | `ctrl+x m` | 列出可用模型 |
| `/new` | `/clear` | `ctrl+x n` | 开始新会话 |
| `/redo` | — | `ctrl+x r` | 重做之前撤销的消息（同时恢复文件更改） |
| `/sessions` | `/resume`, `/continue` | `ctrl+x l` | 列出并切换会话 |
| `/share` | — | — | 分享当前会话（生成公开链接） |
| `/themes` | — | `ctrl+x t` | 列出可用主题 |
| `/thinking` | — | — | 切换思维/推理块的显示（不影响模型推理能力） |
| `/undo` | — | `ctrl+x u` | 撤销最后一条消息（同时还原文件更改，需要 Git 仓库） |
| `/unshare` | — | — | 取消分享当前会话 |

---

## 4. 文件引用（@ 引用）

- 使用 `@` 符号在消息中引用文件
- 支持模糊文件搜索
- 示例: `How is auth handled in @packages/functions/src/api/index.ts?`
- 文件内容会自动添加到对话中
- 配置的 references 也会出现在 `@` 自动补全中
- 使用 `@alias` 添加引用根目录为上下文，`@alias/` 自动补全引用中的文件

---

## 5. Bash 命令注入

- 消息以 `!` 开头可执行 shell 命令
- 示例: `!ls -la`
- 命令输出会作为工具结果添加到对话中

---

## 6. 图片支持

- 可以将图片拖放到终端窗口
- 图片会被扫描并添加到提示词中
- 图片附件配置:
  - `auto_resize` — 自动调整超过限制的图片
  - `max_width` — 最大宽度（默认 2000px）
  - `max_height` — 最大高度（默认 2000px）
  - `max_base64_bytes` — 最大 base64 编码大小（默认 5242880 字节）

---

## 7. 撤销/重做

- `/undo` — 撤销最后一条消息及其所有文件更改
- `/redo` — 重做之前撤销的消息
- 内部使用 Git 管理文件更改，**项目必须是 Git 仓库**
- 快捷键: `ctrl+x u` (撤销), `ctrl+x r` (重做)

---

## 8. 会话分享

### 分享模式
- `"manual"` — 手动分享（默认），通过 `/share` 命令
- `"auto"` — 自动分享所有新对话
- `"disabled"` — 完全禁用分享

### 链接格式
- 生成唯一公开 URL: `opncd.ai/s/<share-id>`
- 可通过 `/unshare` 取消分享并删除数据

---

## 9. 主题系统

### 内置主题
| 主题名 | 描述 |
|--------|------|
| `system` | 自适应终端背景色 |
| `tokyonight` | 基于 Tokyonight 主题 |
| `everforest` | 基于 Everforest 主题 |
| `ayu` | 基于 Ayu 暗色主题 |
| `catppuccin` | 基于 Catppuccin 主题 |
| `catppuccin-macchiato` | 基于 Catppuccin Macchiato 主题 |
| `gruvbox` | 基于 Gruvbox 主题 |
| `kanagawa` | 基于 Kanagawa 主题 |
| `nord` | 基于 Nord 主题 |
| `matrix` | 黑客风格绿底黑字主题 |
| `one-dark` | 基于 Atom One Dark 主题 |

### 自定义主题
- 支持 JSON 格式自定义主题
- 主题加载优先级: 内置 < 用户配置 < 项目根目录 < 当前工作目录
- 支持颜色格式: Hex、ANSI (0-255)、颜色引用、暗/亮变体、"none"（透明）

### 配置位置
- 用户全局: `~/.config/opencode/themes/*.json`
- 项目级: `.opencode/themes/*.json`

---

## 10. 快捷键系统

### Leader Key 机制
- 默认 `ctrl+x` 作为 leader key
- 很多操作需要先按 leader key 再按快捷键
- `leader_timeout` 控制等待下一个按键的时间（默认 2000ms）

### 核心快捷键（默认值）

**应用级:**
| 功能 | 快捷键 |
|------|--------|
| 退出 | `ctrl+c`, `ctrl+d`, `q` |
| 命令列表 | `ctrl+p` |
| 主题列表 | `t` |
| 侧边栏切换 | `b` |
| 状态查看 | `s` |

**会话管理:**
| 功能 | 快捷键 |
|------|--------|
| 新建会话 | `n` |
| 会话列表 | `l` |
| 会话时间线 | `g` |
| 会话重命名 | `ctrl+r` |
| 会话删除 | `ctrl+d` |
| 会话中断 | `escape` |
| 会话压缩 | `c` |
| 会话导出 | `x` |

**模型管理:**
| 功能 | 快捷键 |
|------|--------|
| 模型列表 | `m` |
| 提供商列表 | `ctrl+a` |
| 收藏切换 | `ctrl+f` |
| 循环最近模型 | `f2` / `shift+f2` |

**Agent 管理:**
| 功能 | 快捷键 |
|------|--------|
| Agent 列表 | `a` |
| Agent 循环 | `tab` / `shift+tab` |
| 变体循环 | `ctrl+t` |

**消息导航:**
| 功能 | 快捷键 |
|------|--------|
| 翻页上/下 | `pageup` / `pagedown` |
| 消息复制 | `y` |
| 消息撤销 | `u` |
| 消息重做 | `r` |
| 隐藏/显示 | `h` |

**子 Agent 导航:**
| 功能 | 快捷键 |
|------|--------|
| 进入第一个子会话 | `down` |
| 循环子会话 | `right` / `left` |
| 返回父会话 | `up` |

**输入编辑（Readline/Emacs 风格）:**
| 功能 | 快捷键 |
|------|--------|
| 行首/行尾 | `ctrl+a` / `ctrl+e` |
| 左/右移动 | `left`/`right` 或 `ctrl+b`/`ctrl+f` |
| 单词移动 | `alt+b`/`alt+f` 或 `ctrl+left`/`ctrl+right` |
| 删除到行尾 | `ctrl+k` |
| 删除到行首 | `ctrl+u` |
| 删除前一个单词 | `ctrl+w` 或 `ctrl+backspace` |
| 删除后一个单词 | `alt+d` |
| 换行 | `shift+return`, `ctrl+return`, `alt+return`, `ctrl+j` |
| 提交 | `return` |
| 清除输入 | `ctrl+c` |
| 粘贴 | `ctrl+v` |

### 自定义快捷键
- 通过 `tui.json` 的 `keybinds` 配置
- 支持逗号分隔的多快捷键、数组格式、对象格式
- 可设置为 `"none"` 或 `false` 禁用

---

## 11. CLI 命令

### 启动 TUI
```
opencode [project]
```
**标志:**
| 标志 | 简写 | 描述 |
|------|------|------|
| `--continue` | `-c` | 继续上一个会话 |
| `--session` | `-s` | 指定会话 ID 继续 |
| `--fork` | — | 分叉会话（配合 `--continue` 或 `--session`） |
| `--prompt` | — | 使用的提示词 |
| `--model` | `-m` | 使用的模型（格式: provider/model） |
| `--agent` | — | 使用的 Agent |
| `--port` | — | 监听端口 |
| `--hostname` | — | 监听主机名 |
| `--mdns` | — | 启用 mDNS 发现 |

### CLI 子命令

| 命令 | 描述 |
|------|------|
| `opencode agent create` | 创建新 Agent |
| `opencode agent list` | 列出所有 Agent |
| `opencode attach [url]` | 连接到运行中的后端服务器 |
| `opencode auth login` | 配置提供商 API 密钥 |
| `opencode auth list` | 列出已认证的提供商 |
| `opencode auth logout` | 登出提供商 |
| `opencode github install` | 安装 GitHub Agent |
| `opencode github run` | 运行 GitHub Agent |
| `opencode mcp add` | 添加 MCP 服务器 |
| `opencode mcp list` | 列出 MCP 服务器 |
| `opencode mcp auth [name]` | MCP OAuth 认证 |
| `opencode mcp logout [name]` | 移除 MCP OAuth 凭证 |
| `opencode mcp debug <name>` | 调试 MCP 连接 |
| `opencode models [provider]` | 列出可用模型 |
| `opencode run [message..]` | 非交互模式运行（脚本/自动化） |
| `opencode serve` | 启动无头服务器（API 访问） |
| `opencode session list` | 列出会话 |
| `opencode session delete` | 删除会话 |
| `opencode stats` | 显示 token 使用和成本统计 |
| `opencode export [sessionID]` | 导出会话为 JSON |
| `opencode import <file>` | 从 JSON 或分享 URL 导入会话 |
| `opencode web` | 启动 Web 界面 |
| `opencode acp` | 启动 ACP 服务器 |
| `opencode plugin <module>` | 安装插件 |
| `opencode pr <number>` | 获取并检出 GitHub PR |
| `opencode db [query]` | 数据库工具 |
| `opencode debug` | 调试工具 |
| `opencode uninstall` | 卸载 OpenCode |
| `opencode upgrade [target]` | 升级到最新/指定版本 |

### run 命令标志
| 标志 | 简写 | 描述 |
|------|------|------|
| `--command` | — | 要运行的命令 |
| `--continue` | `-c` | 继续上一个会话 |
| `--session` | `-s` | 指定会话 ID |
| `--share` | — | 分享会话 |
| `--model` | `-m` | 使用的模型 |
| `--agent` | — | 使用的 Agent |
| `--file` | `-f` | 附加文件 |
| `--format` | — | 输出格式: default 或 json |
| `--title` | — | 会话标题 |
| `--attach` | — | 连接到运行中的服务器 |
| `--variant` | — | 模型变体 |
| `--thinking` | — | 显示思维块 |
| `--dangerously-skip-permissions` | — | 自动批准未明确拒绝的权限 |

### 全局标志
| 标志 | 简写 | 描述 |
|------|------|------|
| `--help` | `-h` | 显示帮助 |
| `--version` | `-v` | 打印版本号 |
| `--print-logs` | — | 打印日志到 stderr |
| `--log-level` | — | 日志级别 (DEBUG, INFO, WARN, ERROR) |
| `--pure` | — | 不加载外部插件运行 |

---

## 12. 权限系统

### 权限值
- `"allow"` — 无需批准直接运行
- `"ask"` — 提示用户批准
- `"deny"` — 阻止操作

### 可用权限键
| 权限 | 控制的工具 |
|------|-----------|
| `read` | 读取文件 |
| `edit` | 所有文件修改（edit, write, patch） |
| `glob` | 文件模式匹配 |
| `grep` | 内容搜索 |
| `bash` | 执行 shell 命令 |
| `task` | 启动子 Agent |
| `skill` | 加载技能 |
| `lsp` | 运行 LSP 查询 |
| `question` | 向用户提问 |
| `webfetch` | 获取 URL |
| `websearch` | 网页搜索 |
| `external_directory` | 访问工作目录外的路径 |
| `doom_loop` | 同一工具调用重复 3 次时触发 |

### 默认权限
- 大多数权限默认 `"allow"`
- `doom_loop` 和 `external_directory` 默认 `"ask"`
- `read` 默认 `"allow"`，但 `.env` 文件默认 `"deny"`

### 粒度控制（对象语法）
```json
{
  "permission": {
    "bash": {
      "*": "ask",
      "git *": "allow",
      "npm *": "allow",
      "rm *": "deny"
    },
    "edit": {
      "*": "deny",
      "packages/web/src/content/docs/*.mdx": "allow"
    }
  }
}
```

### Ask 时的选项
- `once` — 仅批准本次请求
- `always` — 批准匹配模式的后续请求（当前会话内）
- `reject` — 拒绝请求

---

## 13. Agent 系统

### Agent 类型
- **Primary Agent** — 主要交互 Agent，使用 Tab 键循环切换
- **Subagent** — 子 Agent，可被主 Agent 自动调用或通过 `@` 手动调用

### 内置 Agent

**主 Agent:**
| Agent | 描述 |
|-------|------|
| `build` | **默认**主 Agent，所有工具可用 |
| `plan` | 受限 Agent，用于规划和分析，edit 和 bash 默认 `ask` |

**子 Agent:**
| Agent | 描述 |
|-------|------|
| `general` | 通用 Agent，用于研究复杂问题和执行多步任务 |
| `explore` | 快速只读 Agent，用于探索代码库 |
| `scout` | 只读 Agent，用于外部文档和依赖研究 |

**系统 Agent（隐藏，不可选择）:**
| Agent | 描述 |
|-------|------|
| `compaction` | 自动压缩长上下文 |
| `title` | 生成短会话标题 |
| `summary` | 创建会话摘要 |

### Agent 配置选项
| 选项 | 描述 |
|------|------|
| `description` | Agent 描述（必填） |
| `temperature` | 控制随机性 (0.0-1.0) |
| `steps` | 最大迭代次数 |
| `disable` | 设为 `true` 禁用 |
| `prompt` | 自定义系统提示词文件 |
| `model` | 覆盖默认模型 |
| `permission` | 权限配置 |
| `mode` | `primary`, `subagent`, 或 `all` |
| `hidden` | 从 `@` 自动补全中隐藏（仅 subagent） |
| `color` | UI 中的颜色（hex 或主题色名） |
| `top_p` | 控制响应多样性 |

### Agent 创建
```
opencode agent create
```
交互式引导创建 Agent，生成 Markdown 配置文件。

### Agent 配置位置
- JSON: `opencode.json` 的 `agent` 字段
- Markdown: `~/.config/opencode/agents/` 或 `.opencode/agents/`

---

## 14. 内置工具

| 工具 | 描述 |
|------|------|
| `bash` | 执行 shell 命令 |
| `edit` | 使用精确字符串替换修改文件 |
| `write` | 创建新文件或覆盖现有文件 |
| `read` | 读取文件内容 |
| `grep` | 使用正则表达式搜索文件内容 |
| `glob` | 按模式匹配查找文件 |
| `lsp` | 与 LSP 服务器交互（实验性） |
| `apply_patch` | 应用补丁到文件 |
| `skill` | 加载 SKILL.md 技能 |
| `todowrite` | 管理待办事项列表 |
| `webfetch` | 获取网页内容 |
| `websearch` | 网页搜索（需要 OpenCode 提供商或 `OPENCODE_ENABLE_EXA`） |
| `question` | 在执行过程中向用户提问 |

---

## 15. 自定义命令

### 配置方式
1. **JSON**: `opencode.json` 的 `command` 字段
2. **Markdown**: `~/.config/opencode/commands/` 或 `.opencode/commands/`

### 命令配置选项
| 选项 | 描述 |
|------|------|
| `template` | 发送给 LLM 的提示词（必填） |
| `description` | 命令描述 |
| `agent` | 指定执行命令的 Agent |
| `subtask` | 是否强制作为子任务触发 |
| `model` | 覆盖默认模型 |

### 特殊占位符
- `$ARGUMENTS` — 传递的所有参数
- `$1`, `$2`, `$3`... — 位置参数
- `` !`command` `` — 注入 shell 命令输出
- `@filename` — 引用文件内容

### 自定义命令可覆盖内置命令

---

## 16. Agent Skills（技能系统）

### 技能文件位置
- `.opencode/skills/<name>/SKILL.md`
- `~/.config/opencode/skills/<name>/SKILL.md`
- `.claude/skills/<name>/SKILL.md`（兼容 Claude Code）
- `~/.claude/skills/<name>/SKILL.md`（兼容 Claude Code）
- `.agents/skills/<name>/SKILL.md`（兼容 agents）

### SKILL.md 格式
```yaml
---
name: git-release  # 必填，1-64 字符，小写字母数字加连字符
description: Create consistent releases and changelogs  # 必填，1-1024 字符
license: MIT  # 可选
compatibility: opencode  # 可选
metadata:  # 可选
  audience: maintainers
  workflow: github
---
## 技能内容
```

### 权限控制
```json
{
  "permission": {
    "skill": {
      "*": "allow",
      "pr-review": "allow",
      "internal-*": "deny",
      "experimental-*": "ask"
    }
  }
}
```

---

## 17. References（引用系统）

### 本地目录引用
```json
{
  "references": {
    "docs": {
      "path": "../product-docs",
      "description": "用于产品行为和文档规范"
    }
  }
}
```

### Git 仓库引用
```json
{
  "references": {
    "sdk": {
      "repository": "anomalyco/opencode-sdk-js",
      "branch": "main",
      "description": "用于 JavaScript SDK 实现细节"
    }
  }
}
```

### 配置字段
| 字段 | 本地 | Git | 描述 |
|------|------|-----|------|
| `path` | Yes | No | 本地引用目录 |
| `repository` | No | Yes | Git URL 或 GitHub `owner/repo` |
| `branch` | No | Yes | Git 分支或 ref |
| `description` | Yes | Yes | 使用说明 |
| `hidden` | Yes | Yes | 从 TUI `@` 自动补全中隐藏 |

---

## 18. MCP 服务器

### 本地 MCP
```json
{
  "mcp": {
    "my-local-mcp": {
      "type": "local",
      "command": ["npx", "-y", "my-mcp-command"],
      "enabled": true,
      "environment": { "MY_ENV_VAR": "value" },
      "timeout": 5000
    }
  }
}
```

### 远程 MCP
```json
{
  "mcp": {
    "my-remote-mcp": {
      "type": "remote",
      "url": "https://my-mcp-server.com",
      "enabled": true,
      "headers": { "Authorization": "Bearer MY_API_KEY" }
    }
  }
}
```

### OAuth 认证
- 自动处理 OAuth 认证（Dynamic Client Registration RFC 7591）
- 手动触发: `opencode mcp auth <name>`
- 列出状态: `opencode mcp list`
- 移除凭证: `opencode mcp logout <name>`
- 调试: `opencode mcp debug <name>`

### MCP 管理
- 可全局启用/禁用
- 支持 glob 模式控制多个 MCP
- 可按 Agent 配置不同的 MCP 访问权限

---

## 19. 自定义工具

### 位置
- 项目级: `.opencode/tools/`
- 全局: `~/.config/opencode/tools/`

### 结构（TypeScript/JavaScript）
```typescript
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Query the project database",
  args: {
    query: tool.schema.string().describe("SQL query to execute"),
  },
  async execute(args) {
    return `Executed query: ${args.query}`
  },
})
```

### 特性
- 文件名即工具名
- 单文件可导出多个工具（`<filename>_<exportname>`）
- 自定义工具可覆盖内置工具
- 支持任意语言编写的脚本（通过 TS/JS 定义调用）

---

## 20. 插件系统

### 插件位置
- 项目级: `.opencode/plugins/`
- 全局: `~/.config/opencode/plugins/`
- npm: `opencode.json` 的 `plugin` 数组

### 插件结构
```typescript
export const MyPlugin = async ({ project, client, $, directory, worktree }) => {
  return {
    // 事件钩子
  }
}
```

### 可用事件
| 类别 | 事件 |
|------|------|
| 命令 | `command.executed` |
| 文件 | `file.edited`, `file.watcher.updated` |
| 消息 | `message.updated`, `message.removed`, `message.part.updated`, `message.part.removed` |
| 会话 | `session.created`, `session.compacted`, `session.deleted`, `session.diff`, `session.error`, `session.idle`, `session.status`, `session.updated` |
| 权限 | `permission.asked`, `permission.replied` |
| 工具 | `tool.execute.before`, `tool.execute.after` |
| TUI | `tui.prompt.append`, `tui.command.execute`, `tui.toast.show` |
| LSP | `lsp.client.diagnostics`, `lsp.updated` |
| Shell | `shell.env` |
| Todo | `todo.updated` |
| 安装 | `installation.updated` |
| 服务器 | `server.connected` |

### 加载顺序
1. 全局配置
2. 项目配置
3. 全局插件目录
4. 项目插件目录

---

## 21. 配置系统

### 配置文件格式
- JSON 和 JSONC（带注释的 JSON）

### 配置位置与优先级（从低到高）
1. **Remote config** — 组织默认配置（`.well-known/opencode`）
2. **Global config** — `~/.config/opencode/opencode.json`
3. **Custom config** — `OPENCODE_CONFIG` 环境变量
4. **Project config** — 项目根目录的 `opencode.json`
5. **`.opencode` directories** — agents, commands, plugins
6. **Inline config** — `OPENCODE_CONFIG_CONTENT` 环境变量
7. **Managed config** — 系统管理配置
8. **macOS managed preferences** — MDM `.mobileconfig`

### 配置合并
- 配置文件是**合并**的，不是替换的
- 非冲突设置会保留

### TUI 配置（`tui.json`）
| 选项 | 描述 |
|------|------|
| `theme` | UI 主题 |
| `keybinds` | 键盘快捷键 |
| `leader_timeout` | Leader key 超时（默认 2000ms） |
| `scroll_speed` | 滚动速度（默认 3） |
| `scroll_acceleration.enabled` | macOS 风格滚动加速 |
| `diff_style` | diff 渲染样式（`"auto"` 或 `"stacked"`） |
| `mouse` | 启用鼠标捕获（默认 `true`） |
| `attention` | 桌面通知和声音配置 |

### 主要配置选项
| 选项 | 描述 |
|------|------|
| `model` | 默认模型 |
| `small_model` | 轻量任务模型（标题生成等） |
| `provider` | 提供商配置 |
| `permission` | 权限配置 |
| `agent` | Agent 配置 |
| `command` | 自定义命令 |
| `mcp` | MCP 服务器 |
| `formatter` | 代码格式化 |
| `lsp` | LSP 服务器 |
| `plugin` | 插件 |
| `instructions` | 指令文件路径/URL |
| `share` | 分享模式 |
| `snapshot` | 快照（用于 undo/redo，默认启用） |
| `autoupdate` | 自动更新 |
| `compaction` | 上下文压缩配置 |
| `watcher` | 文件监视器忽略模式 |
| `attachment.image` | 图片附件限制 |
| `shell` | shell 配置 |
| `disabled_providers` | 禁用的提供商 |
| `enabled_providers` | 启用的提供商（白名单） |
| `default_agent` | 默认 Agent |

### 变量替换
- `{env:VARIABLE_NAME}` — 环境变量
- `{file:path/to/file}` — 文件内容

---

## 22. 环境变量

| 变量 | 类型 | 描述 |
|------|------|------|
| `OPENCODE_AUTO_SHARE` | boolean | 自动分享会话 |
| `OPENCODE_CONFIG` | string | 配置文件路径 |
| `OPENCODE_TUI_CONFIG` | string | TUI 配置文件路径 |
| `OPENCODE_CONFIG_DIR` | string | 配置目录路径 |
| `OPENCODE_CONFIG_CONTENT` | string | 内联 JSON 配置内容 |
| `OPENCODE_DISABLE_AUTOUPDATE` | boolean | 禁用自动更新 |
| `OPENCODE_PERMISSION` | string | 内联权限配置 |
| `OPENCODE_DISABLE_MOUSE` | boolean | 禁用鼠标捕获 |
| `OPENCODE_ENABLE_EXA` | boolean | 启用 Exa 网页搜索 |
| `OPENCODE_SERVER_PASSWORD` | string | HTTP Basic Auth 密码 |
| `OPENCODE_SERVER_USERNAME` | string | Basic Auth 用户名 |

### 实验性环境变量
| 变量 | 描述 |
|------|------|
| `OPENCODE_EXPERIMENTAL` | 启用实验性功能总开关 |
| `OPENCODE_EXPERIMENTAL_LSP_TOOL` | 启用实验性 LSP 工具 |
| `OPENCODE_EXPERIMENTAL_PLAN_MODE` | 启用计划模式 |
| `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS` | 启用后台子 Agent |
| `OPENCODE_EXPERIMENTAL_SCOUT` | 启用 Scout 子 Agent |
| `OPENCODE_EXPERIMENTAL_WORKSPACES` | 启用工作区支持 |

---

## 23. Rules（规则/指令）

### AGENTS.md 文件
- 项目根目录的 `AGENTS.md` — 项目特定规则
- `~/.config/opencode/AGENTS.md` — 全局规则
- 通过 `/init` 命令自动创建

### Claude Code 兼容性
- 支持读取 `CLAUDE.md` 作为回退
- 支持 `~/.claude/CLAUDE.md` 全局规则
- 支持 `.claude/skills/` 技能目录
- 可通过环境变量禁用

### 自定义指令文件
```json
{
  "instructions": [
    "CONTRIBUTING.md",
    "docs/guidelines.md",
    ".cursor/rules/*.md",
    "https://raw.githubusercontent.com/org/rules/main/style.md"
  ]
}
```

---

## 24. 代码格式化

### 内置格式化器（30+）
air, biome, cargofmt, clang-format, cljfmt, dart, dfmt, gleam, gofmt, htmlbeautifier, ktlint, mix, nixfmt, ocamlformat, ormolu, oxfmt, pint, prettier, rubocop, ruff, rustfmt, shfmt, standardrb, terraform, uv, zig

### 启用方式
```json
{ "formatter": true }
```

### 自定义格式化器
```json
{
  "formatter": {
    "custom-formatter": {
      "command": ["deno", "fmt", "$FILE"],
      "extensions": [".md"]
    }
  }
}
```

---

## 25. Policies（策略系统）

实验性功能，控制 OpenCode 可使用哪些资源。

```json
{
  "experimental": {
    "policies": [
      { "effect": "deny", "action": "provider.use", "resource": "openai" },
      { "effect": "allow", "action": "provider.use", "resource": "anthropic" }
    ]
  }
}
```

- 支持通配符匹配
- 最后匹配的规则生效
- 全局策略优先于项目策略

---

## 26. TUI 注意力通知

```json
{
  "attention": {
    "enabled": true,
    "notifications": true,
    "sound": true,
    "volume": 0.4,
    "sound_pack": "opencode.default",
    "sounds": {
      "error": "./sounds/error.mp3"
    }
  }
}
```

支持通知的事件:
- 问题（questions）
- 权限请求（permissions）
- 会话错误（session errors）
- 会话完成（completed sessions）

---

## 27. 终端要求

- 需要支持 **truecolor**（24 位颜色）的现代终端
- 推荐终端: WezTerm, Alacritty, Ghostty, Kitty
- 检查: `echo $COLORTERM` 应输出 `truecolor` 或 `24bit`

---

## 28. 安装方式

- **安装脚本** — 最简单的方式
- **Node.js**: npm, Bun, pnpm, Yarn
- **macOS/Linux**: Homebrew (OpenCode tap)
- **Arch Linux**: 包管理器
- **Windows**: Chocolatey, Scoop, NPM, Mise, Docker
- **二进制下载**: GitHub Releases 页面

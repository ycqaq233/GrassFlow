# 官方文档分析报告

## 一、OpenCode 文档分析

### 1.1 斜杠命令列表

#### 内置命令

| 命令 | 功能 |
|------|------|
| `/init` | 初始化项目配置 |
| `/undo` | 撤销操作 |
| `/redo` | 重做操作 |
| `/share` | 分享功能 |
| `/help` | 显示帮助信息 |
| `/connect` | 连接 Provider（输入 API Key） |
| `/models` | 选择可用模型 |

#### 自定义命令特性

自定义命令可通过两种方式定义：
- JSON 配置文件（`opencode.json` 的 `command` 字段）
- `.opencode/commands/` 目录下的 Markdown 文件

**提示词语法**：

| 语法 | 功能 |
|------|------|
| `$ARGUMENTS` | 替换为所有传入参数 |
| `$1`, `$2`, `$3`... | 替换为第 N 个位置参数 |
| `` !`command` `` | 注入 bash 命令的输出到提示词中 |
| `@filename` | 将文件内容自动包含在提示词中 |

**命令配置选项**：

```jsonc
{
  "command": {
    "test": {
      "template": "Run the full test suite...",  // 必需：提示词模板
      "description": "Run tests with coverage",   // 可选：描述
      "agent": "build",                           // 可选：指定执行代理
      "model": "anthropic/claude-haiku-4-5",      // 可选：覆盖默认模型
      "subtask": true                             // 可选：强制子代理调用
    }
  }
}
```

### 1.2 MCP 服务器配置

**配置文件位置**：项目根目录的 `opencode.json` 或 `opencode.jsonc`

**支持的传输类型**：

#### 本地模式 (`"local"` — 对应 stdio)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "my-local-mcp-server": {
      "type": "local",
      "command": ["npx", "-y", "my-mcp-command"],
      "enabled": true,
      "environment": {
        "MY_ENV_VAR": "my_env_var_value"
      },
      "timeout": 5000
    }
  }
}
```

#### 远程模式 (`"remote"` — 对应 Streamable HTTP / SSE)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "my-remote-mcp": {
      "type": "remote",
      "url": "https://my-mcp-server.com",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer MY_API_KEY"
      },
      "timeout": 5000
    }
  }
}
```

**环境变量引用语法**：`{env:VAR_NAME}`

```json
{
  "headers": {
    "CONTEXT7_API_KEY": "{env:CONTEXT7_API_KEY}"
  }
}
```

**工具管理**：

```json
{
  "tools": {
    "my-mcp*": false
  }
}
```

### 1.3 Skills 系统

**技能文件位置**：

| 级别 | 路径 |
|------|------|
| 项目级 | `.opencode/skills/<name>/SKILL.md` |
| 全局级 | `~/.config/opencode/skills/<name>/SKILL.md` |
| Claude 兼容 | `.claude/skills/<name>/SKILL.md` |

**Frontmatter 格式**：

```yaml
---
name: git-release           # 必填：1-64字符，小写字母和数字，单连字符分隔
description: Create consistent releases and changelogs  # 必填：1-1024字符
license: MIT                # 可选
compatibility: opencode     # 可选
metadata:                   # 可选：键值映射
  audience: maintainers
  workflow: github
---

## What I do
- Draft release notes from merged PRs
- Propose a version bump

## When to use me
Use this when you are preparing a tagged release.
```

**名称验证规则**：`^[a-z0-9]+(-[a-z0-9]+)*$`

**触发方式**：通过原生 `skill` 工具按需加载

**权限控制**：

```json
{
  "permission": {
    "skill": "allow"  // allow | deny | ask
  }
}
```

### 1.4 配置格式

**配置文件位置与优先级**（后者覆盖前者）：

| 优先级 | 位置 | 说明 |
|--------|------|------|
| 1 | 远程配置 `.well-known/opencode` | 组织默认值 |
| 2 | 全局配置 `~/.config/opencode/opencode.json` | 用户偏好 |
| 3 | 自定义配置 `OPENCODE_CONFIG` 环境变量 | 自定义覆盖 |
| 4 | 项目配置 `opencode.json` | 项目特定设置 |
| 5 | `.opencode` 目录 | 代理、命令、插件等 |
| 6 | 内联配置 `OPENCODE_CONFIG_CONTENT` | 运行时覆盖 |

**完整配置示例**：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5",
  "autoupdate": true,
  "default_agent": "plan",
  "share": "manual",
  "instructions": ["CONTRIBUTING.md", "docs/guidelines.md"],
  "disabled_providers": ["openai"],
  "enabled_providers": ["anthropic", "openai"],

  "tui": {
    "scroll_speed": 3,
    "scroll_acceleration": { "enabled": true },
    "diff_style": "auto"
  },

  "server": {
    "port": 4096,
    "hostname": "0.0.0.0",
    "mdns": true,
    "cors": ["http://localhost:5173"]
  },

  "tools": {
    "write": false,
    "bash": false
  },

  "provider": {
    "anthropic": {
      "options": {
        "timeout": 600000,
        "setCacheKey": true
      }
    }
  },

  "agent": {
    "code-reviewer": {
      "description": "Reviews code for best practices",
      "model": "anthropic/claude-sonnet-4-5",
      "prompt": "You are a code reviewer.",
      "tools": { "write": false, "edit": false }
    }
  },

  "permission": {
    "edit": "ask",
    "bash": "ask"
  },

  "compaction": {
    "auto": true,
    "prune": false,
    "reserved": 10000
  },

  "watcher": {
    "ignore": ["node_modules/**", "dist/**", ".git/**"]
  }
}
```

**变量替换语法**：
- 环境变量：`{env:VARIABLE_NAME}`
- 文件内容：`{file:path/to/file}`

### 1.5 Provider 系统

**支持的 Provider 列表（40+）**：

| 类型 | Provider |
|------|----------|
| 云端 | Anthropic, OpenAI, DeepSeek, Google Vertex AI, Azure OpenAI, Amazon Bedrock, Groq, xAI, Moonshot AI, MiniMax, Together AI, Fireworks AI, Cerebras, Deep Infra, Hugging Face, Venice AI, Scaleway, Nebius, STACKIT, OVHcloud, SAP AI Core, Baseten, Cortecs, 302.AI, IO.NET, Z.AI |
| 本地 | Ollama, llama.cpp, LM Studio, Atomic Chat |
| 网关 | OpenRouter, Cloudflare AI Gateway, Vercel AI Gateway, Helicone, ZenMux |
| 其他 | GitHub Copilot, GitLab Duo, OpenCode Zen |

**自定义 Provider 配置**：

```json
{
  "provider": {
    "myprovider": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "My AI Provider",
      "options": {
        "baseURL": "https://api.myprovider.com/v1",
        "apiKey": "{env:MY_API_KEY}",
        "headers": {
          "Authorization": "Bearer custom-token"
        }
      },
      "models": {
        "my-model-name": {
          "name": "My Model Display Name",
          "limit": {
            "context": 200000,
            "output": 65536
          }
        }
      }
    }
  }
}
```

**API 密钥设置方式**：
1. `/connect` 命令（推荐）—— 存储在 `~/.local/share/opencode/auth.json`
2. 环境变量
3. 配置文件内联（`{env:VAR_NAME}` 语法）

---

## 二、Hermes Agent 文档分析

### 2.1 项目概述

**Hermes Agent** 是 Nous Research 开源的自进化 AI 代理，口号是"与你一起成长的代理"。

**核心特性**：
- 内置学习循环：从经验中创建技能，持续改进
- 持久化知识：跨会话搜索、用户建模
- 多平台消息网关：Telegram、Discord、Slack、WhatsApp、Signal、CLI
- 六种终端后端：Local、Docker、SSH、Singularity、Modal、Daytona
- 内置定时调度器（cron）

**技术栈**：Python 81.9%, TypeScript 14.1%

**流行度**：203k stars, 36.4k forks

### 2.2 CLI 命令

| 命令 | 功能 |
|------|------|
| `hermes` | 交互式 CLI 对话 |
| `hermes model` | 选择 LLM provider 和模型 |
| `hermes tools` | 配置启用的工具 |
| `hermes config set` | 设置配置值 |
| `hermes gateway` | 启动消息网关 |
| `hermes setup` | 完整设置向导 |
| `hermes claw migrate` | 从 OpenClaw 迁移 |
| `hermes update` | 更新到最新版本 |
| `hermes doctor` | 诊断问题 |

### 2.3 斜杠命令（CLI 和消息平台通用）

| 操作 | 命令 |
|------|------|
| 新对话 | `/new` 或 `/reset` |
| 切换模型 | `/model [provider:model]` |
| 设置人格 | `/personality [name]` |
| 重试/撤销 | `/retry`, `/undo` |
| 上下文管理 | `/compress`, `/usage`, `/insights [--days N]` |
| 浏览技能 | `/skills` 或 `/<skill-name>` |
| 中断工作 | `Ctrl+C` (CLI) 或 `/stop` (消息平台) |
| 平台状态 | `/platforms`, `/status`, `/sethome` |

### 2.4 配置格式

使用 YAML 配置文件（`cli-config.yaml.example`）和环境变量（`.env.example`）。

配置管理命令：`hermes config set`

### 2.5 仓库结构

| 目录 | 用途 |
|------|------|
| `agent/` | 核心代理逻辑 |
| `gateway/` | 消息平台网关 |
| `skills/` | 内置技能 |
| `optional-skills/` | 可选技能模块 |
| `optional-mcps/` | 可选 MCP 服务器 |
| `tools/` | 工具实现 |
| `providers/` | LLM provider 集成 |
| `plugins/` | 插件系统 |
| `ui-tui/` | 终端 UI |
| `hermes_cli/` | CLI 实现 |
| `cron/` | 定时调度器 |

---

## 三、对 GrassFlow 的设计参考

### 3.1 配置系统参考

**OpenCode 的配置优先级**（6层）值得借鉴：
1. 远程配置（组织默认）
2. 全局配置（用户偏好）
3. 环境变量自定义配置
4. 项目配置
5. `.opencode` 目录
6. 内联环境变量配置

**GrassFlow 建议**：
- 采用类似的多层配置优先级
- 支持 `{env:VAR_NAME}` 和 `{file:path}` 变量替换语法
- 使用 JSONC 格式支持注释

### 3.2 MCP 配置参考

**OpenCode 的两种传输类型**：
- `local`（stdio）—— 本地进程
- `remote`（HTTP）—— 远程服务器

**GrassFlow 建议**：
- 统一使用 `local`/`remote` 类型标识
- 支持 `environment` 字段传递环境变量
- 支持 `headers` 字段传递认证信息

### 3.3 Skills 系统参考

**OpenCode 的技能定义**：
- YAML frontmatter + Markdown 内容
- 严格的命名规则（正则验证）
- 多级目录（项目级、全局级、兼容层）

**Hermes 的技能特性**：
- 自动从经验中创建技能
- 技能自我改进
- FTS5 会话搜索

**GrassFlow 建议**：
- 采用 YAML frontmatter 格式
- 支持 `name`、`description`、`metadata` 字段
- 考虑技能版本管理和继承机制

### 3.4 Provider 系统参考

**OpenCode 的 Provider 配置**：
- 40+ 内置 provider
- 自定义 provider 通过 `npm` 字段指定 SDK 包
- 模型限制配置（context/output token limits）

**GrassFlow 建议**：
- 支持主流 provider（OpenAI、Anthropic、DeepSeek、Ollama 等）
- 自定义 provider 通过 `baseURL` + `apiKey` 配置
- 模型配置包含 token 限制

### 3.5 会话管理参考

**Hermes 的会话命令**：
- `/new` 或 `/reset` —— 新对话
- `/retry` 或 `/undo` —— 重试/撤销
- `/compress` —— 压缩上下文
- `/usage` —— 查看用量
- `/insights [--days N]` —— 查看历史洞察

**GrassFlow 建议**：
- 支持 `/undo`、`/redo` 操作
- 支持 `/compress` 上下文压缩
- 支持会话持久化和恢复

### 3.6 命令系统参考

**OpenCode 的自定义命令**：
- 支持 `$ARGUMENTS`、`$1`、`$2` 参数替换
- 支持 `` !`command` `` 注入 shell 输出
- 支持 `@filename` 引用文件内容
- 可指定 `agent` 和 `model`

**GrassFlow 建议**：
- 采用类似的参数替换语法
- 支持 shell 命令注入
- 支持文件内容引用

# GrassFlow 项目状态

> 最后更新：2026-06-25

## 项目概述

GrassFlow 是一个声明式多Agent编排平台，支持 TUI 和 GUI 两种模式。当前已完成 P0（TUI 全流程闭环）的所有功能。

## 完成状态

### P0 功能（TUI 全流程闭环）— ✅ 全部完成

| 功能 | 状态 | 文件 | 测试 |
|------|------|------|------|
| Agent 基类 + Schema 系统 | ✅ | `core/agent.py` | 13 个测试 |
| DAG 拓扑排序 + 并行调度 | ✅ | `core/dag.py` | 15 个测试 |
| DSL 解析器（顺序/并行/条件/立即执行） | ✅ | `tui/dsl_parser.py` | 17 个测试 |
| ConditionAgent（条件分支） | ✅ | `core/condition.py` | 10 个测试 |
| LLM Agent + API 调用 | ✅ | `core/llm.py`, `core/llm_agent.py` | 17 个测试 |
| 只读数据传递（Context） | ✅ | `core/context.py` | 4 个测试 |
| 可配置失败策略（stop/skip/retry） | ✅ | `core/scheduler.py` | 11 个测试 |
| 工作流保存/加载（JSON） | ✅ | `core/storage.py` | 10 个测试 |
| 终端进度展示（Rich） | ✅ | `tui/display.py` | - |
| CLI 入口（`grassflow run/list/save`） | ✅ | `tui/cli.py` | - |
| 监控报告（事后检查） | ✅ | `core/monitor.py` | 14 个测试 |
| 执行记录（SQLite） | ✅ | `core/db.py` | 8 个测试 |
| 示例工作流 | ✅ | `examples/*.af` | - |

### 测试覆盖

- **总测试数**：149 个
- **测试通过率**：100%
- **覆盖模块**：core/、tui/、tests/

## 文件结构

```
grassflow/
├── core/                         # 共享核心模块
│   ├── __init__.py               # 模块导出
│   ├── agent.py                  # Agent 基类 + Schema 系统
│   ├── condition.py              # 条件分支 Agent
│   ├── config.py                 # 配置管理
│   ├── context.py                # 只读数据传递 Context
│   ├── dag.py                    # DAG 引擎 + 拓扑排序
│   ├── db.py                     # SQLite 执行记录
│   ├── llm.py                    # LLM API 封装
│   ├── llm_agent.py              # LLM Agent
│   ├── monitor.py                # 监控 Agent
│   ├── models.py                 # 数据模型
│   ├── scheduler.py              # asyncio 并行调度器
│   └── storage.py                # 工作流存储
│
├── tui/                          # TUI 入口
│   ├── __init__.py               # 模块导出
│   ├── cli.py                    # CLI 命令入口
│   ├── display.py                # 终端进度展示
│   └── dsl_parser.py             # DSL 语法解析器
│
├── examples/                     # 示例工作流
│   ├── ticket_processing.af      # 工单处理示例
│   └── competitor_analysis.af    # 竞品分析示例
│
├── tests/                        # 测试
│   ├── test_condition.py         # 条件分支测试
│   ├── test_config.py            # 配置管理测试
│   ├── test_core.py              # 核心模块测试
│   ├── test_dag.py               # DAG 引擎测试
│   ├── test_db.py                # 数据库测试
│   ├── test_dsl_parser.py        # DSL 解析器测试
│   ├── test_llm.py               # LLM 模块测试
│   ├── test_llm_agent.py         # LLM Agent 测试
│   ├── test_monitor.py           # 监控模块测试
│   ├── test_scheduler.py         # 调度器测试
│   └── test_storage.py           # 存储测试
│
├── setup.py                      # Python 包配置
├── requirements.txt              # 依赖列表
├── README.md                     # 项目说明
├── CLAUDE.md                     # 项目规范
└── PROJECT_STATUS.md             # 项目状态（本文件）
```

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **TUI 前端** | Python Rich |
| **后端** | Python + asyncio |
| **数据持久化** | SQLite + JSON |
| **AI 层** | LiteLLM（支持 OpenAI/Anthropic） |
| **测试** | pytest + pytest-asyncio |

## CLI 命令

```bash
# 验证工作流文件
python -m tui.cli validate examples/ticket_processing.af

# 执行工作流
python -m tui.cli run examples/ticket_processing.af

# 列出已保存的工作流
python -m tui.cli list

# 保存工作流
python -m tui.cli save examples/ticket_processing.af

# 配置管理
python -m tui.cli config list                    # 列出所有配置
python -m tui.cli config get llm.default_model   # 获取配置值
python -m tui.cli config set llm.default_model gpt-4  # 设置配置值
python -m tui.cli config api-key openai sk-xxx   # 设置 API Key
python -m tui.cli config show-key openai         # 显示 API Key（脱敏）
python -m tui.cli config path                    # 显示配置文件路径
python -m tui.cli config reset --scope global    # 重置配置
```

## 配置系统

### 多级配置（参考 Claude Code）

- **全局配置**：`~/.Grass/config.json`
- **项目配置**：`.grass/config.json`
- **环境变量**：`GRASSFLOW_*`

**配置优先级**：环境变量 > 项目配置 > 全局配置 > 默认值

### 配置结构

```json
{
  "version": "1.0.0",
  "api_keys": {
    "openai": null,
    "anthropic": null,
    "deepseek": null,
    "ollama": null
  },
  "llm": {
    "default_model": "gpt-4",
    "default_provider": "openai",
    "temperature": 0.7,
    "max_tokens": 4096,
    "timeout": 60,
    "retry_count": 3,
    "retry_delay": 1.0
  },
  "workflow": {
    "auto_save": true,
    "auto_validate": true,
    "max_parallel": 10,
    "default_on_fail": "stop",
    "execution_timeout": 300
  },
  "display": {
    "theme": "dark",
    "show_timestamps": true,
    "show_agent_names": true,
    "log_level": "INFO",
    "compact_mode": false
  },
  "server": {
    "host": "localhost",
    "port": 8000,
    "cors_origins": ["*"],
    "debug": false
  },
  "workflows_dir": "~/.Grass/workflows",
  "db_path": "~/.Grass/grassflow.db",
  "plugins_dir": "~/.Grass/plugins"
}
```

## 下一步（P1 — GUI）

1. Electron 桌面应用
2. React Flow 画布 + 左侧积木面板
3. 多种连线类型（实线/虚线/粗线）
4. 广播分发、聚合等待、超时降级
5. AI 自动生成 TUI 编排
6. 工作流模板市场
7. 本地模型支持（Ollama）

## 开发记录

- **2026-06-25**：添加配置文件功能（多级配置、CLI 配置命令、环境变量覆盖）
- **2026-06-25**：完成 P0 所有功能，115 个测试全部通过
- **2026-06-24**：完成第一阶段（项目骨架）

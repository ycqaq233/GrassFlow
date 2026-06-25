# GrassFlow

> 可视化多Agent积木编排平台

GrassFlow 是一个声明式多Agent编排平台，用户可以通过"拼积木"的方式创建、连接和调度多个AI Agent，实现复杂任务的自动化分解与并行执行。

## 特性

- **GUI + TUI 双模式**：支持可视化拖拽和声明式DSL语法
- **丰富的交互方式**：顺序、并行、条件分支、立即执行、广播、聚合
- **监控Agent机制**：用Agent监控Agent，确保输出质量
- **声明式依赖**：用户只需声明"谁依赖谁"，系统自动处理执行顺序

## 快速开始

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd grassflow

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### CLI 使用

```bash
# 验证工作流文件
python -m tui.cli validate examples/ticket_processing.af

# 执行工作流
python -m tui.cli run examples/ticket_processing.af

# 列出已保存的工作流
python -m tui.cli list

# 保存工作流
python -m tui.cli save examples/ticket_processing.af
```

### 基本使用

```python
from core.agent import Agent, AgentConfig
from core.context import WorkflowContext
from core.scheduler import Scheduler
from core.dag import DAG
from tui.dsl_parser import parse_file

# 加载工作流
workflow = parse_file("examples/ticket_processing.af")

# 创建 Agent 实例
agents = {}
for agent_config in workflow.agents:
    # 根据配置创建 Agent
    agents[agent_config.name] = MyAgent(agent_config)

# 创建调度器并执行
scheduler = Scheduler(workflow, agents)
context = WorkflowContext()
result = asyncio.run(scheduler.run(context))
```

## DSL 语法

```grassflow
# 工作流定义
workflow ticket_processing {
  # Agent 声明
  agent classify {
    model: "gpt-4"
    prompt: "分类工单: {input}"
    input_schema: { "ticket": "string" }
    output_schema: { "category": "string" }
  }

  agent route {
    type: "condition"
    rules: ["urgent", "normal", "info"]
  }

  # 执行流
  # 并行执行
  (classify, priority)

  # 顺序执行
  -> route

  # 条件分支
  -> [urgent] human, [normal] bot
}
```

### 支持的语法

| 语法 | 说明 | 示例 |
|------|------|------|
| `A -> B` | 顺序执行 | `classify -> route` |
| `(A, B) -> C` | 并行执行 | `(classify, priority) -> route` |
| `A \| B` | 立即执行 | `classify \| priority` |
| `-> [x] A` | 条件分支 | `-> [urgent] human` |

## 项目结构

```
grassflow/
├── core/                     # 共享核心模块
│   ├── agent.py              # Agent 基类 + Schema 系统
│   ├── dag.py                # DAG 引擎 + 拓扑排序
│   ├── scheduler.py          # asyncio 并行调度器
│   ├── context.py            # 只读数据传递 Context
│   ├── condition.py          # 条件分支 Agent
│   ├── llm.py                # LLM API 封装
│   ├── llm_agent.py          # LLM Agent
│   ├── monitor.py            # 监控 Agent
│   ├── storage.py            # 工作流存储
│   ├── db.py                 # SQLite 执行记录
│   └── models.py             # 数据模型
│
├── tui/                      # TUI 入口
│   ├── cli.py                # CLI 命令入口
│   ├── dsl_parser.py         # DSL 语法解析器
│   └── display.py            # 终端进度展示
│
├── examples/                 # 示例工作流
│   ├── ticket_processing.af  # 工单处理示例
│   └── competitor_analysis.af # 竞品分析示例
│
├── tests/                    # 测试
├── setup.py                  # Python 包配置
└── requirements.txt          # 依赖列表
```

## 开发

```bash
# 运行测试
pytest tests/

# 运行特定测试
pytest tests/test_dag.py -v

# 代码格式化
black core/ tui/ tests/

# 代码检查
ruff check core/ tui/ tests/
```

## 测试覆盖

项目包含 115 个测试，覆盖以下模块：

- **核心模块**：Agent、Context、Workflow、Models
- **DAG 引擎**：拓扑排序、依赖解析、环检测
- **调度器**：顺序/并行执行、失败策略、条件分支
- **DSL 解析器**：语法解析、错误处理
- **条件分支**：ConditionAgent、SimpleConditionAgent
- **LLM 集成**：LLMClient、LLMManager、LLMAgent
- **存储**：工作流保存/加载、SQLite 执行记录
- **监控**：Schema 检查、质量检查、性能检查

## 许可证

MIT License

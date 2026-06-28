# GrassFlow DSL v2 语言规范

> 版本：2.1.0
> 最后更新：2026-06-28

---

## 1. 概述

GrassFlow DSL（领域特定语言）是一种**声明式编排语言**，用于定义多 Agent 工作流。用户通过描述"组件是什么"和"组件怎么连接"来构建复杂的 AI 编排，系统自动处理执行顺序、并行调度和数据传递。

### 1.1 设计原则

| 原则 | 说明 |
|------|------|
| **端口是一等公民** | 所有连接关系基于端口，端口名即数据契约 |
| **组合优于继承** | 用 `use` 引入组件，不支持 `extends` |
| **组件级别声明** | 同步/异步、复用/独立是组件的核心行为 |
| **就近优先发现** | 文件系统约定 + CLI 管理 |
| **DSL 驱动** | 所有组件系统必须可由 DSL 表达 |

### 1.2 文件格式

- 文件扩展名：`.gf`
- 编码：UTF-8
- 注释：`#` 行注释
- 一个文件可包含多个 `component` 和 `workflow` 定义

---

## 2. 词法元素

### 2.1 关键字

```
component   workflow    agent       use
port        input       output      mcp
permission  allow       deny        ask
model       sync        async       shared
```

### 2.2 标识符

```
IDENTIFIER := [a-zA-Z_][a-zA-Z0-9_-]*
```

标识符用于命名组件、Agent、端口。允许字母、数字、下划线、连字符，不能以数字开头。

### 2.3 字面量

```
STRING      := '"' ... '"' | '"""' ... '"""'    # 字符串 / 多行字符串
NUMBER      := [0-9]+('.'[0-9]+)?               # 整数 / 浮点
BOOLEAN     := 'true' | 'false'
ARRAY       := '[' value (',' value)* ']'        # 数组
NULL        := 'null'
```

### 2.4 模板变量

在 `system_prompt` 和 `prompt` 中，用 `{port_name}` 引用输入端口数据：

```
system_prompt: "审查代码: {code}, 上下文: {context}"
```

---

## 3. 组件（Component）

组件是可复用的 Agent 模板，定义了 Agent 的完整行为规范。

### 3.1 基本语法

```grassflow
component <name> {
    <属性定义>
}
```

### 3.2 完整属性列表

```grassflow
component code-reviewer {
    # === 元信息 ===
    description: "代码审查专家"
    version: "1.0.0"

    # === 提示词 ===
    system_prompt: "你是一个专业的代码审查专家..."

    # === 输入端口 ===
    port input code: string "待审查的代码"
    port input context: object "上下文信息"

    # === 输出端口 ===
    port output issues: array "发现的问题列表"
    port output score: number "代码质量评分"

    # === MCP 配置 ===
    mcp github {
        tools: [create_issue, add_comment]
    }

    # === 模型配置 ===
    model default: "gpt-4"
    model fallback: "gpt-3.5-turbo"
    model temperature: 0.3
    model max_tokens: 4096

    # === 权限 ===
    permission allow: [read, glob, grep]
    permission deny: [write, shell]
    permission ask: [commit_changes]

    # === 执行模式 ===
    mode: "batch"          # batch | stream
    context: "shared"      # shared | independent

    # === 失败策略 ===
    on_fail: "retry"       # stop | skip | retry
    retry_count: 3
}
```

### 3.3 属性详解

#### 3.3.1 description

组件的简要描述，用于 `grassflow component show` 和搜索。

```
description: "代码审查专家"
```

#### 3.3.2 version

语义化版本号。

```
version: "1.0.0"
```

#### 3.3.3 system_prompt

Agent 的系统提示词。支持 `{port_name}` 模板变量，从输入端口自动注入。

```
system_prompt: "你是一个代码审查专家，审查以下代码: {code}"
```

多行提示词：

```
system_prompt: """
    你是一个专业的代码审查专家。
    审查重点：
    - 代码质量
    - 安全漏洞
    - 性能问题
"""
```

#### 3.3.4 port（端口）

定义组件的输入输出接口。

**语法**：

```
port <direction> <name>: <type> "<description>"
```

- `direction`：`input`（输入）或 `output`（输出）
- `name`：端口名称，同一组件内唯一
- `type`：类型标签（见 3.3.4.1）
- `description`：端口描述（可选）

**示例**：

```
port input code: string "待审查的代码"
port input context: object "上下文信息"
port output issues: array "问题列表"
port output score: number "评分"
```

**3.3.4.1 端口类型**

端口类型是 **JSON Schema 的语法糖**，用于简化声明。实际数据校验仍由 JSON Schema 完成。

| 端口类型 | 对应 JSON Schema | 说明 |
|----------|-----------------|------|
| `string` | `{"type": "string"}` | 字符串 |
| `number` | `{"type": "number"}` | 数字 |
| `boolean` | `{"type": "boolean"}` | 布尔值 |
| `object` | `{"type": "object"}` | 对象 |
| `array` | `{"type": "array"}` | 数组 |

> **注意**：端口类型只是标签，不支持嵌套类型（如 `array<object>`）。需要复杂类型时，在 `output_schema` 中定义完整的 JSON Schema，端口名与 schema 字段名自动对应。

**3.3.4.2 端口同步属性**

端口可以声明同步或异步行为（可选，默认同步）：

```
port input trigger: string [async]    # 异步端口：每次收到输入就激活
port input data: object [sync]        # 同步端口：等待所有源就绪（默认）
```

#### 3.3.5 mcp（MCP 服务器配置）

声明组件使用的 MCP 服务器及其工具。

**语法**：

```
mcp <server_name> {
    tools: [tool1, tool2, ...]
}
```

多个 MCP 服务器：

```
mcp github {
    tools: [create_issue, add_comment]
}
mcp sonarqube {
    tools: [analyze_code, get_metrics]
}
```

**工具命名空间**：调用工具时自动带 MCP 服务器名前缀。如 `github.create_issue`、`sonarqube.analyze_code`，不同 MCP 的同名工具不会冲突。

#### 3.3.6 model（模型配置）

```
model default: "gpt-4"        # 默认模型
model fallback: "gpt-3.5-turbo"  # 备选模型
model temperature: 0.3        # 温度
model max_tokens: 4096        # 最大 token 数
```

#### 3.3.7 permission（权限）

控制 Agent 可用的内置工具集。权限声明中的工具 ID 对应 `ToolRegistry` 中注册的内置工具名称。

```
permission allow: [read, glob, grep]        # 允许读取类工具
permission deny:  [write, shell]            # 禁止写入和执行
permission ask:   [commit_changes]          # 每次调用前询问用户
```

**优先级规则**：`deny` > `ask` > `allow`

**继承规则**：权限是组件的固有属性，实例化时**不可覆盖**（安全策略不可放宽）。

**工具过滤机制**：运行时，`create_filtered_registry()` 根据组件的 `permission` 声明从全局 `ToolRegistry` 中创建一个独立的过滤注册表，该 Agent 只能访问声明允许的工具。参见第 11 章。

#### 3.3.8 mode（执行模式）

```
mode: "batch"     # 批处理：等待所有输入就绪后执行一次（默认）
mode: "stream"    # 流处理：规划中，未完整实现
```

> **注意**：`stream` 模式已定义在数据模型中，但当前调度器仅实现了 `batch` 模式的调度逻辑。`stream` 模式的完整支持（包括异步端口触发、共享上下文累积等）在后续版本中实现。

#### 3.3.9 context（上下文策略）

```
context: "shared"       # 共享上下文：多次执行共享状态（默认）
context: "independent"  # 独立上下文：每次执行隔离
```

**mode 与 context 的组合**：

| mode | context | 行为 | 典型场景 |
|------|---------|------|---------|
| `batch` | `shared` | 等待所有输入，执行一次，共享上下文 | 函数调用 |
| `batch` | `independent` | 等待所有输入，执行一次，隔离上下文 | 无状态处理 |
| `stream` | `shared` | 每次输入触发，共享上下文（累积状态） | 流式累加器 |
| `stream` | `independent` | 每次输入触发，隔离上下文 | 流式 map |

#### 3.3.10 on_fail（失败策略）

```
on_fail: "stop"    # 停止整个工作流（默认）
on_fail: "skip"    # 跳过该 Agent，用空结果继续
on_fail: "retry"   # 重试，配合 retry_count
retry_count: 3     # 重试次数（on_fail: "retry" 时有效）
```

---

## 4. 工作流（Workflow）

工作流定义了 Agent 实例的创建、连接和执行规则。

### 4.1 基本语法

```grassflow
workflow <name> {
    <端口定义>
    <Agent 实例>
    <连接>
}
```

### 4.2 完整示例

```grassflow
workflow code-review-pipeline {
    # === 工作流端口 ===
    port input code: string "待审查的代码"
    port output report: object "审查报告"

    # === Agent 实例 ===
    agent analyzer {
        model: "gpt-4"
        system_prompt: "分析代码结构: {code}"
        port input code: string
        port output analysis: object
    }

    agent reviewer use code-reviewer {
        model temperature: 0.5    # 覆盖运行时参数
    }

    agent reporter {
        model: "gpt-4"
        system_prompt: "生成报告: {analysis}, {issues}"
        port input analysis: object
        port input issues: array
        port output report: object
    }

    # === 连接 ===
    analyzer.analysis -> reporter.analysis
    reviewer.issues -> reporter.issues

    # === 工作流输出映射 ===
    reporter.report -> report
}
```

### 4.3 工作流端口

工作流的端口与组件端口语法一致：

```grassflow
workflow my-pipeline {
    port input code: string
    port output report: object
    ...
}
```

**输入传递**：工作流的输入自动注入到同名端口的 Agent。

**输出映射**：工作流输出需要显式映射：

```grassflow
agent.final_result -> workflow_output_name
```

### 4.3.1 工作流输入（workflow_input）

执行工作流时，可通过 `--task` 和 `--input` 参数向工作流注入外部输入：

```bash
/run my_workflow.gf --task "审查 examples/code_review_pipeline.gf 的代码质量" --input debug=true
```

**输入注入规则**：

1. `--task "描述"` 将 `task` 键注入到输入参数
2. `--input key=value` 注入键值对（支持 JSON 值，否则作为字符串）
3. **根 Agent**（DAG 中无依赖的 Agent）自动接收 `workflow_input` 作为输入数据
4. 非根 Agent 的输入通过 `_deps` 字段获取上游 Agent 的输出

**输入数据结构**：

```python
# 根 Agent（无依赖）收到：
{
    "task": "审查 examples/code_review_pipeline.gf 的代码质量",
    "debug": True,
    "_deps": {}  # 空，因为没有上游依赖
}

# 非根 Agent 收到：
{
    "_deps": {
        "reader": {"code_content": "...", "structure": {...}, "metrics": {...}},
        "complexity": {"complexity_report": {...}, "score": 85}
    }
}
```

**实现位置**：`core/scheduler.py` — `Scheduler._prepare_input()`

### 4.4 Agent 实例化

**4.4.1 内联定义**

直接在 workflow 内定义 Agent：

```grassflow
agent analyzer {
    model: "gpt-4"
    system_prompt: "分析代码: {code}"
    port input code: string
    port output analysis: object
}
```

**4.4.2 使用组件**

通过 `use` 引入组件定义：

```grassflow
agent reviewer use code-reviewer
```

**4.4.3 使用组件 + 覆盖运行时参数**

```grassflow
agent reviewer use code-reviewer {
    model: "gpt-4o"
    model temperature: 0.5
    model max_tokens: 8192
}
```

**允许覆盖的参数**：
- `model`（模型名）
- `model temperature`
- `model max_tokens`
- `model fallback`
- `on_fail`
- `retry_count`

**不允许覆盖的参数**（要修改请定义新组件）：
- `port`（端口定义）
- `system_prompt`（提示词）
- `mcp`（MCP 配置）
- `permission`（权限）

### 4.5 连接

连接定义了数据在 Agent 之间的流动。

**4.5.1 基本连接**

```grassflow
A -> B    # A 的默认输出端口 → B 的默认输入端口
```

等价于：

```grassflow
A.out -> B.in
```

**4.5.2 显式端口连接**

```grassflow
A.analysis -> B.context    # A 的 analysis 端口 → B 的 context 端口
```

**4.5.3 广播（一对多）**

```grassflow
A -> (B, C, D)             # A 的默认输出 → B、C、D 的默认输入
A.result -> (B.data, C.input)  # A.result → B.data 和 C.input
```

**4.5.4 聚合（多对一）**

```grassflow
(A, B, C) -> D             # A、B、C 的默认输出 → D 的默认输入
```

D 的默认输入端口收到的数据为：

```json
{
    "A": "<A的输出>",
    "B": "<B的输出>",
    "C": "<C的输出>"
}
```

**4.5.5 混合连接**

左侧默认 `out` 端口，右侧默认 `in` 端口，可混合显式端口：

```grassflow
(A, B.analysis) -> C       # A.out → C.in, B.analysis → C.in
(A.result, B) -> C.data    # A.result → C.data, B.out → C.data
```

**4.5.6 连接规则总结**

| 语法 | 等价于 | 说明 |
|------|--------|------|
| `A -> B` | `A.out -> B.in` | 默认端口连接 |
| `A.x -> B.y` | `A.x -> B.y` | 显式端口连接 |
| `(A, B) -> C` | `A.out -> C.in, B.out -> C.in` | 聚合 |
| `A -> (B, C)` | `A.out -> B.in, A.out -> C.in` | 广播 |
| `(A.x, B) -> C.y` | `A.x -> C.y, B.out -> C.y` | 混合 |

---

## 5. 条件分支

条件分支通过 `Connection` 的 `routing_rules` 字段实现。路由 Agent 的输出中包含 `route` 字段，调度器根据该字段值决定将数据路由到哪个下游 Agent。

### 5.1 数据模型

条件路由的核心在 `Connection` 数据模型中：

```python
@dataclass
class Connection:
    source_agent: str
    source_port: Optional[str] = None
    target_agents: List[str] = field(default_factory=list)
    target_ports: List[str] = field(default_factory=list)
    routing_rules: Dict[str, List[str]] = field(default_factory=dict)
    # routing_rules 格式: {condition_value: [target_agent_name, ...]}
```

### 5.2 路由判断逻辑

调度器通过 `Scheduler._should_execute()` 判断 Agent 是否应执行：

1. 收集该 Agent 的所有入边（`Connection`）
2. 如果入边有 `routing_rules`，读取源 Agent 输出中的 `route` 字段
3. `route` 值匹配到 `routing_rules` 中的 key，且当前 Agent 在对应的 target 列表中，则执行
4. 有 `routing_rules` 但未匹配到，不执行

```python
# 伪代码
source_output = context.get(conn.source_agent)
route_value = source_output.get("route")  # 例如 "urgent"
if route_value in conn.routing_rules:
    if agent_name in conn.routing_rules[route_value]:
        return True  # 执行该 Agent
return False  # 跳过该 Agent
```

### 5.3 ConditionAgent

路由 Agent 使用 `ConditionAgent` 类，通过 `rules` 参数定义路由规则：

```python
from core.condition import ConditionAgent

agent = ConditionAgent(component, rules=["urgent", "normal", "info"])
```

在 DSL 中，通过 Agent 名称或 overrides 中的 `rules` 字段声明：

```grassflow
agent route {
    type: "condition"
    rules: ["urgent", "normal", "info"]
}
```

### 5.4 在 workflow 中使用

```grassflow
workflow ticket-processing {
    port input ticket: object
    port output result: object

    agent classify { model: "gpt-4", system_prompt: "分类工单: {ticket}" }
    agent route {
        type: "condition"
        rules: ["urgent", "normal", "info"]
    }
    agent human { type: "manual" }
    agent bot { model: "gpt-4", system_prompt: "自动回复: {ticket}" }

    classify -> route

    # 条件连接：route 的输出根据 route 字段分发
    route -> [urgent] human
    route -> [normal] bot
}
```

**DSL 语法说明**：

- `route -> [urgent] human` 表示：当 `route` 输出的 `route` 字段值为 `"urgent"` 时，执行 `human`
- 方括号内为条件值，对应 `routing_rules` 中的 key
- 同一条件可连接多个目标：`route -> [urgent] (human, alert)`

### 5.5 实现细节

`Connection.routing_rules` 在 DSL 解析器中生成。对于上述示例，解析结果为：

```python
Connection(
    source_agent="route",
    target_agents=["human"],
    routing_rules={"urgent": ["human"]}
)
Connection(
    source_agent="route",
    target_agents=["bot"],
    routing_rules={"normal": ["bot"]}
)
```

调度器在执行每个并行组时，先调用 `_should_execute()` 过滤，只有匹配条件路由的 Agent 才会实际执行。

---

## 6. 组件组合

### 6.1 use 关键字（workflow 内）

`use` 将一个已定义的组件引入到 workflow 中的 Agent 实例：

```grassflow
workflow my-pipeline {
    agent reviewer use code-reviewer          # 引入组件定义
    agent reviewer2 use code-reviewer {
        model temperature: 0.5                # 覆盖运行时参数
    }
}
```

> **注意**：`use` 关键字目前仅在 workflow 内的 `agent` 实例化中实现。组件内部不支持 `use` 引入其他组件（即 `component A { use B }` 未实现）。不支持 `extends` 继承。

### 6.2 引入规则

- `use` 引入组件的**全部定义**（端口、提示词、MCP、权限等）
- 不支持选择性引入（鼓励细粒度拆分组件）
- 同名属性：后者覆盖前者（`system_prompt`、`model` 等）
- 端口：合并（不冲突时）或报错（同名不同类型）
- 权限：合并（取并集）
- MCP：合并（同名 server 的 tools 取并集）

### 6.3 覆盖参数

在 workflow 内使用组件时，可覆盖以下运行时参数：

```grassflow
agent reviewer use code-reviewer {
    model: "gpt-4o"                   # 覆盖模型名
    model temperature: 0.5            # 覆盖温度
    model max_tokens: 8192            # 覆盖最大 token
    on_fail: "retry"                  # 覆盖失败策略
    retry_count: 5                    # 覆盖重试次数
}
```

**不允许覆盖的参数**（要修改请定义新组件）：
- `port`（端口定义）
- `system_prompt`（提示词）
- `mcp`（MCP 配置）
- `permission`（权限）

---

## 7. 组件发现

### 7.1 发现顺序

当使用 `use <name>` 时，按以下顺序搜索：

```
1. 当前文件内的 component 定义
2. 当前目录的 .grass/components/
3. 项目根目录的 .grass/components/
4. 全局 ~/.Grass/components/
5. 远程注册表（未来扩展）
```

找到第一个匹配即使用。多个目录存在同名组件时打印警告。

### 7.2 CLI 管理命令

```bash
grassflow component list                    # 列出所有可用组件
grassflow component show code-reviewer      # 查看组件详情
grassflow component search github           # 搜索组件
grassflow component export code-reviewer    # 导出为独立文件
grassflow component import ./reviewer.gf    # 导入组件
```

---

## 8. 数据流

### 8.1 端口数据映射

**输入映射**：

- 端口名 → 提示词模板变量 `{port_name}`
- 端口名 → `input_data[port_name]`（Python 代码访问）

```grassflow
port input code: string
system_prompt: "审查代码: {code}"
# 运行时 input_data = {"code": "<上游传来的数据>"}
```

**输出映射**：

- `output_schema` 的字段名 = 端口名，自动映射

```grassflow
port output issues: array
# Agent 返回 {"issues": [...]} 时，自动映射到 issues 端口
```

### 8.2 聚合数据格式

多个源连接到同一端口时，数据自动合并为字典：

```grassflow
(A, B) -> C
# C.in = {"A": <A的输出>, "B": <B的输出>}
```

### 8.3 stream 模式数据流（规划中，未完整实现）

```grassflow
component counter {
    mode: "stream"
    context: "shared"
    port input item: string [async]
    port output count: number
}

# A 输出 3 次 → counter 执行 3 次（共享上下文，累积计数）
A -> counter
```

---

## 9. 完整示例

### 9.1 工单处理

```grassflow
# === 组件定义 ===

component ticket-classifier {
    description: "工单分类器"
    port input ticket: object
    port output category: string

    model: "gpt-4"
    system_prompt: "对工单进行分类: {ticket}"
}

component ticket-router {
    description: "工单路由器"
    port input category: string
    port output urgent: object
    port output normal: object
    port output info: object

    model: "gpt-4"
    system_prompt: "根据分类 {category} 路由工单"
}

component auto-responder {
    description: "自动回复"
    port input normal: object
    port output result: object

    model: "gpt-4"
    system_prompt: "自动回复工单: {normal}"
}

component human-reviewer {
    description: "人工审核"
    port input urgent: object
    port output result: object
}

# === 工作流 ===

workflow ticket-processing {
    port input ticket: object
    port output result: object

    agent classify use ticket-classifier
    agent route use ticket-router
    agent bot use auto-responder
    agent human use human-reviewer

    classify -> route
    route.urgent -> human.urgent
    route.normal -> bot.normal

    (human, bot) -> result
}
```

### 9.2 代码审查流水线

```grassflow
component static-analyzer {
    description: "静态分析"
    port input code: string
    port output analysis: object

    mcp sonarqube {
        tools: [analyze_code, get_metrics]
    }
}

component code-reviewer {
    description: "代码审查"
    port input code: string
    port input context: object
    port output issues: array
    port output score: number

    model: "gpt-4"
    model temperature: 0.3
    system_prompt: "审查代码: {code}, 上下文: {context}"

    mcp github {
        tools: [add_comment, create_issue]
    }

    permission allow: [read, glob, grep]
    permission ask: [write]
}

component report-generator {
    description: "报告生成"
    port input analysis: object
    port input issues: array
    port output report: object

    model: "gpt-4"
    system_prompt: "生成审查报告: 分析={analysis}, 问题={issues}"
}

workflow code-review {
    port input code: string
    port output report: object

    agent analyzer use static-analyzer
    agent reviewer use code-reviewer
    agent reporter use report-generator

    # 广播代码到分析器和审查器
    code -> (analyzer.code, reviewer.code)

    # 分析结果作为审查上下文
    analyzer.analysis -> reviewer.context

    # 聚合结果生成报告
    (analyzer.analysis, reviewer.issues) -> reporter

    # 工作流输出
    reporter.report -> report
}
```

### 9.3 流式数据处理（规划中）

> **注意**：`stream` 模式已定义在数据模型中，但当前调度器仅实现了 `batch` 模式。以下为设计示例，尚未完整实现。

```grassflow
component data-fetcher {
    description: "数据获取器"
    mode: "stream"
    context: "independent"

    port input url: string
    port output data: object
}

component data-transformer {
    description: "数据转换器"
    mode: "stream"
    context: "independent"

    port input data: object
    port output transformed: object

    model: "gpt-4"
    system_prompt: "转换数据: {data}"
}

component data-saver {
    description: "数据存储器"
    mode: "stream"
    context: "shared"

    port input transformed: object
    port output saved_count: number
}

workflow stream-pipeline {
    port input urls: array
    port output count: number

    agent fetcher use data-fetcher
    agent transformer use data-transformer
    agent saver use data-saver

    fetcher -> transformer -> saver

    saver.saved_count -> count
}
```

---

## 10. 调度器事件回调

### 10.1 事件类型

调度器通过 `SchedulerEventType` 枚举定义 10 种事件：

```python
class SchedulerEventType(str, Enum):
    WORKFLOW_START   = "workflow_start"    # 工作流开始
    WORKFLOW_COMPLETE = "workflow_complete" # 工作流完成
    WORKFLOW_FAILED  = "workflow_failed"   # 工作流失败
    GROUP_START      = "group_start"       # 并行组开始
    GROUP_COMPLETE   = "group_complete"    # 并行组完成
    AGENT_START      = "agent_start"       # Agent 开始执行
    AGENT_COMPLETE   = "agent_complete"    # Agent 执行完成
    AGENT_FAIL       = "agent_fail"        # Agent 执行失败
    AGENT_RETRY      = "agent_retry"       # Agent 重试
    AGENT_SKIPPED    = "agent_skipped"     # Agent 被跳过
```

### 10.2 事件数据结构

```python
@dataclass
class SchedulerEvent:
    event_type: SchedulerEventType
    agent_name: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    data: Optional[Any] = None
```

`data` 字段因事件类型而异：

| 事件 | data 内容 |
|------|----------|
| `WORKFLOW_START` | `{"workflow_name": str}` |
| `WORKFLOW_COMPLETE` | `{"execution_record": ExecutionRecord}` |
| `WORKFLOW_FAILED` | `{"error": str, "execution_record": ExecutionRecord}` |
| `GROUP_START` | `{"agents": [str, ...]}` |
| `GROUP_COMPLETE` | `{"agents": [str, ...], "results": [...]}` |
| `AGENT_START` | `None` |
| `AGENT_COMPLETE` | `{"output": dict, "duration_ms": int}` |
| `AGENT_FAIL` | `{"error": str, "duration_ms": int}` |
| `AGENT_RETRY` | `{"attempt": int, "max_retries": int}` |
| `AGENT_SKIPPED` | `{"reason": str}` |

### 10.3 回调注册

创建 `Scheduler` 时通过 `on_event` 参数注册回调函数：

```python
scheduler = Scheduler(
    workflow=workflow,
    agents=agents,
    workflow_input={"task": "..."},
    on_event=lambda event: print(f"[{event.event_type}] {event.agent_name}"),
)
```

- 回调为 `None` 时不发射事件（零开销）
- 回调函数抛出异常不影响工作流执行

### 10.4 事件序列示例

一个包含 2 个并行 Agent 的工作流的事件序列：

```
WORKFLOW_START       {workflow_name: "my-workflow"}
GROUP_START          {agents: ["reader"]}
AGENT_START          agent_name="reader"
AGENT_COMPLETE       agent_name="reader"  {output: {...}, duration_ms: 1234}
GROUP_COMPLETE       {agents: ["reader"]}
GROUP_START          {agents: ["complexity", "security"]}
AGENT_START          agent_name="complexity"
AGENT_START          agent_name="security"
AGENT_COMPLETE       agent_name="complexity"  {output: {...}, duration_ms: 567}
AGENT_COMPLETE       agent_name="security"    {output: {...}, duration_ms: 890}
GROUP_COMPLETE       {agents: ["complexity", "security"]}
WORKFLOW_COMPLETE    {execution_record: ...}
```

**实现位置**：`core/scheduler.py` — `Scheduler._emit()`

---

## 11. 工具权限过滤

### 11.1 机制概述

每个 Agent 的工具权限由其所属 Component 的 `permission` 声明决定。运行时通过 `create_filtered_registry()` 从全局 `ToolRegistry` 创建一个独立的过滤注册表。

```python
from core.tool_registry import ToolRegistry, create_filtered_registry, register_builtin_tools

# 1. 全局注册表（包含所有内置工具）
global_registry = ToolRegistry()
register_builtin_tools(global_registry)

# 2. 根据组件权限创建过滤注册表
agent_registry = create_filtered_registry(global_registry, component.permission)

# 3. Agent 只能使用过滤后的工具
agent = LLMAgent(component=component, tool_registry=agent_registry)
```

### 11.2 过滤规则

- `permission.allow` 中列出的工具 ID 被包含
- `permission.deny` 中列出的工具 ID 被排除
- `permission.ask` 中列出的工具 ID 被包含，但执行前需要用户确认
- 优先级：`deny` > `ask` > `allow`
- 如果 `allow` 和 `deny` 都为空，Agent 使用全局注册表（不限制）

### 11.3 内置工具 ID

常用内置工具 ID（用于 `permission` 声明）：

| 工具 ID | 说明 |
|---------|------|
| `read` | 读取文件 |
| `write` | 写入文件 |
| `glob` | 文件模式匹配 |
| `grep` | 内容搜索 |
| `shell` | 执行 Shell 命令 |

**实现位置**：`core/tool_registry.py` — `create_filtered_registry()`

---

## 12. REPL 集成

### 12.1 工作流执行命令

在 REPL 中通过 `/run` 命令执行工作流文件：

```bash
# 执行工作流
/run my_workflow.gf

# 带任务描述执行
/run my_workflow.gf --task "审查代码质量"

# 带额外输入参数
/run my_workflow.gf --task "审查代码" --input debug=true --input format=json

# 取消正在运行的工作流
/run stop

# 列出已保存的工作流
/run
```

**参数说明**：
- `<workflow_file>`：`.gf` 文件路径（支持相对路径、绝对路径，自动搜索 `~/.Grass/workflows/`）
- `--task "描述"`：注入为 `workflow_input["task"]`
- `--input key=value`：注入键值对（支持 JSON 值解析）
- `stop`：取消正在运行的工作流
- 无参数：列出 `~/.Grass/workflows/` 下已保存的工作流

### 12.2 AI 生成工作流命令

通过 `/generate` 命令让 AI 根据自然语言描述生成 DSL：

```bash
# 交互式生成（预览后确认保存）
/generate 创建一个代码审查流水线，先读取代码，然后并行分析复杂度和安全性，最后生成报告

# 仅预览不保存
/generate preview 对比分析方案A和方案B

# 直接保存为指定名称
/generate save my-review 分析代码质量并生成报告
```

**子命令**：
- 无子命令：生成 → 预览 → 交互确认（输入 `yes` 保存、`save <name>` 自定义名称保存、`no` 丢弃）
- `preview`：仅预览，不保存
- `save <name>`：直接保存到 `~/.Grass/workflows/<name>.gf`

### 12.3 意图检测

`IntentDetector` 通过规则匹配自动识别用户消息中的多步骤任务意图，并生成对应的 DSL v2 工作流定义。

**支持的模式**：

| 模式 | 触发词 | 生成结构 | 示例 |
|------|--------|---------|------|
| 顺序依赖 | "然后" | `A -> B` | "分析代码然后生成报告" |
| 多步顺序 | "先...再...最后" | `A -> B -> C` | "先读取再分析最后报告" |
| 并行+聚合 | "对比...和..." | `(A, B) -> C` | "对比方案A和方案B" |
| 并行执行 | "分别" | `(A, B, C)` | "分别分析安全性、性能和风格" |

**实现位置**：`tui/intent_detector.py` — `IntentDetector`

### 12.4 WorkflowRunner 引擎

`WorkflowRunner` 是 REPL 内的工作流执行引擎，对齐 CLI 的 `run_cmd` 逻辑，但面向 REPL 环境：

- **异步执行**：不阻塞 REPL 事件循环
- **事件驱动输出**：通过 `REPLOutputHandler` 将 `SchedulerEvent` 格式化为 Rich 输出
- **可取消**：通过 `asyncio.Task` 支持 `/run stop` 取消
- **自动保存执行记录**：执行完成后保存到 SQLite

**执行流程**：

```
/run my_workflow.gf --task "..."
    │
    ├─ 1. 解析 .gf 文件 (DSLParser)
    ├─ 2. 确定 model/provider (ConfigManager)
    ├─ 3. 注册内置工具 (ToolRegistry)
    ├─ 4. 创建 Agent 实例 (LLMAgent / ConditionAgent)
    │     └─ 按 Component 权限过滤工具 (create_filtered_registry)
    ├─ 5. 合并输入参数 (workflow_input)
    ├─ 6. 创建 Scheduler (带 on_event 回调)
    ├─ 7. 执行 (Scheduler.run)
    │     └─ 事件 → REPLOutputHandler → Rich 输出
    └─ 8. 保存执行记录 (SQLite)
```

**实现位置**：`tui/workflow_runner.py` — `WorkflowRunner`

---

## 13. 语法规则速查表

### 13.1 关键字

| 关键字 | 用途 | 示例 |
|--------|------|------|
| `component` | 定义组件 | `component reviewer { ... }` |
| `workflow` | 定义工作流 | `workflow pipeline { ... }` |
| `agent` | 实例化 Agent | `agent r use reviewer` |
| `use` | workflow 内引入组件 | `agent r use reviewer` |
| `port` | 定义端口 | `port input code: string` |
| `input` | 输入端口方向 | `port input ...` |
| `output` | 输出端口方向 | `port output ...` |
| `mcp` | MCP 服务器配置 | `mcp github { ... }` |
| `permission` | 权限声明 | `permission allow: [...]` |
| `allow` | 允许权限 | `permission allow: [...]` |
| `deny` | 禁止权限 | `permission deny: [...]` |
| `ask` | 询问权限 | `permission ask: [...]` |
| `model` | 模型配置 | `model default: "gpt-4"` |
| `sync` | 同步端口 | `port input x: string [sync]` |
| `async` | 异步端口 | `port input x: string [async]` |
| `shared` | 共享上下文 | `context: "shared"` |
| `independent` | 独立上下文 | `context: "independent"` |

### 13.2 连接语法

| 语法 | 含义 |
|------|------|
| `A -> B` | A 默认输出 → B 默认输入 |
| `A.x -> B.y` | A 端口 x → B 端口 y |
| `(A, B) -> C` | 聚合：A、B → C |
| `A -> (B, C)` | 广播：A → B、C |
| `(A.x, B) -> C.y` | 混合连接 |

### 13.3 属性覆盖规则

| 属性 | 实例化时可覆盖 | 说明 |
|------|---------------|------|
| `model` | ✅ | 模型名、temperature、max_tokens |
| `on_fail` | ✅ | 失败策略 |
| `retry_count` | ✅ | 重试次数 |
| `port` | ❌ | 端口是组件契约，不可覆盖 |
| `system_prompt` | ❌ | 提示词是组件核心，不可覆盖 |
| `mcp` | ❌ | MCP 配置不可覆盖 |
| `permission` | ❌ | 权限不可放宽 |

### 13.4 组件发现路径

```
当前文件 → .grass/components/ → 项目根/.grass/components/ → ~/.Grass/components/
```

---

## 附录 A：端口类型与 JSON Schema 对照

| 端口类型 | JSON Schema | 说明 |
|----------|-------------|------|
| `string` | `{"type": "string"}` | 字符串 |
| `number` | `{"type": "number"}` | 数字 |
| `boolean` | `{"type": "boolean"}` | 布尔 |
| `object` | `{"type": "object"}` | 对象 |
| `array` | `{"type": "array"}` | 数组 |

端口类型是简化声明，用于编辑器提示和连线合法性检查。实际数据校验由 JSON Schema 完成。

## 附录 B：执行模式组合

| mode | context | 触发时机 | 实例策略 | 典型场景 | 状态 |
|------|---------|---------|---------|---------|------|
| `batch` | `shared` | 所有输入就绪 | 复用实例 | 函数调用 | 已实现 |
| `batch` | `independent` | 所有输入就绪 | 新建实例 | 无状态批处理 | 已实现 |
| `stream` | `shared` | 每次输入 | 复用实例（累积） | 流式累加器 | 规划中 |
| `stream` | `independent` | 每次输入 | 新建实例 | 流式 map | 规划中 |

## 附录 C：权限优先级

```
deny > ask > allow
```

- `deny`：禁止调用，无论其他规则
- `ask`：调用前询问用户确认
- `allow`：允许调用

权限是组件的固有属性，实例化时不可覆盖（安全策略不可放宽）。

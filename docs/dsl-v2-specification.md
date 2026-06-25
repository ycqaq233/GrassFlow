# GrassFlow DSL v2 语言规范

> 版本：2.0.0
> 最后更新：2026-06-25

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
    permission allow: [github.add_comment]
    permission deny: [github.delete_repo]
    permission ask: [github.merge_pr]

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

控制 Agent 对 MCP 工具的调用权限。

```
permission allow: [github.add_comment, github.create_issue]   # 允许
permission deny:  [github.delete_repo]                         # 禁止
permission ask:   [github.merge_pr]                            # 每次调用前询问用户
```

**优先级规则**：`deny` > `ask` > `allow`

**继承规则**：权限是组件的固有属性，实例化时**不可覆盖**（安全策略不可放宽）。

#### 3.3.8 mode（执行模式）

```
mode: "batch"     # 批处理：等待所有输入就绪后执行一次（默认）
mode: "stream"    # 流处理：每次收到输入就执行一次
```

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

条件分支通过命名输出端口实现。路由组件为每个可能的分支定义一个输出端口。

### 5.1 定义路由组件

```grassflow
component ticket-router {
    port input ticket: object

    # 每个分支是一个输出端口
    port output urgent: object
    port output normal: object
    port output info: object

    system_prompt: """
        根据工单内容判断优先级。
        输出 JSON: {"route": "urgent|normal|info", "ticket": ...}
    """
}
```

### 5.2 在 workflow 中使用

```grassflow
workflow ticket-processing {
    port input ticket: object
    port output result: object

    agent router use ticket-router
    agent urgent-handler {
        model: "gpt-4"
        system_prompt: "紧急处理: {urgent}"
        port input urgent: object
        port output result: object
    }
    agent normal-handler {
        model: "gpt-4"
        system_prompt: "常规处理: {normal}"
        port input normal: object
        port output result: object
    }
    agent info-handler {
        model: "gpt-4"
        system_prompt: "信息记录: {info}"
        port input info: object
        port output result: object
    }

    # 条件连接：每个分支端口连接到对应处理器
    router.urgent -> urgent-handler.urgent
    router.normal -> normal-handler.normal
    router.info -> info-handler.info

    # 聚合结果（运行时只有一个分支会执行）
    (urgent-handler, normal-handler, info-handler) -> result
}
```

---

## 6. 组件组合

### 6.1 use 关键字

`use` 将一个组件的定义引入到当前组件或 workflow 中：

```grassflow
component my-agent {
    use github-tools        # 引入 MCP 配置
    use base-reviewer       # 引入端口、提示词等

    # 可以覆盖非安全相关的配置
    system_prompt: "我的自定义提示词..."
}
```

### 6.2 引入规则

- `use` 引入组件的**全部定义**（端口、提示词、MCP、权限等）
- 不支持选择性引入（鼓励细粒度拆分组件）
- 同名属性：后者覆盖前者（`system_prompt`、`model` 等）
- 端口：合并（不冲突时）或报错（同名不同类型）
- 权限：合并（取并集）
- MCP：合并（同名 server 的 tools 取并集）

### 6.3 细粒度拆分

当只需要部分能力时，将能力拆分为独立组件：

```grassflow
# MCP 配置独立组件
component github-tools {
    mcp github {
        tools: [add_comment, create_issue]
    }
}

component sonarqube-tools {
    mcp sonarqube {
        tools: [analyze_code]
    }
}

# 组合
component reviewer {
    use github-tools
    use sonarqube-tools
    system_prompt: "你是一个代码审查专家..."
    port input code: string
    port output issues: array
}
```

### 6.4 路径引用

可以使用文件路径显式引用组件：

```grassflow
component my-agent {
    use "./components/github-tools.gf"
    use "~/.Grass/components/base-reviewer.gf"
}
```

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

### 8.3 stream 模式数据流

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

    permission allow: [github.add_comment]
    permission ask: [github.create_issue]
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

### 9.3 流式数据处理

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

## 10. 语法规则速查表

### 10.1 关键字

| 关键字 | 用途 | 示例 |
|--------|------|------|
| `component` | 定义组件 | `component reviewer { ... }` |
| `workflow` | 定义工作流 | `workflow pipeline { ... }` |
| `agent` | 实例化 Agent | `agent r use reviewer` |
| `use` | 引入组件 | `use github-tools` |
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

### 10.2 连接语法

| 语法 | 含义 |
|------|------|
| `A -> B` | A 默认输出 → B 默认输入 |
| `A.x -> B.y` | A 端口 x → B 端口 y |
| `(A, B) -> C` | 聚合：A、B → C |
| `A -> (B, C)` | 广播：A → B、C |
| `(A.x, B) -> C.y` | 混合连接 |

### 10.3 属性覆盖规则

| 属性 | 实例化时可覆盖 | 说明 |
|------|---------------|------|
| `model` | ✅ | 模型名、temperature、max_tokens |
| `on_fail` | ✅ | 失败策略 |
| `retry_count` | ✅ | 重试次数 |
| `port` | ❌ | 端口是组件契约，不可覆盖 |
| `system_prompt` | ❌ | 提示词是组件核心，不可覆盖 |
| `mcp` | ❌ | MCP 配置不可覆盖 |
| `permission` | ❌ | 权限不可放宽 |

### 10.4 组件发现路径

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

| mode | context | 触发时机 | 实例策略 | 典型场景 |
|------|---------|---------|---------|---------|
| `batch` | `shared` | 所有输入就绪 | 复用实例 | 函数调用 |
| `batch` | `independent` | 所有输入就绪 | 新建实例 | 无状态批处理 |
| `stream` | `shared` | 每次输入 | 复用实例（累积） | 流式累加器 |
| `stream` | `independent` | 每次输入 | 新建实例 | 流式 map |

## 附录 C：权限优先级

```
deny > ask > allow
```

- `deny`：禁止调用，无论其他规则
- `ask`：调用前询问用户确认
- `allow`：允许调用

权限是组件的固有属性，实例化时不可覆盖（安全策略不可放宽）。

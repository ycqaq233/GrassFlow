# core/ 目录 Import 错误扫描报告

扫描时间: 2026-06-28
扫描范围: core/ 目录下 15 个 Python 文件 + 额外发现的模块

## 总结

**所有模块均可成功导入**，不存在致命的 ImportError。但发现了 3 个命名冲突/遮蔽问题、1 个跨包依赖问题、2 个过时注释。

---

## 问题清单

### ISSUE-1: ComponentRegistry 类名冲突 (core/__init__.py 遮蔽)

```
FILE: core/__init__.py
ISSUE: __init__.py 从 agent_component 导入 ComponentRegistry，完全遮蔽了 component_registry.py 中功能更完整的同名类。
  - core.agent_component.ComponentRegistry 是简单的内存注册表（152 行，~50 行逻辑）
  - core.component_registry.ComponentRegistry 是完整实现（963 行，支持文件发现、优先级、搜索、导入导出）
  - core.ComponentRegistry 解析为 agent_component 的版本，component_registry 的版本被隐藏
LINE: 78 (from .agent_component import ... ComponentRegistry ...)
FIX: 在 __init__.py 中，将 component_registry 的 ComponentRegistry 重命名为 FileComponentRegistry 或 DiscoveryComponentRegistry 后导入，或只从 component_registry 导入（因为它更完整）。
```

### ISSUE-2: ComponentNotFoundError 类名冲突

```
FILE: core/__init__.py
ISSUE: 同一 __init__.py 中，ComponentNotFoundError 从 agent_component 导入（line 76）。
  - core.component_registry 也定义了 ComponentNotFoundError（继承自 ComponentRegistryError）
  - core.agent_component 也定义了 ComponentNotFoundError（继承自 ComponentError）
  - 两者语义相同但继承层次不同，使用时可能混淆
LINE: 76 (from .agent_component import ... ComponentNotFoundError ...)
FIX: 统一为一个 ComponentNotFoundError，或在 __init__.py 中使用别名区分。
```

### ISSUE-3: LLMResponse 类名冲突

```
FILE: core/llm_protocol.py
ISSUE: llm_protocol.py 定义了自己的 LLMResponse (line 106-114)，与 llm.py 的 LLMResponse (line 16-21) 同名但结构完全不同。
  - core.llm.LLMResponse: content, model, usage(dict), finish_reason
  - core.llm_protocol.LLMResponse: text, reasoning, tool_calls, usage(Usage), model, finish_reason, raw_events
  - __init__.py 只导出 llm.py 的版本，llm_protocol.py 的版本被遮蔽但未标记
LINE: 106 (class LLMResponse)
FIX: 将 llm_protocol.py 的 LLMResponse 重命名为 ProtocolLLMResponse 以区分。llm_protocol.py 内部已有 _LegacyLLMResponse 用于兼容，但主 LLMResponse 仍与 llm.py 冲突。
```

### ISSUE-4: component_registry.py 跨包依赖

```
FILE: core/component_registry.py
ISSUE: 第 33 行 `from tui.dsl_parser_v2 import DSLv2Parser` 导致 core 包依赖 tui 包。
  - core 是底层包，tui 是上层包，这违反了依赖方向原则
  - 如果 tui 未安装或有导入错误，component_registry 无法使用
  - 虽然当前能成功导入（因为 tui.dsl_parser_v2 存在），但架构上不合理
LINE: 33
FIX: 将 DSLv2Parser 的实例化延迟到实际使用时，或通过依赖注入传入 parser，或将 DSLv2Parser 移到 core 包中。
```

### ISSUE-5: 过时注释引用已删除模块

```
FILE: core/execution.py
ISSUE: 第 5 行注释引用了已删除的 core/dsl_v2_ast.py:
  "DSL 定义类型在 core/models.py（或 core/dsl_v2_ast.py）中。"
  core/dsl_v2_ast.py 已不存在，注释具有误导性。
LINE: 5
FIX: 删除注释中对 core/dsl_v2_ast.py 的引用。
```

### ISSUE-6: 过时注释引用已删除类型

```
FILE: core/llm_agent.py
ISSUE: 第 6 行注释引用了已删除的 AgentConfig:
  "重构：LLMAgent 从 Component 构造，不再依赖 AgentConfig。"
  AgentConfig 已从 core.models 中删除，注释已完成使命但仍保留。
LINE: 6
FIX: 可保留作为重构历史记录，或简化为 "LLMAgent 从 Component 构造。"
```

### ISSUE-7: component_registry.py 冗余 try/except

```
FILE: core/component_registry.py
ISSUE: 第 29-32 行的 try/except 块中，try 和 except 做的是完全相同的事情:
  try:
      from core.models import Component, ParseResult
  except ImportError:
      from core.models import Component, ParseResult
  这段代码没有意义。
LINE: 29-32
FIX: 删除 try/except，直接使用 `from core.models import Component, ParseResult`。
```

---

## 验证结果

所有模块均可独立导入且无循环依赖:

| 模块 | 状态 |
|------|------|
| core | OK |
| core.models | OK |
| core.agent | OK |
| core.execution | OK |
| core.context | OK |
| core.dag | OK |
| core.scheduler | OK |
| core.condition | OK |
| core.llm | OK |
| core.llm_agent | OK |
| core.storage | OK |
| core.db | OK |
| core.monitor | OK |
| core.config | OK |
| core.tool_registry | OK |
| core.error_classifier | OK |
| core.permission | OK |
| core.component_registry | OK |
| core.agent_component | OK |
| core.llm_protocol | OK |
| core.skills | OK |
| core.workflow_generator | OK |
| core.model_discovery | OK |
| core.mcp_client | OK |
| core.circuit_breaker | OK |
| core.doom_loop | OK |

**未发现的问题类型:**
- 不存在引用 WorkflowV1, Edge, InteractionType, AgentConfig 等已删除类型（仅注释中提及）
- 不存在引用 core.dsl_v2_ast 等已删除模块（仅注释中提及）
- 不存在循环导入
- 所有 import 路径均正确

## 优先级建议

| 优先级 | Issue | 影响 |
|--------|-------|------|
| P1 | ISSUE-1 (ComponentRegistry 遮蔽) | 功能丢失：用户通过 core.ComponentRegistry 无法访问完整的文件发现功能 |
| P1 | ISSUE-4 (跨包依赖) | 架构违规：core 依赖 tui，可能导致安装/部署问题 |
| P2 | ISSUE-3 (LLMResponse 冲突) | 代码混淆：两个同名类结构不同，容易误用 |
| P2 | ISSUE-2 (ComponentNotFoundError 冲突) | 异常处理混乱：catch 时可能捕获错误的类型 |
| P3 | ISSUE-7 (冗余 try/except) | 代码质量：无功能影响 |
| P3 | ISSUE-5, ISSUE-6 (过时注释) | 文档质量：无功能影响 |

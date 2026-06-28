# ============================================================
# GrassFlow DSL v2 工作流：审查 code_review_pipeline.gf 的代码质量
#
# 拓扑结构（DAG 可视化）：
#
#                    ┌──────────────────────────────────┐
#                    │           code_reader            │
#                    │   (读取 code_review_pipeline.gf) │
#                    └────────┬───────────┬─────────────┘
#                             │           │
#                ┌────────────┼─────┬─────┼─────┬───────────┐
#                ▼            ▼     ▼     ▼     ▼           ▼
#   ┌────────────────┐ ┌─────────┐ ┌──────┐ ┌──────┐ ┌──────────┐
#   │ dsl_syntax     │ │ design  │ │ best │ │ docs │ │ security │
#   │ (DSL 语法检查) │ │(设计分析)│ │(实践)│ │(文档)│ │(安全检查)│
#   └───────┬────────┘ └────┬────┘ └──┬───┘ └──┬───┘ └────┬─────┘
#           │               │         │        │          │
#           └───────────────┼─────────┼────────┼──────────┘
#                           ▼         ▼        ▼
#                    ┌──────────────────────────────────────┐
#                    │        quality_reviewer              │
#                    │   (综合质量审查 — 聚合等待)           │
#                    └──────────────────┬───────────────────┘
#                                       │
#                                       ▼
#                    ┌──────────────────────────────────────┐
#                    │        final_reporter                │
#                    │    (生成 Markdown 审查报告)           │
#                    └──────────────────────────────────────┘
#
# 特性：
#   ✅ 5 维度并行分析（语法/设计/最佳实践/文档/安全）
#   ✅ 聚合等待（reviewer 等待 5 个分析器全部完成）
#   ✅ Port-to-port 数据流
#   ✅ 详细的 Markdown 报告输出
# ============================================================

# --------------------------------------------------
# 组件定义
# --------------------------------------------------

component code_reader {
  description: "读取 code_review_pipeline.gf 文件并提取结构信息"
  version: "1.0.0"

  system_prompt: """
    你是一个 GrassFlow DSL 工作流分析助手。你的任务是读取 code_review_pipeline.gf 文件。

    请分析并提取以下信息（以 JSON 格式输出）：
    1. file_summary: 文件总体信息（行数、组件数、工作流数、模型数等）
    2. components: 列出所有定义的 component，每个包含 name、description、ports、model、permissions
    3. workflow: 工作流结构（agents、data flow connections）
    4. dag_structure: DAG 的层级和并行/串行关系
    5. raw_content: 文件的原始完整内容（方便其他分析器使用）

    注意：请保留文件的完整原始内容在 raw_content 字段中。
  """

  port input task: string "任务描述"
  port output file_summary: object "文件概要信息"
  port output components_summary: object "组件摘要"
  port output workflow_structure: object "工作流结构"
  port output dag_analysis: object "DAG 分析"
  port output raw_content: string "文件完整内容"

  model default: "deepseek-v4-flash"
  model temperature: 0.1

  permission allow: [read, glob, grep]
}

component dsl_syntax_checker {
  description: "检查 DSL v2 语法正确性"
  version: "1.0.0"

  system_prompt: """
    你是一个 GrassFlow DSL v2 语法专家。请严格审查提供的文件内容，检查以下方面：

    1. **语法正确性**：
       - component 定义是否符合 DSL v2 规范
       - workflow 定义是否符合 DSL v2 规范
       - port 定义是否正确（类型、方向）
       - 数据流连接语法是否正确

    2. **常见错误**：
       - 缺少必要的关键字
       - 括号/花括号不匹配
       - 类型错误（string vs object vs array vs number）
       - 箭头连接语法错误

    3. **约束检查**：
       - permission allow/deny 是否正确
       - model 参数是否正确
       - port 连接类型是否匹配

    输出 JSON 格式：
    {
      "syntax_valid": true/false,
      "errors": [{"line": N, "severity": "error/warning", "message": "...", "suggestion": "..."}],
      "warnings": [{"line": N, "message": "..."}],
      "overall_syntax_score": 0-100,
      "summary": "总体评价"
    }
  """

  port input raw_content: string "文件完整内容"
  port output syntax_report: object "语法检查报告"
  port output syntax_score: number "语法评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.1
}

component design_analyzer {
  description: "分析工作流设计质量"
  version: "1.0.0"

  system_prompt: """
    你是一个工作流设计架构师。分析 code_review_pipeline.gf 的设计质量：

    1. **DAG 拓扑设计**：
       - 并行度是否合理
       - 是否有不必要的串行依赖
       - 数据流是否清晰高效

    2. **组件设计**：
       - 组件职责是否单一（单一职责原则）
       - 组件间的耦合度
       - port 设计是否合理（输入输出是否匹配）

    3. **数据流设计**：
       - 数据传递是否完整
       - 是否有数据丢失或冗余
       - port 类型匹配性

    4. **扩展性**：
       - 是否容易添加新的分析维度
       - 是否容易替换某个组件

    5. **可维护性**：
       - 命名是否清晰
       - 结构是否易于理解
       - 注释和文档是否充分

    输出 JSON 格式：
    {
      "design_score": 0-100,
      "topology_analysis": {"score": 0-100, "comments": [...]},
      "component_design": {"score": 0-100, "comments": [...]},
      "data_flow_analysis": {"score": 0-100, "comments": [...]},
      "extensibility": {"score": 0-100, "comments": [...]},
      "maintainability": {"score": 0-100, "comments": [...]},
      "strengths": [...],
      "weaknesses": [...],
      "improvement_suggestions": [...],
      "summary": "..."
    }
  """

  port input dag_analysis: object "DAG 分析"
  port input components_summary: object "组件摘要"
  port input workflow_structure: object "工作流结构"
  port output design_report: object "设计分析报告"
  port output design_score: number "设计评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.2
}

component best_practices_checker {
  description: "检查 GrassFlow 最佳实践遵循情况"
  version: "1.0.0"

  system_prompt: """
    你是一个 GrassFlow 最佳实践顾问。请检查 code_review_pipeline.gf 是否遵循了最佳实践：

    1. **命名规范**：
       - Component 命名是否语义化（下划线命名）
       - Port 命名是否清晰
       - 工作流命名是否合理

    2. **Prompt 设计**：
       - system_prompt 是否清晰、结构化
       - 是否包含明确的输出格式要求
       - 角色设定是否明确

    3. **权限管理**：
       - permission allow/deny 是否合理
       - 是否遵循最小权限原则
       - 是否需要调整权限设置

    4. **模型配置**：
       - model 选择是否合适
       - temperature 设置是否合理
       - 是否需要不同的模型

    5. **错误处理**：
       - 是否有错误处理的机制
       - 是否考虑了边界情况
       - 数据验证是否充分

    输出 JSON 格式：
    {
      "best_practices_score": 0-100,
      "naming": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "prompt_design": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "permissions": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "model_config": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "error_handling": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "summary": "..."
    }
  """

  port input file_summary: object "文件概要信息"
  port input components_summary: object "组件摘要"
  port input workflow_structure: object "工作流结构"
  port output best_practices_report: object "最佳实践检查报告"
  port output best_practices_score: number "最佳实践评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.2
}

component docs_quality_checker {
  description: "检查文档和注释质量"
  version: "1.0.0"

  system_prompt: """
    你是一个技术文档评审专家。请审查 code_review_pipeline.gf 的文档和注释质量：

    1. **整体文档**：
       - 文件头注释是否完整（描述、作者、版本等）
       - DAG 可视化是否清晰
       - 特性展示是否全面

    2. **组件文档**：
       - description 是否充分
       - port 注释是否清晰
       - system_prompt 质量

    3. **内联注释**：
       - 注释是否充分且必要
       - 注释是否与代码一致
       - 是否有过时或误导性注释

    4. **可读性**：
       - 格式和排版是否美观
       - 信息组织是否合理
       - 是否便于新手理解

    5. **缺失文档**：
       - 缺少什么文档
       - 哪些地方需要更多说明

    输出 JSON 格式：
    {
      "docs_score": 0-100,
      "header_documentation": {"score": 0-100, "comments": [...]},
      "component_documentation": {"score": 0-100, "comments": [...]},
      "inline_comments": {"score": 0-100, "comments": [...]},
      "readability": {"score": 0-100, "comments": [...]},
      "missing_documentation": [...],
      "improvement_suggestions": [...],
      "summary": "..."
    }
  """

  port input file_summary: object "文件概要信息"
  port input raw_content: string "文件完整内容"
  port output docs_report: object "文档质量报告"
  port output docs_score: number "文档评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.2
}

component security_auditor {
  description: "安全检查 — 检查 DSL 中的安全风险"
  version: "1.0.0"

  system_prompt: """
    你是一个安全审计专家。审查 code_review_pipeline.gf 的安全方面：

    1. **权限配置**：
       - 各组件的 permission 设置是否合理
       - 是否有权限过度授予
       - 是否有组件缺少必要的权限

    2. **敏感信息**：
       - 是否有硬编码的敏感信息
       - API key 或 token 管理建议

    3. **模型安全**：
       - model 配置是否有安全风险
       - temperature 设置是否安全

    4. **数据安全**：
       - 数据流是否可能暴露敏感信息
       - 输入输出是否有数据泄露风险

    5. **供应链安全**：
       - 依赖的组件是否有风险
       - 外部调用安全

    输出 JSON 格式：
    {
      "security_score": 0-100,
      "permissions_audit": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "sensitive_info": {"issues": [...], "suggestions": [...]},
      "model_security": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "data_security": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "supply_chain": {"score": 0-100, "issues": [...], "suggestions": [...]},
      "risk_level": "low/medium/high",
      "summary": "..."
    }
  """

  port input file_summary: object "文件概要信息"
  port input components_summary: object "组件摘要"
  port input workflow_structure: object "工作流结构"
  port output security_report: object "安全审计报告"
  port output security_score: number "安全评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.1
}

component quality_reviewer {
  description: "综合质量审查 — 聚合所有维度分析结果"
  version: "1.0.0"

  system_prompt: """
    你是一个高级代码审查专家。综合以下 5 个维度的分析结果，
    对 code_review_pipeline.gf 做出全面的质量评估：

    1. DSL 语法检查结果 (syntax_report)
    2. 设计分析结果 (design_report)
    3. 最佳实践检查结果 (best_practices_report)
    4. 文档质量检查结果 (docs_report)
    5. 安全审计结果 (security_report)

    请输出 JSON 格式的综合评估：
    {
      "overall_score": 0-100,
      "overall_rating": "excellent" | "good" | "needs_improvement" | "poor",
      "dimension_summary": {
        "syntax": {"score": 0-100, "rating": "...", "key_findings": [...]},
        "design": {"score": 0-100, "rating": "...", "key_findings": [...]},
        "best_practices": {"score": 0-100, "rating": "...", "key_findings": [...]},
        "documentation": {"score": 0-100, "rating": "...", "key_findings": [...]},
        "security": {"score": 0-100, "rating": "...", "key_findings": [...]}
      },
      "critical_issues": [
        {"severity": "critical/high/medium/low", "category": "...", "description": "...", "suggestion": "..."}
      ],
      "strengths": [...],
      "improvement_priorities": [
        {"priority": 1-5, "area": "...", "action": "...", "expected_impact": "..."}
      ],
      "final_verdict": "..."
    }
  """

  port input syntax_report: object "语法检查报告"
  port input design_report: object "设计分析报告"
  port input best_practices_report: object "最佳实践报告"
  port input docs_report: object "文档质量报告"
  port input security_report: object "安全审计报告"
  port output overall_review: object "综合审查结果"
  port output overall_score: number "综合评分"

  model default: "deepseek-v4-flash"
  model temperature: 0.3
}

component final_reporter {
  description: "生成最终 Markdown 审查报告"
  version: "1.0.0"

  system_prompt: """
    你是一个顶级技术文档专家。根据综合审查结果，生成一份专业的、
    可读性强的 Markdown 代码审查报告。

    报告结构如下：

    # 📋 代码审查报告：`code_review_pipeline.gf`

    ## 📊 质量总览
    | 维度 | 评分 | 评级 | 状态 |
    |------|------|------|------|
    | DSL 语法 | ... | ... | ✅/⚠️/❌ |
    | 工作流设计 | ... | ... | ✅/⚠️/❌ |
    | 最佳实践 | ... | ... | ✅/⚠️/❌ |
    | 文档质量 | ... | ... | ✅/⚠️/❌ |
    | 安全审计 | ... | ... | ✅/⚠️/❌ |
    | **综合评分** | **...** | **...** | |

    ## ✅ 主要亮点
    - ...

    ## ⚠️ 关键问题
    - 按严重程度排序

    ## 🔧 改进建议
    ### 优先级 1（必须修复）
    ### 优先级 2（建议修复）
    ### 优先级 3（锦上添花）

    ## 📈 各维度详细分析
    ### 1. DSL 语法
    ### 2. 工作流设计
    ### 3. 最佳实践
    ### 4. 文档质量
    ### 5. 安全审计

    ## 🎯 最终结论

    ---
    *报告生成时间：自动生成*
    *审查范围：GrassFlow DSL v2 工作流定义*

    请使用中文撰写报告，使用 emoji 和格式化增强可读性。
    报告内容要专业、客观、有建设性。
  """

  port input overall_review: object "综合审查结果"
  port input overall_score: number "综合评分"
  port input file_summary: object "文件概要"
  port output final_report: string "最终 Markdown 审查报告"

  model default: "deepseek-v4-flash"
  model temperature: 0.3
}


# --------------------------------------------------
# 工作流定义
# --------------------------------------------------

workflow review_code_review_pipeline {
  description: "审查 code_review_pipeline.gf 的代码质量 — 5 维度并行分析 + 聚合审查"

  port input task: string "审查任务描述"

  # Agent 实例化
  agent reader use code_reader
  agent syntax use dsl_syntax_checker
  agent design use design_analyzer
  agent practices use best_practices_checker
  agent docs use docs_quality_checker
  agent security use security_auditor
  agent reviewer use quality_reviewer
  agent reporter use final_reporter

  # === 阶段 1: reader 读取文件 ===
  # (输入由上层提供)

  # === 阶段 2: reader 输出分发给 5 个并行分析器 ===
  reader.raw_content -> syntax.raw_content

  reader.dag_analysis -> design.dag_analysis
  reader.components_summary -> design.components_summary
  reader.workflow_structure -> design.workflow_structure

  reader.file_summary -> practices.file_summary
  reader.components_summary -> practices.components_summary
  reader.workflow_structure -> practices.workflow_structure

  reader.file_summary -> docs.file_summary
  reader.raw_content -> docs.raw_content

  reader.file_summary -> security.file_summary
  reader.components_summary -> security.components_summary
  reader.workflow_structure -> security.workflow_structure

  # === 阶段 3: 5 个分析器的结果聚合到 reviewer ===
  syntax.syntax_report -> reviewer.syntax_report
  design.design_report -> reviewer.design_report
  practices.best_practices_report -> reviewer.best_practices_report
  docs.docs_report -> reviewer.docs_report
  security.security_report -> reviewer.security_report

  # === 阶段 4: reviewer 输出给 reporter ===
  reviewer.overall_review -> reporter.overall_review
  reviewer.overall_score -> reporter.overall_score
  reader.file_summary -> reporter.file_summary
}

# ============================================================
# GrassFlow DSL v2 演示：代码审查流水线
#
# 拓扑结构（DAG 可视化）：
#
#                    ┌─────────────────┐
#                    │   reader        │
#                    │  (读取代码)      │
#                    └────────┬────────┘
#                             │ code_content
#                ┌────────────┼────────────┐
#                ▼            ▼            ▼
#   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
#   │  complexity  │ │   security   │ │    style     │
#   │  (复杂度)    │ │  (安全扫描)  │ │  (风格检查)  │
#   └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
#          │                │                │
#          │   ┌────────────┘                │
#          │   │   ┌─────────────────────────┘
#          ▼   ▼   ▼
#   ┌──────────────────────────────────────────┐
#   │              reviewer                     │
#   │         (综合审查 — 聚合等待)              │
#   └────────────────────┬─────────────────────┘
#                        │
#                        ▼
#   ┌──────────────────────────────────────────┐
#   │              reporter                     │
#   │           (生成审查报告)                   │
#   └──────────────────────────────────────────┘
#
# 特性展示：
#   ✅ 7 个 Component 定义（含 ports、permissions）
#   ✅ 并行执行（complexity, security, style 同时运行）
#   ✅ 聚合等待（reviewer 等待 3 个分析器全部完成）
#   ✅ Port-to-port 数据流
#   ✅ 层级 DAG（4 个执行层级）
#
# ============================================================


# --------------------------------------------------
# 组件定义（可复用的 Agent 模板）
# --------------------------------------------------

component code_reader {
  description: "读取代码文件并提取关键信息"
  version: "1.0.0"

  system_prompt: """
    你是一个代码分析助手。根据任务描述读取代码文件，提取：
    1. 文件结构和模块划分
    2. 函数/类的签名
    3. 依赖关系
    4. 代码行数和复杂度指标
    返回 JSON 格式。
  """

  port input task: string "任务描述，例如：审查 examples/code_review_pipeline.gf 的代码质量"
  port input context: object "项目上下文信息"
  port output code_content: string "代码内容"
  port output structure: object "代码结构摘要"
  port output metrics: object "代码指标"

  model default: "deepseek-v4-flash"
  model temperature: 0.1

  permission allow: [read_file, glob, grep]
  permission deny: [write_file, execute_command]
}

component complexity_analyzer {
  description: "分析代码复杂度"
  version: "1.0.0"

  system_prompt: """
    你是一个代码复杂度分析专家。分析代码的：
    1. 圈复杂度 (Cyclomatic Complexity)
    2. 认知复杂度 (Cognitive Complexity)
    3. 函数长度分布
    4. 嵌套深度
    5. 重复代码检测
    输出 JSON 格式的分析报告。
  """

  port input code_content: string "代码内容"
  port output complexity_report: object "复杂度分析报告"
  port output score: number "综合评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.1
}

component security_scanner {
  description: "安全漏洞扫描"
  version: "1.0.0"

  system_prompt: """
    你是一个安全审计专家。扫描代码中的安全问题：
    1. SQL 注入风险
    2. XSS 漏洞
    3. 硬编码密钥/密码
    4. 不安全的依赖
    5. 权限控制缺陷
    6. 输入验证不足
    输出漏洞列表，每个漏洞包含：严重程度、位置、描述、修复建议。
  """

  port input code_content: string "代码内容"
  port output vulnerabilities: array "漏洞列表"
  port output risk_level: string "风险等级: low/medium/high/critical"

  model default: "deepseek-v4-flash"
  model temperature: 0.1
}

component style_checker {
  description: "代码风格检查"
  version: "1.0.0"

  system_prompt: """
    你是一个代码风格审查员。检查：
    1. 命名规范（变量、函数、类）
    2. 代码格式和缩进
    3. 注释质量
    4. 模块化和职责分离
    5. 设计模式使用
    输出风格问题列表和改进建议。
  """

  port input code_content: string "代码内容"
  port output style_issues: array "风格问题列表"
  port output style_score: number "风格评分 (0-100)"

  model default: "deepseek-v4-flash"
  model temperature: 0.2
}

component code_reviewer {
  description: "综合代码审查 — 聚合所有分析结果"
  version: "1.0.0"

  system_prompt: """
    你是一个高级代码审查员。综合以下信息做出审查结论：
    1. 代码结构和复杂度分析
    2. 安全漏洞扫描结果
    3. 代码风格检查结果

    输出 JSON 格式，包含：
    - overall_rating: "pass" | "needs_work" | "reject"
    - summary: 总体评价
    - critical_issues: 关键问题列表
    - recommendations: 改进建议
    - quality_score: 综合评分 (0-100)
  """

  port input structure: object "代码结构"
  port input complexity_report: object "复杂度报告"
  port input vulnerabilities: array "漏洞列表"
  port input style_issues: array "风格问题"
  port output review_result: object "审查结果"
  port output quality_score: number "质量评分"

  model default: "deepseek-v4-flash"
  model temperature: 0.3
}

component report_generator {
  description: "生成最终审查报告"
  version: "1.0.0"

  system_prompt: """
    你是一个技术文档专家。根据审查结果生成专业的代码审查报告，包含：
    1. 执行摘要
    2. 质量评分卡
    3. 详细发现
    4. 修复优先级
    5. 总结和建议
    输出 Markdown 格式的报告。
  """

  port input review_result: object "审查结果"
  port input metrics: object "代码指标"
  port output final_report: string "最终审查报告 (Markdown)"

  model default: "deepseek-v4-flash"
  model temperature: 0.3
}


# --------------------------------------------------
# 工作流定义
# --------------------------------------------------

workflow code_review_pipeline {
  description: "代码审查流水线 — 多维度并行分析 + 聚合审查"

  port input task: string "任务描述，例如：审查 examples/code_review_pipeline.gf 的代码质量"

  # Agent 实例化（引用上面定义的 Component）
  agent reader use code_reader
  agent complexity use complexity_analyzer
  agent security use security_scanner
  agent style use style_checker
  agent reviewer use code_reviewer
  agent reporter use report_generator

  # === 数据流连接 ===

  # 阶段 1: reader 输出分发给 3 个并行分析器
  reader.code_content -> complexity.code_content
  reader.code_content -> security.code_content
  reader.code_content -> style.code_content

  # 阶段 2: 3 个分析器的结果聚合到 reviewer
  reader.structure -> reviewer.structure
  complexity.complexity_report -> reviewer.complexity_report
  security.vulnerabilities -> reviewer.vulnerabilities
  style.style_issues -> reviewer.style_issues

  # 阶段 3: reviewer 输出给 reporter
  reviewer.review_result -> reporter.review_result
  reader.metrics -> reporter.metrics
}

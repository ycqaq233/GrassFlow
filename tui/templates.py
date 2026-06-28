"""
GrassFlow 工作流模板 (v2 格式)

提供常用工作流模板，使用 Component + Workflow 结构
"""

from typing import Dict, Any, List, Optional
try:
    from core.models import Component, AgentInstance, Connection, Workflow, Port, ModelConfig
except ImportError:
    from core.dsl_v2_ast import Component, AgentInstance, Connection, Workflow, Port, ModelConfig


def _make_component(name: str, system_prompt: str = "", ports: Optional[List[Port]] = None,
                    model_default: str = "default", **kwargs) -> Component:
    """辅助函数：快速创建 Component"""
    model = ModelConfig(default=model_default)
    return Component(
        name=name,
        system_prompt=system_prompt,
        ports=ports or [],
        model=model,
        **kwargs,
    )


def _make_port(name: str, direction: str, type_: str, description: str = "") -> Port:
    """辅助函数：快速创建 Port"""
    return Port(name=name, direction=direction, type=type_, description=description)


# ==================== 组件定义 ====================

# --- ticket_processing ---
_TICKET_COMPONENTS = [
    _make_component(
        "classifier",
        system_prompt="分类工单: {input}",
        ports=[
            _make_port("ticket", "input", "string", "待分类的工单"),
            _make_port("category", "output", "string", "分类结果"),
        ],
    ),
    _make_component(
        "priority",
        system_prompt="判断优先级: {input}",
        ports=[
            _make_port("ticket", "input", "string", "工单内容"),
            _make_port("priority", "output", "string", "优先级"),
        ],
    ),
    _make_component(
        "router",
        system_prompt="根据分类和优先级路由工单",
        ports=[
            _make_port("category", "input", "string", "工单分类"),
            _make_port("priority", "input", "string", "优先级"),
            _make_port("route", "output", "string", "路由结果"),
        ],
    ),
    _make_component(
        "human_handler",
        system_prompt="人工处理工单",
        ports=[
            _make_port("ticket", "input", "string", "工单内容"),
        ],
    ),
    _make_component(
        "bot_handler",
        system_prompt="自动回复: {input}",
        ports=[
            _make_port("ticket", "input", "string", "工单内容"),
            _make_port("category", "input", "string", "工单分类"),
            _make_port("response", "output", "string", "自动回复"),
        ],
    ),
]

_TICKET_WORKFLOW = Workflow(
    name="ticket_processing",
    agents=[
        AgentInstance(name="classify", component="classifier"),
        AgentInstance(name="prio", component="priority"),
        AgentInstance(name="route", component="router"),
        AgentInstance(name="human", component="human_handler"),
        AgentInstance(name="bot", component="bot_handler"),
    ],
    connections=[
        Connection(source_agent="classify", target_agents=["route"]),
        Connection(source_agent="prio", target_agents=["route"]),
        Connection(source_agent="route", target_agents=["human"], target_ports=["ticket"]),
        Connection(source_agent="route", target_agents=["bot"], target_ports=["ticket"]),
    ],
)

# --- competitor_analysis ---
_COMPETITOR_COMPONENTS = [
    _make_component(
        "searcher_a",
        system_prompt="搜索竞品A的信息: {input}",
        ports=[
            _make_port("company", "input", "string", "公司名称"),
            _make_port("info", "output", "object", "搜索结果"),
        ],
    ),
    _make_component(
        "searcher_b",
        system_prompt="搜索竞品B的信息: {input}",
        ports=[
            _make_port("company", "input", "string", "公司名称"),
            _make_port("info", "output", "object", "搜索结果"),
        ],
    ),
    _make_component(
        "searcher_c",
        system_prompt="搜索竞品C的信息: {input}",
        ports=[
            _make_port("company", "input", "string", "公司名称"),
            _make_port("info", "output", "object", "搜索结果"),
        ],
    ),
    _make_component(
        "analyzer",
        system_prompt="分析竞品信息并生成报告",
        ports=[
            _make_port("competitor_a", "input", "object", "竞品A信息"),
            _make_port("competitor_b", "input", "object", "竞品B信息"),
            _make_port("competitor_c", "input", "object", "竞品C信息"),
            _make_port("report", "output", "object", "分析报告"),
        ],
    ),
    _make_component(
        "reporter",
        system_prompt="生成最终报告: {input}",
        ports=[
            _make_port("analysis", "input", "object", "分析结果"),
            _make_port("final_report", "output", "string", "最终报告"),
        ],
    ),
]

_COMPETITOR_WORKFLOW = Workflow(
    name="competitor_analysis",
    agents=[
        AgentInstance(name="search_a", component="searcher_a"),
        AgentInstance(name="search_b", component="searcher_b"),
        AgentInstance(name="search_c", component="searcher_c"),
        AgentInstance(name="analyze", component="analyzer"),
        AgentInstance(name="report", component="reporter"),
    ],
    connections=[
        Connection(source_agent="search_a", target_agents=["analyze"]),
        Connection(source_agent="search_b", target_agents=["analyze"]),
        Connection(source_agent="search_c", target_agents=["analyze"]),
        Connection(source_agent="analyze", target_agents=["report"]),
    ],
)

# --- code_review ---
_CODE_REVIEW_COMPONENTS = [
    _make_component(
        "security_checker",
        system_prompt="检查代码安全性: {input}",
        ports=[
            _make_port("code", "input", "string", "待审查代码"),
            _make_port("security_issues", "output", "array", "安全问题列表"),
        ],
    ),
    _make_component(
        "style_checker",
        system_prompt="检查代码风格: {input}",
        ports=[
            _make_port("code", "input", "string", "待审查代码"),
            _make_port("style_issues", "output", "array", "风格问题列表"),
        ],
    ),
    _make_component(
        "logic_checker",
        system_prompt="检查代码逻辑: {input}",
        ports=[
            _make_port("code", "input", "string", "待审查代码"),
            _make_port("logic_issues", "output", "array", "逻辑问题列表"),
        ],
    ),
    _make_component(
        "summarizer",
        system_prompt="汇总审查结果: {input}",
        ports=[
            _make_port("security_issues", "input", "array", "安全问题"),
            _make_port("style_issues", "input", "array", "风格问题"),
            _make_port("logic_issues", "input", "array", "逻辑问题"),
            _make_port("summary", "output", "string", "汇总报告"),
            _make_port("severity", "output", "string", "严重程度"),
        ],
    ),
    _make_component(
        "review_router",
        system_prompt="根据审查结果路由",
        ports=[
            _make_port("severity", "input", "string", "严重程度"),
            _make_port("route", "output", "string", "路由结果"),
        ],
    ),
    _make_component(
        "block_merge_handler",
        system_prompt="阻止合并，需要人工处理",
        ports=[
            _make_port("summary", "input", "string", "审查汇总"),
        ],
    ),
    _make_component(
        "approve_handler",
        system_prompt="批准合并",
        ports=[
            _make_port("summary", "input", "string", "审查汇总"),
        ],
    ),
]

_CODE_REVIEW_WORKFLOW = Workflow(
    name="code_review",
    agents=[
        AgentInstance(name="security_check", component="security_checker"),
        AgentInstance(name="style_check", component="style_checker"),
        AgentInstance(name="logic_check", component="logic_checker"),
        AgentInstance(name="summarize", component="summarizer"),
        AgentInstance(name="route", component="review_router"),
        AgentInstance(name="block_merge", component="block_merge_handler"),
        AgentInstance(name="approve", component="approve_handler"),
    ],
    connections=[
        Connection(source_agent="security_check", target_agents=["summarize"]),
        Connection(source_agent="style_check", target_agents=["summarize"]),
        Connection(source_agent="logic_check", target_agents=["summarize"]),
        Connection(source_agent="summarize", target_agents=["route"]),
        Connection(source_agent="route", target_agents=["block_merge"], target_ports=["summary"]),
        Connection(source_agent="route", target_agents=["approve"], target_ports=["summary"]),
    ],
)

# --- data_pipeline ---
_DATA_PIPELINE_COMPONENTS = [
    _make_component(
        "extractor",
        system_prompt="从数据源提取数据: {input}",
        ports=[
            _make_port("source", "input", "string", "数据源"),
            _make_port("raw_data", "output", "object", "原始数据"),
        ],
    ),
    _make_component(
        "validator",
        system_prompt="验证数据质量: {input}",
        ports=[
            _make_port("raw_data", "input", "object", "原始数据"),
            _make_port("is_valid", "output", "boolean", "是否有效"),
            _make_port("issues", "output", "array", "问题列表"),
        ],
    ),
    _make_component(
        "data_router",
        system_prompt="根据验证结果路由",
        ports=[
            _make_port("is_valid", "input", "boolean", "是否有效"),
            _make_port("route", "output", "string", "路由结果"),
        ],
    ),
    _make_component(
        "transformer",
        system_prompt="转换数据格式: {input}",
        ports=[
            _make_port("raw_data", "input", "object", "原始数据"),
            _make_port("transformed_data", "output", "object", "转换后数据"),
        ],
    ),
    _make_component(
        "loader",
        system_prompt="加载数据到目标: {input}",
        ports=[
            _make_port("transformed_data", "input", "object", "转换后数据"),
            _make_port("status", "output", "string", "加载状态"),
            _make_port("count", "output", "integer", "加载记录数"),
        ],
    ),
    _make_component(
        "error_handler",
        system_prompt="处理数据错误: {input}",
        ports=[
            _make_port("issues", "input", "array", "问题列表"),
            _make_port("error_report", "output", "string", "错误报告"),
        ],
    ),
]

_DATA_PIPELINE_WORKFLOW = Workflow(
    name="data_pipeline",
    agents=[
        AgentInstance(name="extract", component="extractor"),
        AgentInstance(name="validate", component="validator"),
        AgentInstance(name="route", component="data_router"),
        AgentInstance(name="transform", component="transformer"),
        AgentInstance(name="load", component="loader"),
        AgentInstance(name="error_handler", component="error_handler"),
    ],
    connections=[
        Connection(source_agent="extract", target_agents=["validate"]),
        Connection(source_agent="validate", target_agents=["route"]),
        Connection(source_agent="route", target_agents=["transform"], target_ports=["raw_data"]),
        Connection(source_agent="route", target_agents=["error_handler"], target_ports=["issues"]),
        Connection(source_agent="transform", target_agents=["load"]),
    ],
)

# --- chatbot ---
_CHATBOT_COMPONENTS = [
    _make_component(
        "intent_detector",
        system_prompt="识别用户意图: {input}",
        ports=[
            _make_port("message", "input", "string", "用户消息"),
            _make_port("intent", "output", "string", "识别的意图"),
            _make_port("confidence", "output", "number", "置信度"),
        ],
    ),
    _make_component(
        "chat_router",
        system_prompt="根据意图路由",
        ports=[
            _make_port("intent", "input", "string", "用户意图"),
            _make_port("route", "output", "string", "路由结果"),
        ],
    ),
    _make_component(
        "answerer",
        system_prompt="回答用户问题: {input}",
        ports=[
            _make_port("message", "input", "string", "用户消息"),
            _make_port("context", "input", "string", "上下文"),
            _make_port("answer", "output", "string", "回答"),
        ],
    ),
    _make_component(
        "escalator",
        system_prompt="升级到人工客服",
        ports=[
            _make_port("message", "input", "string", "用户消息"),
        ],
    ),
    _make_component(
        "greeter",
        system_prompt="生成问候语: {input}",
        ports=[
            _make_port("message", "input", "string", "用户消息"),
            _make_port("greeting", "output", "string", "问候语"),
        ],
    ),
    _make_component(
        "fallback_handler",
        system_prompt="生成默认回复: {input}",
        ports=[
            _make_port("message", "input", "string", "用户消息"),
            _make_port("response", "output", "string", "默认回复"),
        ],
    ),
]

_CHATBOT_WORKFLOW = Workflow(
    name="chatbot",
    agents=[
        AgentInstance(name="intent", component="intent_detector"),
        AgentInstance(name="route", component="chat_router"),
        AgentInstance(name="answer", component="answerer"),
        AgentInstance(name="escalate", component="escalator"),
        AgentInstance(name="greet", component="greeter"),
        AgentInstance(name="fallback", component="fallback_handler"),
    ],
    connections=[
        Connection(source_agent="intent", target_agents=["route"]),
        Connection(source_agent="route", target_agents=["answer"], target_ports=["message"]),
        Connection(source_agent="route", target_agents=["escalate"], target_ports=["message"]),
        Connection(source_agent="route", target_agents=["greet"], target_ports=["message"]),
        Connection(source_agent="route", target_agents=["fallback"], target_ports=["message"]),
    ],
)


# ==================== 模板注册 ====================

TEMPLATES = {
    "ticket_processing": {
        "name": "ticket_processing",
        "description": "工单处理工作流：分类 -> 优先级判断 -> 条件路由",
        "components": _TICKET_COMPONENTS,
        "workflow": _TICKET_WORKFLOW,
    },
    "competitor_analysis": {
        "name": "competitor_analysis",
        "description": "竞品分析工作流：并行搜索 -> 分析 -> 报告",
        "components": _COMPETITOR_COMPONENTS,
        "workflow": _COMPETITOR_WORKFLOW,
    },
    "code_review": {
        "name": "code_review",
        "description": "代码审查工作流：并行审查 -> 汇总 -> 报告",
        "components": _CODE_REVIEW_COMPONENTS,
        "workflow": _CODE_REVIEW_WORKFLOW,
    },
    "data_pipeline": {
        "name": "data_pipeline",
        "description": "数据处理管道：提取 -> 转换 -> 加载",
        "components": _DATA_PIPELINE_COMPONENTS,
        "workflow": _DATA_PIPELINE_WORKFLOW,
    },
    "chatbot": {
        "name": "chatbot",
        "description": "聊天机器人：意图识别 -> 条件路由 -> 响应生成",
        "components": _CHATBOT_COMPONENTS,
        "workflow": _CHATBOT_WORKFLOW,
    },
}


def get_templates() -> List[Dict[str, Any]]:
    """获取所有模板"""
    result = []
    for name, template in TEMPLATES.items():
        result.append({
            "name": name,
            "description": template["description"],
            "agent_count": len(template["workflow"].agents),
        })
    return result


def get_template(name: str) -> Optional[Dict[str, Any]]:
    """获取指定模板"""
    return TEMPLATES.get(name)


def create_from_template(template: Dict[str, Any]):
    """从模板创建工作流

    返回 (workflow, components_dict) 元组：
    - workflow: v2 Workflow 对象
    - components_dict: {name: Component} 字典
    """
    components = template["components"]
    workflow = template["workflow"]
    components_dict = {c.name: c for c in components}
    return workflow, components_dict

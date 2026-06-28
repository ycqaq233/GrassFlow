"""
GrassFlow 工作流模板

提供常用工作流模板，快速创建

使用 v2 类型: Workflow, AgentInstance, Connection, Component
"""

from typing import Dict, Any, List, Optional
from core.models import (
    Workflow, AgentInstance, Connection, Component, Port, ModelConfig
)


# 模板定义
TEMPLATES = {
    "ticket_processing": {
        "name": "ticket_processing",
        "description": "工单处理工作流：分类 -> 优先级判断 -> 条件路由",
        "workflow": {
            "name": "ticket_processing",
            "agents": [
                {
                    "name": "classify",
                    "model": "gpt-4",
                    "system_prompt": "分类工单: {input}",
                    "ports": [
                        {"name": "ticket", "direction": "input", "type": "string"},
                        {"name": "category", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "priority",
                    "model": "gpt-4",
                    "system_prompt": "判断优先级: {input}",
                    "ports": [
                        {"name": "ticket", "direction": "input", "type": "string"},
                        {"name": "priority", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "route",
                    "model": "gpt-4",
                    "system_prompt": "根据分类和优先级决定路由",
                    "ports": [
                        {"name": "category", "direction": "input", "type": "string"},
                        {"name": "priority", "direction": "input", "type": "string"},
                    ],
                    "overrides": {"rules": ["urgent", "normal", "info"]},
                },
                {
                    "name": "human",
                    "model": "gpt-4",
                    "system_prompt": "人工处理工单",
                },
                {
                    "name": "bot",
                    "model": "gpt-4",
                    "system_prompt": "自动回复: {input}",
                    "ports": [
                        {"name": "ticket", "direction": "input", "type": "string"},
                        {"name": "category", "direction": "input", "type": "string"},
                        {"name": "response", "direction": "output", "type": "string"},
                    ],
                },
            ],
            "connections": [
                {"source_agent": "classify", "target_agents": ["route"]},
                {"source_agent": "priority", "target_agents": ["route"]},
                {
                    "source_agent": "route",
                    "target_agents": ["human", "bot"],
                    "routing_rules": {
                        "urgent": ["human"],
                        "normal": ["bot"],
                    },
                },
            ],
        },
    },
    "competitor_analysis": {
        "name": "competitor_analysis",
        "description": "竞品分析工作流：并行搜索 -> 分析 -> 报告",
        "workflow": {
            "name": "competitor_analysis",
            "agents": [
                {
                    "name": "search_a",
                    "model": "gpt-4",
                    "system_prompt": "搜索竞品A的信息: {input}",
                    "ports": [
                        {"name": "company", "direction": "input", "type": "string"},
                        {"name": "info", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "search_b",
                    "model": "gpt-4",
                    "system_prompt": "搜索竞品B的信息: {input}",
                    "ports": [
                        {"name": "company", "direction": "input", "type": "string"},
                        {"name": "info", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "search_c",
                    "model": "gpt-4",
                    "system_prompt": "搜索竞品C的信息: {input}",
                    "ports": [
                        {"name": "company", "direction": "input", "type": "string"},
                        {"name": "info", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "analyze",
                    "model": "gpt-4",
                    "system_prompt": "分析竞品信息并生成报告",
                    "ports": [
                        {"name": "competitor_a", "direction": "input", "type": "object"},
                        {"name": "competitor_b", "direction": "input", "type": "object"},
                        {"name": "competitor_c", "direction": "input", "type": "object"},
                        {"name": "report", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "report",
                    "model": "gpt-4",
                    "system_prompt": "生成最终报告: {input}",
                    "ports": [
                        {"name": "analysis", "direction": "input", "type": "object"},
                        {"name": "final_report", "direction": "output", "type": "string"},
                    ],
                },
            ],
            "connections": [
                {"source_agent": "search_a", "target_agents": ["analyze"]},
                {"source_agent": "search_b", "target_agents": ["analyze"]},
                {"source_agent": "search_c", "target_agents": ["analyze"]},
                {"source_agent": "analyze", "target_agents": ["report"]},
            ],
        },
    },
    "code_review": {
        "name": "code_review",
        "description": "代码审查工作流：并行审查 -> 汇总 -> 报告",
        "workflow": {
            "name": "code_review",
            "agents": [
                {
                    "name": "security_check",
                    "model": "gpt-4",
                    "system_prompt": "检查代码安全性: {input}",
                    "ports": [
                        {"name": "code", "direction": "input", "type": "string"},
                        {"name": "security_issues", "direction": "output", "type": "array"},
                    ],
                },
                {
                    "name": "style_check",
                    "model": "gpt-4",
                    "system_prompt": "检查代码风格: {input}",
                    "ports": [
                        {"name": "code", "direction": "input", "type": "string"},
                        {"name": "style_issues", "direction": "output", "type": "array"},
                    ],
                },
                {
                    "name": "logic_check",
                    "model": "gpt-4",
                    "system_prompt": "检查代码逻辑: {input}",
                    "ports": [
                        {"name": "code", "direction": "input", "type": "string"},
                        {"name": "logic_issues", "direction": "output", "type": "array"},
                    ],
                },
                {
                    "name": "summarize",
                    "model": "gpt-4",
                    "system_prompt": "汇总审查结果: {input}",
                    "ports": [
                        {"name": "security_issues", "direction": "input", "type": "array"},
                        {"name": "style_issues", "direction": "input", "type": "array"},
                        {"name": "logic_issues", "direction": "input", "type": "array"},
                        {"name": "summary", "direction": "output", "type": "string"},
                        {"name": "severity", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "route",
                    "model": "gpt-4",
                    "system_prompt": "根据严重程度路由",
                    "overrides": {"rules": ["critical", "normal", "minor"]},
                },
                {
                    "name": "block_merge",
                    "model": "gpt-4",
                    "system_prompt": "阻止合并，需要人工处理",
                },
                {
                    "name": "approve",
                    "model": "gpt-4",
                    "system_prompt": "批准合并",
                },
            ],
            "connections": [
                {"source_agent": "security_check", "target_agents": ["summarize"]},
                {"source_agent": "style_check", "target_agents": ["summarize"]},
                {"source_agent": "logic_check", "target_agents": ["summarize"]},
                {"source_agent": "summarize", "target_agents": ["route"]},
                {
                    "source_agent": "route",
                    "target_agents": ["block_merge", "approve"],
                    "routing_rules": {
                        "critical": ["block_merge"],
                        "normal": ["approve"],
                    },
                },
            ],
        },
    },
    "data_pipeline": {
        "name": "data_pipeline",
        "description": "数据处理管道：提取 -> 转换 -> 加载",
        "workflow": {
            "name": "data_pipeline",
            "agents": [
                {
                    "name": "extract",
                    "model": "gpt-4",
                    "system_prompt": "从数据源提取数据: {input}",
                    "ports": [
                        {"name": "source", "direction": "input", "type": "string"},
                        {"name": "raw_data", "direction": "output", "type": "object"},
                    ],
                },
                {
                    "name": "validate",
                    "model": "gpt-4",
                    "system_prompt": "验证数据质量: {input}",
                    "ports": [
                        {"name": "raw_data", "direction": "input", "type": "object"},
                        {"name": "is_valid", "direction": "output", "type": "boolean"},
                        {"name": "issues", "direction": "output", "type": "array"},
                    ],
                },
                {
                    "name": "route",
                    "model": "gpt-4",
                    "system_prompt": "根据验证结果路由",
                    "overrides": {"rules": ["valid", "invalid"]},
                },
                {
                    "name": "transform",
                    "model": "gpt-4",
                    "system_prompt": "转换数据格式: {input}",
                    "ports": [
                        {"name": "raw_data", "direction": "input", "type": "object"},
                        {"name": "transformed_data", "direction": "output", "type": "object"},
                    ],
                },
                {
                    "name": "load",
                    "model": "gpt-4",
                    "system_prompt": "加载数据到目标: {input}",
                    "ports": [
                        {"name": "transformed_data", "direction": "input", "type": "object"},
                        {"name": "status", "direction": "output", "type": "string"},
                        {"name": "count", "direction": "output", "type": "number"},
                    ],
                },
                {
                    "name": "error_handler",
                    "model": "gpt-4",
                    "system_prompt": "处理数据错误: {input}",
                    "ports": [
                        {"name": "issues", "direction": "input", "type": "array"},
                        {"name": "error_report", "direction": "output", "type": "string"},
                    ],
                },
            ],
            "connections": [
                {"source_agent": "extract", "target_agents": ["validate"]},
                {"source_agent": "validate", "target_agents": ["route"]},
                {
                    "source_agent": "route",
                    "target_agents": ["transform", "error_handler"],
                    "routing_rules": {
                        "valid": ["transform"],
                        "invalid": ["error_handler"],
                    },
                },
                {"source_agent": "transform", "target_agents": ["load"]},
            ],
        },
    },
    "chatbot": {
        "name": "chatbot",
        "description": "聊天机器人：意图识别 -> 条件路由 -> 响应生成",
        "workflow": {
            "name": "chatbot",
            "agents": [
                {
                    "name": "intent",
                    "model": "gpt-4",
                    "system_prompt": "识别用户意图: {input}",
                    "ports": [
                        {"name": "message", "direction": "input", "type": "string"},
                        {"name": "intent", "direction": "output", "type": "string"},
                        {"name": "confidence", "direction": "output", "type": "number"},
                    ],
                },
                {
                    "name": "route",
                    "model": "gpt-4",
                    "system_prompt": "根据意图路由",
                    "overrides": {"rules": ["question", "complaint", "greeting", "other"]},
                },
                {
                    "name": "answer",
                    "model": "gpt-4",
                    "system_prompt": "回答用户问题: {input}",
                    "ports": [
                        {"name": "message", "direction": "input", "type": "string"},
                        {"name": "context", "direction": "input", "type": "string"},
                        {"name": "answer", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "escalate",
                    "model": "gpt-4",
                    "system_prompt": "升级到人工客服",
                },
                {
                    "name": "greet",
                    "model": "gpt-4",
                    "system_prompt": "生成问候语: {input}",
                    "ports": [
                        {"name": "message", "direction": "input", "type": "string"},
                        {"name": "greeting", "direction": "output", "type": "string"},
                    ],
                },
                {
                    "name": "fallback",
                    "model": "gpt-4",
                    "system_prompt": "生成默认回复: {input}",
                    "ports": [
                        {"name": "message", "direction": "input", "type": "string"},
                        {"name": "response", "direction": "output", "type": "string"},
                    ],
                },
            ],
            "connections": [
                {"source_agent": "intent", "target_agents": ["route"]},
                {
                    "source_agent": "route",
                    "target_agents": ["answer", "escalate", "greet", "fallback"],
                    "routing_rules": {
                        "question": ["answer"],
                        "complaint": ["escalate"],
                        "greeting": ["greet"],
                        "other": ["fallback"],
                    },
                },
            ],
        },
    },
}


def _parse_ports(port_list: List[Dict[str, str]]) -> List[Port]:
    """将端口字典列表转换为 Port 对象列表"""
    return [Port(**p) for p in port_list]


def get_templates() -> List[Dict[str, Any]]:
    """获取所有模板"""
    result = []
    for name, template in TEMPLATES.items():
        result.append({
            "name": name,
            "description": template["description"],
            "agent_count": len(template["workflow"]["agents"]),
        })
    return result


def get_template(name: str) -> Optional[Dict[str, Any]]:
    """获取指定模板"""
    return TEMPLATES.get(name)


def create_from_template(template: Dict[str, Any]) -> Workflow:
    """从模板创建工作流 (v2)"""
    workflow_data = template["workflow"]

    agents = []
    for agent_data in workflow_data["agents"]:
        overrides = agent_data.get("overrides", {})
        if "model" in agent_data:
            overrides["model"] = agent_data["model"]

        agent = AgentInstance(
            name=agent_data["name"],
            overrides=overrides,
            inline_ports=_parse_ports(agent_data.get("ports", [])),
            inline_system_prompt=agent_data.get("system_prompt"),
        )
        agents.append(agent)

    connections = []
    for conn_data in workflow_data.get("connections", []):
        conn = Connection(
            source_agent=conn_data["source_agent"],
            target_agents=conn_data.get("target_agents", []),
            target_ports=conn_data.get("target_ports", []),
            routing_rules=conn_data.get("routing_rules", {}),
        )
        connections.append(conn)

    return Workflow(
        name=workflow_data["name"],
        agents=agents,
        connections=connections,
    )

"""
GrassFlow 工作流模板

提供常用工作流模板，快速创建
"""

from typing import Dict, Any, List, Optional
from core.models import Workflow, AgentConfig, Edge, AgentType, InteractionType


# 模板定义
TEMPLATES = {
    "ticket_processing": {
        "name": "ticket_processing",
        "description": "工单处理工作流：分类 -> 优先级判断 -> 条件路由",
        "workflow": {
            "name": "ticket_processing",
            "description": "工单处理工作流",
            "agents": [
                {
                    "name": "classify",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "分类工单: {input}",
                    "input_schema": {"ticket": "string"},
                    "output_schema": {"category": "string"},
                },
                {
                    "name": "priority",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "判断优先级: {input}",
                    "input_schema": {"ticket": "string"},
                    "output_schema": {"priority": "string"},
                },
                {
                    "name": "route",
                    "type": "condition",
                    "rules": ["urgent", "normal", "info"],
                },
                {
                    "name": "human",
                    "type": "manual",
                    "prompt": "人工处理工单",
                },
                {
                    "name": "bot",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "自动回复: {input}",
                    "input_schema": {"ticket": "string", "category": "string"},
                    "output_schema": {"response": "string"},
                },
            ],
            "edges": [
                {"source": "classify", "target": "route", "interaction_type": "sequence"},
                {"source": "priority", "target": "route", "interaction_type": "sequence"},
                {"source": "route", "target": "human", "interaction_type": "condition", "condition": "urgent"},
                {"source": "route", "target": "bot", "interaction_type": "condition", "condition": "normal"},
            ],
        },
    },
    "competitor_analysis": {
        "name": "competitor_analysis",
        "description": "竞品分析工作流：并行搜索 -> 分析 -> 报告",
        "workflow": {
            "name": "competitor_analysis",
            "description": "竞品分析工作流",
            "agents": [
                {
                    "name": "search_a",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "搜索竞品A的信息: {input}",
                    "input_schema": {"company": "string"},
                    "output_schema": {"info": "string"},
                },
                {
                    "name": "search_b",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "搜索竞品B的信息: {input}",
                    "input_schema": {"company": "string"},
                    "output_schema": {"info": "string"},
                },
                {
                    "name": "search_c",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "搜索竞品C的信息: {input}",
                    "input_schema": {"company": "string"},
                    "output_schema": {"info": "string"},
                },
                {
                    "name": "analyze",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "分析竞品信息并生成报告",
                    "input_schema": {"competitor_a": "object", "competitor_b": "object", "competitor_c": "object"},
                    "output_schema": {"report": "string"},
                },
                {
                    "name": "report",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "生成最终报告: {input}",
                    "input_schema": {"analysis": "object"},
                    "output_schema": {"final_report": "string"},
                },
            ],
            "edges": [
                {"source": "search_a", "target": "analyze", "interaction_type": "parallel"},
                {"source": "search_b", "target": "analyze", "interaction_type": "parallel"},
                {"source": "search_c", "target": "analyze", "interaction_type": "parallel"},
                {"source": "analyze", "target": "report", "interaction_type": "sequence"},
            ],
        },
    },
    "code_review": {
        "name": "code_review",
        "description": "代码审查工作流：并行审查 -> 汇总 -> 报告",
        "workflow": {
            "name": "code_review",
            "description": "代码审查工作流",
            "agents": [
                {
                    "name": "security_check",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "检查代码安全性: {input}",
                    "input_schema": {"code": "string"},
                    "output_schema": {"security_issues": "array"},
                },
                {
                    "name": "style_check",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "检查代码风格: {input}",
                    "input_schema": {"code": "string"},
                    "output_schema": {"style_issues": "array"},
                },
                {
                    "name": "logic_check",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "检查代码逻辑: {input}",
                    "input_schema": {"code": "string"},
                    "output_schema": {"logic_issues": "array"},
                },
                {
                    "name": "summarize",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "汇总审查结果: {input}",
                    "input_schema": {"security_issues": "array", "style_issues": "array", "logic_issues": "array"},
                    "output_schema": {"summary": "string", "severity": "string"},
                },
                {
                    "name": "route",
                    "type": "condition",
                    "rules": ["critical", "normal", "minor"],
                },
                {
                    "name": "block_merge",
                    "type": "manual",
                    "prompt": "阻止合并，需要人工处理",
                },
                {
                    "name": "approve",
                    "type": "manual",
                    "prompt": "批准合并",
                },
            ],
            "edges": [
                {"source": "security_check", "target": "summarize", "interaction_type": "parallel"},
                {"source": "style_check", "target": "summarize", "interaction_type": "parallel"},
                {"source": "logic_check", "target": "summarize", "interaction_type": "parallel"},
                {"source": "summarize", "target": "route", "interaction_type": "sequence"},
                {"source": "route", "target": "block_merge", "interaction_type": "condition", "condition": "critical"},
                {"source": "route", "target": "approve", "interaction_type": "condition", "condition": "normal"},
            ],
        },
    },
    "data_pipeline": {
        "name": "data_pipeline",
        "description": "数据处理管道：提取 -> 转换 -> 加载",
        "workflow": {
            "name": "data_pipeline",
            "description": "数据处理管道",
            "agents": [
                {
                    "name": "extract",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "从数据源提取数据: {input}",
                    "input_schema": {"source": "string"},
                    "output_schema": {"raw_data": "object"},
                },
                {
                    "name": "validate",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "验证数据质量: {input}",
                    "input_schema": {"raw_data": "object"},
                    "output_schema": {"is_valid": "boolean", "issues": "array"},
                },
                {
                    "name": "route",
                    "type": "condition",
                    "rules": ["valid", "invalid"],
                },
                {
                    "name": "transform",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "转换数据格式: {input}",
                    "input_schema": {"raw_data": "object"},
                    "output_schema": {"transformed_data": "object"},
                },
                {
                    "name": "load",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "加载数据到目标: {input}",
                    "input_schema": {"transformed_data": "object"},
                    "output_schema": {"status": "string", "count": "integer"},
                },
                {
                    "name": "error_handler",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "处理数据错误: {input}",
                    "input_schema": {"issues": "array"},
                    "output_schema": {"error_report": "string"},
                },
            ],
            "edges": [
                {"source": "extract", "target": "validate", "interaction_type": "sequence"},
                {"source": "validate", "target": "route", "interaction_type": "sequence"},
                {"source": "route", "target": "transform", "interaction_type": "condition", "condition": "valid"},
                {"source": "route", "target": "error_handler", "interaction_type": "condition", "condition": "invalid"},
                {"source": "transform", "target": "load", "interaction_type": "sequence"},
            ],
        },
    },
    "chatbot": {
        "name": "chatbot",
        "description": "聊天机器人：意图识别 -> 条件路由 -> 响应生成",
        "workflow": {
            "name": "chatbot",
            "description": "聊天机器人工作流",
            "agents": [
                {
                    "name": "intent",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "识别用户意图: {input}",
                    "input_schema": {"message": "string"},
                    "output_schema": {"intent": "string", "confidence": "number"},
                },
                {
                    "name": "route",
                    "type": "condition",
                    "rules": ["question", "complaint", "greeting", "other"],
                },
                {
                    "name": "answer",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "回答用户问题: {input}",
                    "input_schema": {"message": "string", "context": "string"},
                    "output_schema": {"answer": "string"},
                },
                {
                    "name": "escalate",
                    "type": "manual",
                    "prompt": "升级到人工客服",
                },
                {
                    "name": "greet",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "生成问候语: {input}",
                    "input_schema": {"message": "string"},
                    "output_schema": {"greeting": "string"},
                },
                {
                    "name": "fallback",
                    "type": "llm",
                    "model": "gpt-4",
                    "prompt": "生成默认回复: {input}",
                    "input_schema": {"message": "string"},
                    "output_schema": {"response": "string"},
                },
            ],
            "edges": [
                {"source": "intent", "target": "route", "interaction_type": "sequence"},
                {"source": "route", "target": "answer", "interaction_type": "condition", "condition": "question"},
                {"source": "route", "target": "escalate", "interaction_type": "condition", "condition": "complaint"},
                {"source": "route", "target": "greet", "interaction_type": "condition", "condition": "greeting"},
                {"source": "route", "target": "fallback", "interaction_type": "condition", "condition": "other"},
            ],
        },
    },
}


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
    """从模板创建工作流"""
    workflow_data = template["workflow"]

    # 创建工作流
    workflow = Workflow(
        name=workflow_data["name"],
        description=workflow_data.get("description", ""),
    )

    # 添加 Agent
    for agent_data in workflow_data["agents"]:
        agent_type = AgentType(agent_data.get("type", "llm"))
        agent_config = AgentConfig(
            name=agent_data["name"],
            type=agent_type,
            model=agent_data.get("model", "gpt-4"),
            prompt=agent_data.get("prompt", ""),
            input_schema=agent_data.get("input_schema", {}),
            output_schema=agent_data.get("output_schema", {}),
        )
        workflow.add_agent(agent_config)

    # 添加边
    for edge_data in workflow_data["edges"]:
        interaction_type = InteractionType(edge_data.get("interaction_type", "sequence"))
        edge = Edge(
            source=edge_data["source"],
            target=edge_data["target"],
            interaction_type=interaction_type,
            condition=edge_data.get("condition"),
        )
        workflow.add_edge(edge)

    return workflow

"""
GrassFlow DSL 解析器

将 .af 文件解析为 Workflow 对象

支持语法：
- workflow name { ... }
- agent name { ... }
- A -> B -> C（顺序）
- (A, B, C) -> D（并行）
- A | B（立即执行）
- route -> [urgent] A, [normal] B（条件分支）
"""

import re
from typing import List, Dict, Any, Optional
from core.models import WorkflowV1 as Workflow, AgentConfig, Edge, AgentType, InteractionType


class DSLError(Exception):
    """DSL 解析错误"""
    pass


class DSLParser:
    """DSL 解析器"""

    def parse(self, dsl: str) -> Workflow:
        """
        解析 DSL 文本

        Args:
            dsl: DSL 文本

        Returns:
            Workflow 对象

        Raises:
            DSLError: 解析错误
        """
        # 预处理：移除注释和多余空白
        dsl = self._preprocess(dsl)

        # 解析 workflow 定义
        workflow_match = re.search(r'workflow\s+(\w+)\s*\{(.+)\}', dsl, re.DOTALL)
        if not workflow_match:
            raise DSLError("Missing workflow definition")

        workflow_name = workflow_match.group(1)
        workflow_body = workflow_match.group(2)

        # 创建工作流
        workflow = Workflow(name=workflow_name)

        # 解析 Agent 声明
        agents = self._parse_agents(workflow_body)
        for agent in agents:
            workflow.add_agent(agent)

        # 解析执行流
        edges = self._parse_flow(workflow_body, workflow)
        for edge in edges:
            workflow.add_edge(edge)

        return workflow

    def _preprocess(self, dsl: str) -> str:
        """
        预处理 DSL 文本

        Args:
            dsl: 原始 DSL 文本

        Returns:
            处理后的 DSL 文本
        """
        # 移除单行注释（# 到行尾）
        dsl = re.sub(r'#[^\n]*', '', dsl)

        # 移除行首行尾空白，但保留换行符
        lines = dsl.split('\n')
        lines = [line.strip() for line in lines]
        dsl = '\n'.join(line for line in lines if line)

        return dsl.strip()

    def _parse_agents(self, body: str) -> List[AgentConfig]:
        """
        解析 Agent 声明

        Args:
            body: 工作流体

        Returns:
            Agent 配置列表
        """
        agents = []

        # 匹配 agent name { ... }，支持嵌套大括号
        agent_pattern = re.compile(r'agent\s+(\w+)\s*\{')
        for match in agent_pattern.finditer(body):
            agent_name = match.group(1)
            start_pos = match.end()

            # 找到匹配的右大括号
            brace_count = 1
            pos = start_pos
            while pos < len(body) and brace_count > 0:
                if body[pos] == '{':
                    brace_count += 1
                elif body[pos] == '}':
                    brace_count -= 1
                pos += 1

            if brace_count != 0:
                raise DSLError(f"Unmatched braces in agent '{agent_name}' definition")

            agent_body = body[start_pos:pos-1]

            agent = self._parse_agent_config(agent_name, agent_body)
            agents.append(agent)

        return agents

    def _parse_agent_config(self, name: str, body: str) -> AgentConfig:
        """
        解析单个 Agent 配置

        Args:
            name: Agent 名称
            body: Agent 配置体

        Returns:
            Agent 配置
        """
        config = {"name": name}

        # 解析 type
        type_match = re.search(r'type\s*:\s*"(\w+)"', body)
        if type_match:
            type_str = type_match.group(1)
            try:
                config["type"] = AgentType(type_str)
            except ValueError:
                config["type"] = AgentType.LLM

        # 解析 model
        model_match = re.search(r'model\s*:\s*"([^"]+)"', body)
        if model_match:
            config["model"] = model_match.group(1)

        # 解析 prompt
        prompt_match = re.search(r'prompt\s*:\s*"([^"]+)"', body)
        if prompt_match:
            config["prompt"] = prompt_match.group(1)

        # 解析 input_schema
        input_schema_match = re.search(r'input_schema\s*:\s*\{([^}]+)\}', body)
        if input_schema_match:
            config["input_schema"] = self._parse_schema(input_schema_match.group(1))

        # 解析 output_schema
        output_schema_match = re.search(r'output_schema\s*:\s*\{([^}]+)\}', body)
        if output_schema_match:
            config["output_schema"] = self._parse_schema(output_schema_match.group(1))

        # 解析 on_fail
        on_fail_match = re.search(r'on_fail\s*:\s*"(\w+)"', body)
        if on_fail_match:
            config["on_fail"] = on_fail_match.group(1)

        # 解析 retry_count
        retry_count_match = re.search(r'retry_count\s*:\s*(\d+)', body)
        if retry_count_match:
            config["retry_count"] = int(retry_count_match.group(1))

        # 解析 rules（条件 Agent）
        rules_match = re.search(r'rules\s*:\s*\[([^\]]+)\]', body)
        if rules_match:
            rules_str = rules_match.group(1)
            rules = [r.strip().strip('"') for r in rules_str.split(',')]
            config["rules"] = rules

        return AgentConfig(**config)

    def _parse_schema(self, schema_str: str) -> Dict[str, Any]:
        """
        解析 Schema 字符串

        Args:
            schema_str: Schema 字符串，如 "ticket": "string", "category": "string"

        Returns:
            Schema 字典
        """
        schema = {}
        # 匹配 "key": "value" 或 "key": "value"
        pattern = re.compile(r'"(\w+)":\s*"(\w+)"')
        for match in pattern.finditer(schema_str):
            key = match.group(1)
            value = match.group(2)
            schema[key] = value
        return schema

    def _parse_flow(self, body: str, workflow: Workflow) -> List[Edge]:
        """
        解析执行流

        Args:
            body: 工作流体
            workflow: 工作流对象（用于验证 Agent 存在）

        Returns:
            边列表
        """
        edges = []

        # 移除 agent 声明部分，只保留执行流
        # 使用更精确的匹配，支持嵌套大括号
        flow_body = body
        agent_pattern = re.compile(r'agent\s+\w+\s*\{')
        while True:
            match = agent_pattern.search(flow_body)
            if not match:
                break

            start_pos = match.start()
            brace_count = 1
            pos = match.end()

            while pos < len(flow_body) and brace_count > 0:
                if flow_body[pos] == '{':
                    brace_count += 1
                elif flow_body[pos] == '}':
                    brace_count -= 1
                pos += 1

            # 移除整个 agent 声明
            flow_body = flow_body[:start_pos] + flow_body[pos:]

        flow_body = flow_body.strip()

        # 合并多行执行流
        # 处理类似 "(classify, priority)\n-> route" 的情况
        # 将以 "->" 开头的行与前一行合并
        lines = [line.strip() for line in flow_body.split('\n') if line.strip()]
        merged_lines = []
        for line in lines:
            if line.startswith('->') and merged_lines:
                # 合并到前一行
                merged_lines[-1] = merged_lines[-1] + ' ' + line
            elif line.startswith(',') and merged_lines:
                # 处理条件分支的续行，如 "[urgent] human, [normal] bot"
                merged_lines[-1] = merged_lines[-1] + ' ' + line
            else:
                merged_lines.append(line)

        for line in merged_lines:
            line_edges = self._parse_flow_line(line, workflow)
            edges.extend(line_edges)

        return edges

    def _parse_flow_line(self, line: str, workflow: Workflow) -> List[Edge]:
        """
        解析单行执行流

        Args:
            line: 执行流行
            workflow: 工作流对象

        Returns:
            边列表
        """
        edges = []

        # 检查是否包含条件分支
        if re.search(r'\[\w+\]', line):
            # 找到条件分支的源节点
            # 例如：(classify, priority) -> route -> [urgent] human, [normal] bot
            # 需要找到 [ 前面的最后一个节点作为源节点

            # 找到第一个 [ 的位置
            bracket_pos = line.find('[')
            if bracket_pos == -1:
                return edges

            # 获取 [ 前面的部分
            before_bracket = line[:bracket_pos].strip()

            # 移除末尾的 ->
            if before_bracket.endswith('->'):
                before_bracket = before_bracket[:-2].strip()

            # 解析 [ 前面的部分（可能是并行流或顺序流）
            before_edges = self._parse_flow_line(before_bracket, workflow)
            edges.extend(before_edges)

            # 获取条件分支的源节点（before_bracket 的最后一个节点）
            # 对于 "(classify, priority) -> route"，最后一个节点是 "route"
            source = self._get_last_node(before_bracket)

            # 解析所有条件分支
            condition_pattern = re.compile(r'\[(\w+)\]\s*(\w+)')
            for match in condition_pattern.finditer(line[bracket_pos:]):
                condition = match.group(1)
                target = match.group(2)
                self._validate_agent(source, workflow)
                self._validate_agent(target, workflow)
                edges.append(Edge(
                    source=source,
                    target=target,
                    interaction_type=InteractionType.CONDITION,
                    condition=condition
                ))

            return edges

        # 处理并行流：(A, B, C) -> D 或 (A, B, C) -> D -> E
        parallel_match = re.match(r'\(([^)]+)\)\s*->\s*(.+)', line)
        if parallel_match:
            sources_str = parallel_match.group(1)
            rest = parallel_match.group(2).strip()
            sources = [s.strip() for s in sources_str.split(',')]

            # 解析目标链：可能是 D -> E -> F 的形式
            targets = [t.strip() for t in rest.split('->')]

            # 第一个目标接收并行边
            first_target = targets[0]
            self._validate_agent(first_target, workflow)
            for source in sources:
                self._validate_agent(source, workflow)
                edges.append(Edge(
                    source=source,
                    target=first_target,
                    interaction_type=InteractionType.PARALLEL
                ))

            # 后续目标接收顺序边
            for i in range(len(targets) - 1):
                source = targets[i]
                target = targets[i + 1]
                self._validate_agent(source, workflow)
                self._validate_agent(target, workflow)
                edges.append(Edge(
                    source=source,
                    target=target,
                    interaction_type=InteractionType.SEQUENCE
                ))

            return edges

        # 处理立即执行：A | B
        immediate_match = re.search(r'(\w+)\s*\|\s*(\w+)', line)
        if immediate_match:
            source = immediate_match.group(1)
            target = immediate_match.group(2)
            self._validate_agent(source, workflow)
            self._validate_agent(target, workflow)
            edges.append(Edge(
                source=source,
                target=target,
                interaction_type=InteractionType.IMMEDIATE
            ))
            return edges

        # 处理顺序流：A -> B -> C
        if '->' in line:
            nodes = [n.strip() for n in line.split('->')]

            for i in range(len(nodes) - 1):
                source = nodes[i]
                target = nodes[i + 1]
                self._validate_agent(source, workflow)
                self._validate_agent(target, workflow)
                edges.append(Edge(
                    source=source,
                    target=target,
                    interaction_type=InteractionType.SEQUENCE
                ))
            return edges

        return edges

    def _get_last_node(self, expr: str) -> str:
        """
        获取表达式的最后一个节点

        Args:
            expr: 表达式，如 "(A, B) -> C" 或 "A -> B -> C"

        Returns:
            最后一个节点的名称
        """
        # 移除括号和空格
        expr = expr.strip()

        # 如果是并行流，提取目标
        parallel_match = re.match(r'\(([^)]+)\)\s*->\s*(.+)', expr)
        if parallel_match:
            rest = parallel_match.group(2).strip()
            # 获取最后一个节点
            nodes = [n.strip() for n in rest.split('->')]
            return nodes[-1]

        # 如果是顺序流，获取最后一个节点
        if '->' in expr:
            nodes = [n.strip() for n in expr.split('->')]
            return nodes[-1]

        # 否则返回整个表达式
        return expr

    def _validate_agent(self, name: str, workflow: Workflow) -> None:
        """
        验证 Agent 是否存在

        Args:
            name: Agent 名称
            workflow: 工作流对象

        Raises:
            DSLError: Agent 不存在
        """
        if not workflow.get_agent(name):
            raise DSLError(f"Agent '{name}' not defined")


def parse_dsl(dsl: str) -> Workflow:
    """
    解析 DSL 文本的便捷函数

    Args:
        dsl: DSL 文本

    Returns:
        Workflow 对象
    """
    parser = DSLParser()
    return parser.parse(dsl)


def parse_file(file_path: str) -> Workflow:
    """
    解析 DSL 文件

    Args:
        file_path: 文件路径

    Returns:
        Workflow 对象
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        dsl = f.read()
    return parse_dsl(dsl)

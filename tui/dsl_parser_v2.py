"""
GrassFlow DSL v2 解析器

将 .gf 文件解析为 AST (抽象语法树)

支持语法：
- component name { ... }
- workflow name { ... }
- port input/output name: type "description"
- model default/fallback/temperature/max_tokens: value
- mcp server { tools: [...] }
- permission allow/deny/ask: [...]
- agent name { ... } / agent name use component
- A -> B / A.x -> B.y / A -> (B, C) / (A, B) -> C
"""

import re
from typing import List, Optional, Tuple
from core.models import (
    Port, MCPConfig, PermissionConfig, ModelConfig,
    Component, AgentInstance, Connection, Workflow, ParseResult
)


class DSLError(Exception):
    """DSL 解析错误"""
    pass


class DSLv2Parser:
    """DSL v2 解析器"""

    def parse(self, dsl: str) -> ParseResult:
        """
        解析 DSL 文本

        Args:
            dsl: DSL 文本

        Returns:
            ParseResult 对象

        Raises:
            DSLError: 解析错误
        """
        result = ParseResult()

        # 预处理：移除注释和多余空白
        dsl = self._preprocess(dsl)

        # 解析 component 定义
        result.components = self._parse_components(dsl)

        # 解析 workflow 定义
        result.workflows = self._parse_workflows(dsl)

        return result

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
        lines = [line.strip() for line in dsl.split('\n')]
        dsl = '\n'.join(line for line in lines if line)

        return dsl

    def _parse_components(self, dsl: str) -> List[Component]:
        """
        解析所有 component 定义

        Args:
            dsl: 预处理后的 DSL 文本

        Returns:
            Component 列表
        """
        components = []

        # 匹配 component name {
        pattern = r'component\s+(\w[\w-]*)\s*\{'
        for match in re.finditer(pattern, dsl):
            name = match.group(1)
            start = match.end()
            body = self._extract_block(dsl, start)
            if body:
                comp = self._parse_component_body(name, body)
                components.append(comp)

        return components

    def _parse_component_body(self, name: str, body: str) -> Component:
        """
        解析 component 内容

        Args:
            name: 组件名称
            body: 组件内容

        Returns:
            Component 对象
        """
        comp = Component(name=name)

        # 解析 description
        desc_match = re.search(r'description:\s*"([^"]*)"', body)
        if desc_match:
            comp.description = desc_match.group(1)

        # 解析 version
        ver_match = re.search(r'version:\s*"([^"]*)"', body)
        if ver_match:
            comp.version = ver_match.group(1)

        # 解析 system_prompt / prompt（支持多行格式）
        prompt_text = self._extract_prompt_field(body)
        if prompt_text:
            comp.system_prompt = prompt_text

        # 解析 port
        port_pattern = r'port\s+(input|output)\s+(\w[\w-]*):\s*(\w+)\s*(?:"([^"]*)")?'
        for port_match in re.finditer(port_pattern, body):
            port = Port(
                name=port_match.group(2),
                direction=port_match.group(1),
                type=port_match.group(3),
                description=port_match.group(4)
            )
            comp.ports.append(port)

        # 解析 model
        model_default = re.search(r'model\s+default:\s*"([^"]*)"', body)
        model_fallback = re.search(r'model\s+fallback:\s*"([^"]*)"', body)
        model_temp = re.search(r'model\s+temperature:\s*([\d.]+)', body)
        model_tokens = re.search(r'model\s+max_tokens:\s*(\d+)', body)

        if model_default:
            comp.model.default = model_default.group(1)
        if model_fallback:
            comp.model.fallback = model_fallback.group(1)
        if model_temp:
            comp.model.temperature = float(model_temp.group(1))
        if model_tokens:
            comp.model.max_tokens = int(model_tokens.group(1))

        # 解析 max_tool_iterations
        mti_match = re.search(r'max_tool_iterations:\s*(\d+)', body)
        if mti_match:
            comp.max_tool_iterations = int(mti_match.group(1))

        # 解析 mcp
        mcp_pattern = r'mcp\s+(\w[\w-]*)\s*\{[^}]*tools:\s*\[([^\]]*)\][^}]*\}'
        for mcp_match in re.finditer(mcp_pattern, body, re.DOTALL):
            tools = [t.strip() for t in mcp_match.group(2).split(',')]
            mcp = MCPConfig(
                server_name=mcp_match.group(1),
                tools=tools
            )
            comp.mcp.append(mcp)

        # 解析 permission
        perm_allow = re.search(r'permission\s+allow:\s*\[([^\]]*)\]', body)
        perm_deny = re.search(r'permission\s+deny:\s*\[([^\]]*)\]', body)
        perm_ask = re.search(r'permission\s+ask:\s*\[([^\]]*)\]', body)

        if perm_allow:
            comp.permission.allow = [t.strip() for t in perm_allow.group(1).split(',')]
        if perm_deny:
            comp.permission.deny = [t.strip() for t in perm_deny.group(1).split(',')]
        if perm_ask:
            comp.permission.ask = [t.strip() for t in perm_ask.group(1).split(',')]

        # 解析 mode
        mode_match = re.search(r'mode:\s*"?(batch|stream)"?', body)
        if mode_match:
            comp.mode = mode_match.group(1)

        # 解析 context
        ctx_match = re.search(r'context:\s*"?(shared|independent)"?', body)
        if ctx_match:
            comp.context = ctx_match.group(1)

        # 解析 on_fail
        fail_match = re.search(r'on_fail:\s*"?(stop|skip|retry)"?', body)
        if fail_match:
            comp.on_fail = fail_match.group(1)

        # 解析 retry_count
        retry_match = re.search(r'retry_count:\s*(\d+)', body)
        if retry_match:
            comp.retry_count = int(retry_match.group(1))

        return comp

    def _parse_workflows(self, dsl: str) -> List[Workflow]:
        """
        解析所有 workflow 定义

        Args:
            dsl: 预处理后的 DSL 文本

        Returns:
            Workflow 列表
        """
        workflows = []

        # 匹配 workflow name {
        pattern = r'workflow\s+(\w[\w-]*)\s*\{'
        for match in re.finditer(pattern, dsl):
            name = match.group(1)
            start = match.end()
            body = self._extract_block(dsl, start)
            if body:
                wf = self._parse_workflow_body(name, body)
                workflows.append(wf)

        return workflows

    def _parse_workflow_body(self, name: str, body: str) -> Workflow:
        """
        解析 workflow 内容

        Args:
            name: 工作流名称
            body: 工作流内容

        Returns:
            Workflow 对象
        """
        wf = Workflow(name=name)

        # 解析 port
        port_pattern = r'port\s+(input|output)\s+(\w[\w-]*):\s*(\w+)\s*(?:"([^"]*)")?'
        for port_match in re.finditer(port_pattern, body):
            port = Port(
                name=port_match.group(2),
                direction=port_match.group(1),
                type=port_match.group(3),
                description=port_match.group(4)
            )
            wf.ports.append(port)

        # 解析所有 agent（保持顺序）
        # 先收集所有 agent 声明的位置
        agent_declarations = []

        # 匹配内联 agent：agent name {
        inline_pattern = r'agent\s+(\w[\w-]*)\s*\{'
        for match in re.finditer(inline_pattern, body):
            agent_declarations.append({
                'pos': match.start(),
                'name': match.group(1),
                'type': 'inline',
                'match': match
            })

        # 匹配 use agent：agent name use component
        use_pattern = r'agent\s+(\w[\w-]*)\s+use\s+(\w[\w-]*)'
        for match in re.finditer(use_pattern, body):
            agent_declarations.append({
                'pos': match.start(),
                'name': match.group(1),
                'type': 'use',
                'component': match.group(2),
                'match': match
            })

        # 按位置排序
        agent_declarations.sort(key=lambda x: x['pos'])

        # 按顺序解析
        for decl in agent_declarations:
            if decl['type'] == 'use':
                agent = AgentInstance(
                    name=decl['name'],
                    component=decl['component']
                )
                wf.agents.append(agent)
            else:  # inline
                # 找到匹配的右花括号
                start = decl['match'].end()
                agent_body = self._extract_block(body, start)
                if agent_body:
                    agent = self._parse_inline_agent(decl['name'], agent_body)
                    wf.agents.append(agent)

        # 解析连接
        wf.connections = self._parse_connections(body, wf.agents)

        return wf

    def _extract_block(self, text: str, start: int) -> Optional[str]:
        """
        提取匹配的花括号块

        Args:
            text: 文本
            start: 左花括号后的位置

        Returns:
            花括号内的内容，或 None
        """
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
            i += 1

        if depth == 0:
            return text[start:i-1]
        return None

    def _parse_inline_agent(self, name: str, body: str) -> AgentInstance:
        """
        解析内联 agent 定义

        Args:
            name: Agent 名称
            body: Agent 内容

        Returns:
            AgentInstance 对象
        """
        agent = AgentInstance(name=name)

        # 解析 model
        model_match = re.search(r'model:\s*"([^"]*)"', body)
        if model_match:
            agent.overrides["model"] = model_match.group(1)

        # 解析 prompt / system_prompt（支持多种格式）
        prompt_text = self._extract_prompt_field(body)
        if prompt_text:
            agent.inline_system_prompt = prompt_text

        # 解析 port
        port_pattern = r'port\s+(input|output)\s+(\w[\w-]*):\s*(\w+)\s*(?:"([^"]*)")?'
        for port_match in re.finditer(port_pattern, body):
            port = Port(
                name=port_match.group(2),
                direction=port_match.group(1),
                type=port_match.group(3),
                description=port_match.group(4)
            )
            agent.inline_ports.append(port)

        return agent

    def _extract_prompt_field(self, body: str) -> Optional[str]:
        """从 agent/component body 中提取 prompt 或 system_prompt 字段。

        支持以下格式：
        1. system_prompt: "..."        — 单行双引号
        2. system_prompt: |-           — YAML 多行块（literal block）
           多行内容
        3. system_prompt: triple-quoted — 三引号多行
        4. prompt: "..." / prompt: |-  — 同上，prompt 作为别名
        """
        # 优先级: system_prompt > prompt
        for field_name in ("system_prompt", "prompt"):
            # 1. 三引号多行
            m = re.search(rf'{field_name}:\s*"""(.*?)"""', body, re.DOTALL)
            if m:
                return m.group(1).strip()

            # 2. YAML 多行块 (|- 或 |)
            m = re.search(rf'{field_name}:\s*\|(-?)\s*\n', body)
            if m:
                # 找到块开始位置，提取后续缩进行
                block_start = m.end()
                lines = body[block_start:].split('\n')
                # 确定缩进级别（第一行非空行的缩进）
                indent = None
                collected = []
                for line in lines:
                    stripped = line.rstrip()
                    if not stripped:
                        # 空行：如果还没确定缩进则跳过，否则保留
                        if indent is not None:
                            collected.append("")
                        continue
                    current_indent = len(line) - len(line.lstrip())
                    if indent is None:
                        indent = current_indent
                    # 块结束条件：缩进严格小于块缩进，或缩进为0且是DSL关键字
                    if current_indent < indent:
                        break
                    if current_indent == 0 and re.match(
                        r'(permission|model|port|agent|\}|[a-z_]+\s*:)', stripped
                    ):
                        break
                    collected.append(line[indent:] if indent else line)
                # 去除尾部空行
                while collected and not collected[-1].strip():
                    collected.pop()
                result = "\n".join(collected).rstrip()
                if result:
                    return result

            # 3. 单行双引号
            m = re.search(rf'{field_name}:\s*"([^"]*)"', body)
            if m:
                return m.group(1)

        return None

    def _parse_connections(self, body: str, agents: List[AgentInstance]) -> List[Connection]:
        """
        解析连接

        Args:
            body: 工作流内容
            agents: Agent 列表

        Returns:
            Connection 列表
        """
        connections = []

        # 获取所有 agent 名称
        agent_names = {a.name for a in agents}

        # 匹配连接语法
        # 1. A -> B
        # 2. A.x -> B.y
        # 3. A -> (B, C, D)
        # 4. (A, B, C) -> D

        # 移除 agent 定义块，只保留连接语句
        clean_body = re.sub(r'agent\s+\w[\w-]*\s*(?:use\s+\w[\w-]*)?\s*\{[^}]*\}', '', body, flags=re.DOTALL)
        clean_body = re.sub(r'port\s+(input|output)\s+\w[\w-]*:\s*\w+', '', clean_body)

        # 匹配所有连接行
        lines = [line.strip() for line in clean_body.split('\n') if line.strip() and '->' in line]

        for line in lines:
            conn = self._parse_connection_line(line)
            if conn:
                connections.append(conn)

        return connections

    def _parse_connection_line(self, line: str) -> Optional[Connection]:
        """
        解析单行连接

        Args:
            line: 连接语句

        Returns:
            Connection 对象或 None
        """
        # 移除尾部逗号
        line = line.rstrip(',')

        # 分割左右两边
        parts = line.split('->')
        if len(parts) != 2:
            return None

        left = parts[0].strip()
        right = parts[1].strip()

        # 解析左边（源）
        source_agent, source_port = self._parse_source(left)

        # 解析右边（目标）
        target_agents, target_ports = self._parse_target(right)

        return Connection(
            source_agent=source_agent,
            source_port=source_port,
            target_agents=target_agents,
            target_ports=target_ports
        )

    def _parse_source(self, left: str) -> Tuple[str, Optional[str]]:
        """
        解析连接源

        Args:
            left: 左边部分

        Returns:
            (source_agent, source_port)
        """
        # 检查是否是聚合 (A, B, C)
        if left.startswith('(') and left.endswith(')'):
            # 聚合连接，返回特殊标记
            return "__aggregate__", None

        # 检查是否有显式端口 A.x
        if '.' in left:
            parts = left.split('.')
            return parts[0], parts[1]

        # 默认端口
        return left, None

    def _parse_target(self, right: str) -> Tuple[List[str], List[str]]:
        """
        解析连接目标

        Args:
            right: 右边部分

        Returns:
            (target_agents, target_ports)
        """
        # 检查是否是广播 (A, B, C)
        if right.startswith('(') and right.endswith(')'):
            # 广播连接
            inner = right[1:-1]
            targets = [t.strip() for t in inner.split(',')]
            return targets, []

        # 检查是否有显式端口 A.x
        if '.' in right:
            parts = right.split('.')
            return [parts[0]], [parts[1]]

        # 默认端口
        return [right], []

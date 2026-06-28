"""
GrassFlow DSL v2 解析器测试

测试 DSL v2 语法的解析功能
"""

import pytest
try:
    from core.models import Component, Workflow, AgentInstance, Connection, Port, ModelConfig, MCPConfig, PermissionConfig, ParseResult
except ImportError:
    from core.models import Component, Workflow, AgentInstance, Connection, Port, ModelConfig, MCPConfig, PermissionConfig, ParseResult
from tui.dsl_parser_v2 import DSLv2Parser


class TestSlice1_ASTDataStructures:
    """Slice 1: 测试 AST 数据结构"""

    def test_port_creation(self):
        """Port 可以正确创建"""
        port = Port(
            name="code",
            direction="input",
            type="string",
            description="待审查的代码"
        )
        assert port.name == "code"
        assert port.direction == "input"
        assert port.type == "string"
        assert port.description == "待审查的代码"
        assert port.sync is True  # 默认同步

    def test_port_async(self):
        """Port 可以声明为异步"""
        port = Port(
            name="trigger",
            direction="input",
            type="string",
            sync=False
        )
        assert port.sync is False

    def test_mcp_config_creation(self):
        """MCPConfig 可以正确创建"""
        mcp = MCPConfig(
            server_name="github",
            tools=["create_issue", "add_comment"]
        )
        assert mcp.server_name == "github"
        assert mcp.tools == ["create_issue", "add_comment"]

    def test_permission_config_creation(self):
        """PermissionConfig 可以正确创建"""
        perm = PermissionConfig(
            allow=["github.add_comment"],
            deny=["github.delete_repo"],
            ask=["github.merge_pr"]
        )
        assert perm.allow == ["github.add_comment"]
        assert perm.deny == ["github.delete_repo"]
        assert perm.ask == ["github.merge_pr"]

    def test_permission_config_defaults(self):
        """PermissionConfig 默认值为空列表"""
        perm = PermissionConfig()
        assert perm.allow == []
        assert perm.deny == []
        assert perm.ask == []

    def test_model_config_creation(self):
        """ModelConfig 可以正确创建"""
        model = ModelConfig(
            default="gpt-4",
            fallback="gpt-3.5-turbo",
            temperature=0.3,
            max_tokens=4096
        )
        assert model.default == "gpt-4"
        assert model.fallback == "gpt-3.5-turbo"
        assert model.temperature == 0.3
        assert model.max_tokens == 4096

    def test_model_config_defaults(self):
        """ModelConfig 默认值为 None"""
        model = ModelConfig()
        assert model.default is None
        assert model.fallback is None
        assert model.temperature is None
        assert model.max_tokens is None

    def test_component_creation(self):
        """Component 可以正确创建"""
        comp = Component(
            name="code-reviewer",
            description="代码审查专家",
            version="1.0.0"
        )
        assert comp.name == "code-reviewer"
        assert comp.description == "代码审查专家"
        assert comp.version == "1.0.0"
        assert comp.ports == []
        assert comp.mcp == []
        assert comp.mode == "batch"
        assert comp.context == "shared"
        assert comp.on_fail == "stop"
        assert comp.retry_count == 3

    def test_component_with_ports(self):
        """Component 可以包含端口"""
        port1 = Port(name="code", direction="input", type="string")
        port2 = Port(name="issues", direction="output", type="array")
        comp = Component(
            name="reviewer",
            ports=[port1, port2]
        )
        assert len(comp.ports) == 2
        assert comp.ports[0].name == "code"
        assert comp.ports[1].name == "issues"

    def test_agent_instance_creation(self):
        """AgentInstance 可以正确创建"""
        agent = AgentInstance(name="analyzer")
        assert agent.name == "analyzer"
        assert agent.component is None
        assert agent.overrides == {}
        assert agent.inline_ports == []
        assert agent.inline_system_prompt is None

    def test_agent_instance_use_component(self):
        """AgentInstance 可以引用组件"""
        agent = AgentInstance(
            name="reviewer",
            component="code-reviewer"
        )
        assert agent.component == "code-reviewer"

    def test_agent_instance_with_overrides(self):
        """AgentInstance 可以有覆盖参数"""
        agent = AgentInstance(
            name="reviewer",
            component="code-reviewer",
            overrides={"model": "gpt-4o", "temperature": 0.5}
        )
        assert agent.overrides["model"] == "gpt-4o"
        assert agent.overrides["temperature"] == 0.5

    def test_connection_creation(self):
        """Connection 可以正确创建"""
        conn = Connection(
            source_agent="a",
            source_port="out",
            target_agents=["b"],
            target_ports=["in"]
        )
        assert conn.source_agent == "a"
        assert conn.source_port == "out"
        assert conn.target_agents == ["b"]
        assert conn.target_ports == ["in"]

    def test_connection_default_ports(self):
        """Connection 默认端口为 None"""
        conn = Connection(
            source_agent="a",
            target_agents=["b"]
        )
        assert conn.source_port is None
        assert conn.target_ports == []

    def test_workflow_creation(self):
        """Workflow 可以正确创建"""
        wf = Workflow(name="my-pipeline")
        assert wf.name == "my-pipeline"
        assert wf.ports == []
        assert wf.agents == []
        assert wf.connections == []
        assert wf.output_mappings == {}

    def test_parse_result_creation(self):
        """ParseResult 可以正确创建"""
        result = ParseResult()
        assert result.components == []
        assert result.workflows == []
        assert result.errors == []


class TestSlice2_ParseComponent:
    """Slice 2: 测试解析 component 基本定义"""

    def test_parse_empty_component(self):
        """解析空的 component 定义"""
        dsl = '''
        component code-reviewer {
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        assert len(result.components) == 1
        assert result.components[0].name == "code-reviewer"

    def test_parse_component_with_description(self):
        """解析带 description 的 component"""
        dsl = '''
        component code-reviewer {
            description: "代码审查专家"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        comp = result.components[0]
        assert comp.description == "代码审查专家"

    def test_parse_component_with_version(self):
        """解析带 version 的 component"""
        dsl = '''
        component code-reviewer {
            version: "1.0.0"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        comp = result.components[0]
        assert comp.version == "1.0.0"

    def test_parse_component_with_metadata(self):
        """解析带完整元信息的 component"""
        dsl = '''
        component code-reviewer {
            description: "代码审查专家"
            version: "1.0.0"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        comp = result.components[0]
        assert comp.name == "code-reviewer"
        assert comp.description == "代码审查专家"
        assert comp.version == "1.0.0"

    def test_parse_multiple_components(self):
        """解析多个 component 定义"""
        dsl = '''
        component code-reviewer {
            description: "代码审查专家"
        }

        component issue-creator {
            description: "Issue 创建器"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        assert len(result.components) == 2
        assert result.components[0].name == "code-reviewer"
        assert result.components[1].name == "issue-creator"


class TestSlice3_ParsePort:
    """Slice 3: 测试解析 port 定义"""

    def test_parse_input_port(self):
        """解析输入端口"""
        dsl = '''
        component code-reviewer {
            port input code: string "待审查的代码"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        port = result.components[0].ports[0]
        assert port.name == "code"
        assert port.direction == "input"
        assert port.type == "string"
        assert port.description == "待审查的代码"

    def test_parse_output_port(self):
        """解析输出端口"""
        dsl = '''
        component code-reviewer {
            port output issues: array "问题列表"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        port = result.components[0].ports[0]
        assert port.name == "issues"
        assert port.direction == "output"
        assert port.type == "array"
        assert port.description == "问题列表"

    def test_parse_port_without_description(self):
        """解析不带描述的端口"""
        dsl = '''
        component code-reviewer {
            port input code: string
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        port = result.components[0].ports[0]
        assert port.name == "code"
        assert port.direction == "input"
        assert port.type == "string"
        assert port.description is None

    def test_parse_multiple_ports(self):
        """解析多个端口"""
        dsl = '''
        component code-reviewer {
            port input code: string
            port input context: object
            port output issues: array
            port output score: number
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        ports = result.components[0].ports
        assert len(ports) == 4
        assert ports[0].name == "code"
        assert ports[0].direction == "input"
        assert ports[1].name == "context"
        assert ports[1].direction == "input"
        assert ports[2].name == "issues"
        assert ports[2].direction == "output"
        assert ports[3].name == "score"
        assert ports[3].direction == "output"

    def test_parse_all_port_types(self):
        """解析所有端口类型"""
        dsl = '''
        component data-processor {
            port input text: string
            port input count: number
            port input enabled: boolean
            port input config: object
            port input items: array
            port output result: string
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        ports = result.components[0].ports
        assert len(ports) == 6
        assert ports[0].type == "string"
        assert ports[1].type == "number"
        assert ports[2].type == "boolean"
        assert ports[3].type == "object"
        assert ports[4].type == "array"
        assert ports[5].type == "string"


class TestSlice4_ParseModel:
    """Slice 4: 测试解析 model 配置"""

    def test_parse_model_default(self):
        """解析 model default"""
        dsl = '''
        component code-reviewer {
            model default: "gpt-4"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        model = result.components[0].model
        assert model.default == "gpt-4"

    def test_parse_model_fallback(self):
        """解析 model fallback"""
        dsl = '''
        component code-reviewer {
            model fallback: "gpt-3.5-turbo"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        model = result.components[0].model
        assert model.fallback == "gpt-3.5-turbo"

    def test_parse_model_temperature(self):
        """解析 model temperature"""
        dsl = '''
        component code-reviewer {
            model temperature: 0.3
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        model = result.components[0].model
        assert model.temperature == 0.3

    def test_parse_model_max_tokens(self):
        """解析 model max_tokens"""
        dsl = '''
        component code-reviewer {
            model max_tokens: 4096
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        model = result.components[0].model
        assert model.max_tokens == 4096

    def test_parse_model_all(self):
        """解析完整 model 配置"""
        dsl = '''
        component code-reviewer {
            model default: "gpt-4"
            model fallback: "gpt-3.5-turbo"
            model temperature: 0.3
            model max_tokens: 4096
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        model = result.components[0].model
        assert model.default == "gpt-4"
        assert model.fallback == "gpt-3.5-turbo"
        assert model.temperature == 0.3
        assert model.max_tokens == 4096


class TestSlice5_ParseSystemPrompt:
    """Slice 5: 测试解析 system_prompt"""

    def test_parse_system_prompt(self):
        """解析单行 system_prompt"""
        dsl = '''
        component code-reviewer {
            system_prompt: "你是一个代码审查专家"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        assert result.components[0].system_prompt == "你是一个代码审查专家"

    def test_parse_system_prompt_with_template(self):
        """解析带模板变量的 system_prompt"""
        dsl = '''
        component code-reviewer {
            system_prompt: "审查代码: {code}, 上下文: {context}"
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        prompt = result.components[0].system_prompt
        assert "{code}" in prompt
        assert "{context}" in prompt

    def test_parse_multiline_system_prompt(self):
        """解析多行 system_prompt"""
        dsl = '''
        component code-reviewer {
            system_prompt: """
                你是一个专业的代码审查专家。
                审查重点：
                - 代码质量
                - 安全漏洞
            """
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        prompt = result.components[0].system_prompt
        assert "代码审查专家" in prompt
        assert "代码质量" in prompt


class TestSlice6_ParseMCP:
    """Slice 6: 测试解析 MCP 配置"""

    def test_parse_mcp_single_tool(self):
        """解析单个工具的 MCP"""
        dsl = '''
        component code-reviewer {
            mcp github {
                tools: [create_issue]
            }
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        mcp = result.components[0].mcp[0]
        assert mcp.server_name == "github"
        assert mcp.tools == ["create_issue"]

    def test_parse_mcp_multiple_tools(self):
        """解析多个工具的 MCP"""
        dsl = '''
        component code-reviewer {
            mcp github {
                tools: [create_issue, add_comment, list_issues]
            }
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        mcp = result.components[0].mcp[0]
        assert mcp.server_name == "github"
        assert mcp.tools == ["create_issue", "add_comment", "list_issues"]

    def test_parse_multiple_mcp(self):
        """解析多个 MCP 服务器"""
        dsl = '''
        component code-reviewer {
            mcp github {
                tools: [create_issue, add_comment]
            }
            mcp sonarqube {
                tools: [analyze_code, get_metrics]
            }
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        assert len(result.components[0].mcp) == 2
        assert result.components[0].mcp[0].server_name == "github"
        assert result.components[0].mcp[1].server_name == "sonarqube"


class TestSlice7_ParsePermission:
    """Slice 7: 测试解析 permission 配置"""

    def test_parse_permission_allow(self):
        """解析 permission allow"""
        dsl = '''
        component code-reviewer {
            permission allow: [github.add_comment]
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        perm = result.components[0].permission
        assert perm.allow == ["github.add_comment"]

    def test_parse_permission_deny(self):
        """解析 permission deny"""
        dsl = '''
        component code-reviewer {
            permission deny: [github.delete_repo]
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        perm = result.components[0].permission
        assert perm.deny == ["github.delete_repo"]

    def test_parse_permission_ask(self):
        """解析 permission ask"""
        dsl = '''
        component code-reviewer {
            permission ask: [github.merge_pr]
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        perm = result.components[0].permission
        assert perm.ask == ["github.merge_pr"]

    def test_parse_permission_all(self):
        """解析完整 permission 配置"""
        dsl = '''
        component code-reviewer {
            permission allow: [github.add_comment, github.create_issue]
            permission deny: [github.delete_repo]
            permission ask: [github.merge_pr]
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        perm = result.components[0].permission
        assert perm.allow == ["github.add_comment", "github.create_issue"]
        assert perm.deny == ["github.delete_repo"]
        assert perm.ask == ["github.merge_pr"]


class TestSlice8_ParseWorkflow:
    """Slice 8: 测试解析 workflow 基本结构"""

    def test_parse_empty_workflow(self):
        """解析空的 workflow"""
        dsl = '''
        workflow my-pipeline {
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        assert len(result.workflows) == 1
        assert result.workflows[0].name == "my-pipeline"

    def test_parse_workflow_with_port(self):
        """解析带端口的 workflow"""
        dsl = '''
        workflow my-pipeline {
            port input code: string
            port output report: object
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        wf = result.workflows[0]
        assert len(wf.ports) == 2
        assert wf.ports[0].name == "code"
        assert wf.ports[0].direction == "input"
        assert wf.ports[1].name == "report"
        assert wf.ports[1].direction == "output"

    def test_parse_multiple_workflows(self):
        """解析多个 workflow"""
        dsl = '''
        workflow pipeline-1 {
        }

        workflow pipeline-2 {
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        assert len(result.workflows) == 2
        assert result.workflows[0].name == "pipeline-1"
        assert result.workflows[1].name == "pipeline-2"


class TestSlice9_ParseAgent:
    """Slice 9: 测试解析 agent 实例化"""

    def test_parse_inline_agent(self):
        """解析内联 agent 定义"""
        dsl = '''
        workflow my-pipeline {
            agent analyzer {
                model: "gpt-4"
                system_prompt: "分析代码: {code}"
                port input code: string
                port output analysis: object
            }
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        agent = result.workflows[0].agents[0]
        assert agent.name == "analyzer"
        assert agent.component is None
        assert agent.overrides["model"] == "gpt-4"
        assert agent.inline_system_prompt == "分析代码: {code}"
        assert len(agent.inline_ports) == 2

    def test_parse_agent_use_component(self):
        """解析 use 组件的 agent"""
        dsl = '''
        workflow my-pipeline {
            agent reviewer use code-reviewer
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        agent = result.workflows[0].agents[0]
        assert agent.name == "reviewer"
        assert agent.component == "code-reviewer"

    def test_parse_multiple_agents(self):
        """解析多个 agent"""
        dsl = '''
        workflow my-pipeline {
            agent analyzer {
                port input code: string
                port output analysis: object
            }

            agent reviewer use code-reviewer

            agent reporter {
                port input analysis: object
                port output report: object
            }
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        agents = result.workflows[0].agents
        assert len(agents) == 3
        assert agents[0].name == "analyzer"
        assert agents[1].name == "reviewer"
        assert agents[1].component == "code-reviewer"
        assert agents[2].name == "reporter"


class TestSlice10_ParseConnection:
    """Slice 10: 测试解析连接语法"""

    def test_parse_basic_connection(self):
        """解析基本连接 A -> B"""
        dsl = '''
        workflow my-pipeline {
            agent a { port output out: string }
            agent b { port input in: string }
            a -> b
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        conn = result.workflows[0].connections[0]
        assert conn.source_agent == "a"
        assert conn.target_agents == ["b"]

    def test_parse_explicit_port_connection(self):
        """解析显式端口连接 A.x -> B.y"""
        dsl = '''
        workflow my-pipeline {
            agent a { port output result: object }
            agent b { port input data: object }
            a.result -> b.data
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        conn = result.workflows[0].connections[0]
        assert conn.source_agent == "a"
        assert conn.source_port == "result"
        assert conn.target_agents == ["b"]
        assert conn.target_ports == ["data"]

    def test_parse_broadcast_connection(self):
        """解析广播连接 A -> (B, C, D)"""
        dsl = '''
        workflow my-pipeline {
            agent a { port output out: string }
            agent b { port input in: string }
            agent c { port input in: string }
            agent d { port input in: string }
            a -> (b, c, d)
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        conn = result.workflows[0].connections[0]
        assert conn.source_agent == "a"
        assert conn.target_agents == ["b", "c", "d"]

    def test_parse_aggregate_connection(self):
        """解析聚合连接 (A, B, C) -> D"""
        dsl = '''
        workflow my-pipeline {
            agent a { port output out: string }
            agent b { port output out: string }
            agent c { port output out: string }
            agent d { port input in: string }
            (a, b, c) -> d
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        conn = result.workflows[0].connections[0]
        assert conn.source_agent == "__aggregate__"
        assert conn.target_agents == ["d"]

    def test_parse_multiple_connections(self):
        """解析多个连接"""
        dsl = '''
        workflow my-pipeline {
            agent a { port output out: string }
            agent b { port input in: string }
            agent c { port input in: string }
            a -> b
            b -> c
        }
        '''
        parser = DSLv2Parser()
        result = parser.parse(dsl)
        connections = result.workflows[0].connections
        assert len(connections) == 2
        assert connections[0].source_agent == "a"
        assert connections[0].target_agents == ["b"]
        assert connections[1].source_agent == "b"
        assert connections[1].target_agents == ["c"]

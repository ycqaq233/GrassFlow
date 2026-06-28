"""
GrassFlow 交互式工作流编辑器

参考 opencode/claudecode 风格的终端 UI
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Button, Input, Select,
    DataTable, Tree, Label, Switch, Checkbox
)
from textual.screen import Screen
from textual.binding import Binding
from textual import on, work
from textual.message import Message
from textual.reactive import reactive

from typing import Optional, List, Dict, Any
from pathlib import Path

from core.models import (
    Workflow, AgentInstance, Connection, Component, Port, ModelConfig,
)
from core.dag import DAG, DAGError


class AgentEditor(Screen):
    """Agent 编辑对话框"""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit"),
    ]

    def __init__(self, agent: Optional[AgentInstance] = None, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self.result = None

    def compose(self) -> ComposeResult:
        with Container(id="agent-dialog"):
            yield Label("Agent Editor", id="dialog-title")

            yield Label("Name:")
            yield Input(
                value=self.agent.name if self.agent else "",
                placeholder="agent_name",
                id="agent-name"
            )

            yield Label("Component (use):")
            yield Input(
                value=self.agent.component if self.agent and self.agent.component else "",
                placeholder="component_name (optional)",
                id="agent-component"
            )

            yield Label("Model:")
            yield Input(
                value=self.agent.overrides.get("model", "gpt-4") if self.agent else "gpt-4",
                placeholder="gpt-4",
                id="agent-model"
            )

            yield Label("System Prompt:")
            yield Input(
                value=self.agent.inline_system_prompt if self.agent and self.agent.inline_system_prompt else "",
                placeholder="处理输入: {input}",
                id="agent-prompt"
            )

            yield Label("On Fail:")
            yield Select(
                [("stop", "stop"), ("skip", "skip"), ("retry", "retry")],
                value=self.agent.overrides.get("on_fail", "stop") if self.agent else "stop",
                id="agent-on-fail"
            )

            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def action_submit(self):
        """提交表单"""
        name = self.query_one("#agent-name").value
        component = self.query_one("#agent-component").value
        model = self.query_one("#agent-model").value
        prompt = self.query_one("#agent-prompt").value
        on_fail = self.query_one("#agent-on-fail").value

        if not name:
            self.notify("Name is required!", severity="error")
            return

        self.result = {
            "name": name,
            "component": component if component else None,
            "model": model,
            "system_prompt": prompt,
            "on_fail": on_fail,
        }
        self.dismiss(self.result)

    def action_cancel(self):
        """取消"""
        self.dismiss(None)

    @on(Button.Pressed, "#save-btn")
    def on_save(self):
        self.action_submit()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self):
        self.action_cancel()


class ConnectionEditor(Screen):
    """连接编辑对话框"""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit"),
    ]

    def __init__(self, agents: List[str], connection: Optional[Connection] = None, **kwargs):
        super().__init__(**kwargs)
        self.agents = agents
        self.connection = connection
        self.result = None

    def compose(self) -> ComposeResult:
        with Container(id="edge-dialog"):
            yield Label("Connection Editor", id="dialog-title")

            yield Label("Source:")
            yield Select(
                [(a, a) for a in self.agents],
                value=self.connection.source_agent if self.connection else self.agents[0] if self.agents else "",
                id="conn-source"
            )

            yield Label("Source Port:")
            yield Input(
                value=self.connection.source_port if self.connection and self.connection.source_port else "",
                placeholder="default port",
                id="conn-source-port"
            )

            yield Label("Target (comma-separated for broadcast):")
            yield Input(
                value=", ".join(self.connection.target_agents) if self.connection else "",
                placeholder="target_agent",
                id="conn-targets"
            )

            yield Label("Routing Rules (JSON, e.g. {\"urgent\": [\"A\"], \"normal\": [\"B\"]}):")
            yield Input(
                value=str(self.connection.routing_rules) if self.connection and self.connection.routing_rules else "",
                placeholder="{}",
                id="conn-routing"
            )

            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def action_submit(self):
        """提交表单"""
        import json

        source = self.query_one("#conn-source").value
        source_port = self.query_one("#conn-source-port").value
        targets_str = self.query_one("#conn-targets").value
        routing_str = self.query_one("#conn-routing").value

        targets = [t.strip() for t in targets_str.split(",") if t.strip()]

        if not targets:
            self.notify("At least one target is required!", severity="error")
            return

        routing_rules = {}
        if routing_str:
            try:
                routing_rules = json.loads(routing_str)
            except json.JSONDecodeError:
                self.notify("Invalid JSON in routing rules!", severity="error")
                return

        self.result = {
            "source_agent": source,
            "source_port": source_port if source_port else None,
            "target_agents": targets,
            "routing_rules": routing_rules,
        }
        self.dismiss(self.result)

    def action_cancel(self):
        """取消"""
        self.dismiss(None)

    @on(Button.Pressed, "#save-btn")
    def on_save(self):
        self.action_submit()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self):
        self.action_cancel()


class WorkflowEditor(App):
    """GrassFlow 交互式工作流编辑器"""

    TITLE = "GrassFlow Workflow Editor"
    SUB_TITLE = "Create and edit workflows interactively"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "add_agent", "Add Agent"),
        Binding("e", "edit_agent", "Edit Agent"),
        Binding("d", "delete_agent", "Delete Agent"),
        Binding("c", "add_connection", "Add Connection"),
        Binding("x", "delete_connection", "Delete Connection"),
        Binding("s", "save", "Save"),
        Binding("l", "load", "Load"),
        Binding("v", "validate", "Validate"),
        Binding("p", "preview", "Preview DSL"),
        Binding("n", "new", "New"),
        Binding("f1", "help", "Help"),
    ]

    CSS = """
    #main-container {
        height: 100%;
    }

    #sidebar {
        width: 30%;
        border-right: solid $primary;
        height: 100%;
    }

    #content {
        width: 70%;
        height: 100%;
    }

    #agents-panel {
        height: 50%;
        border-bottom: solid $primary;
    }

    #edges-panel {
        height: 50%;
    }

    #info-panel {
        height: 100%;
    }

    #agent-dialog, #edge-dialog {
        width: 60;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    Label {
        margin-top: 1;
    }

    Input, Select {
        margin-bottom: 1;
    }

    #save-btn, #cancel-btn {
        margin: 1 1;
    }

    DataTable {
        height: 100%;
    }

    #status-bar {
        height: 3;
        border-top: solid $primary;
        padding: 0 1;
    }
    """

    workflow = reactive(None)
    selected_agent = reactive(None)
    selected_connection = reactive(None)

    def __init__(self, workflow_file: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.workflow_file = workflow_file
        self.workflow = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-container"):
            with Vertical(id="sidebar"):
                yield Label("Agents", id="agents-title")
                yield DataTable(id="agents-table")

                yield Label("Connections", id="edges-title")
                yield DataTable(id="edges-table")

            with Vertical(id="content"):
                yield Static(id="info-panel")

        yield Static("Ready | Press F1 for help", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """初始化"""
        agents_table = self.query_one("#agents-table")
        agents_table.add_columns("Name", "Component", "Model")
        agents_table.cursor_type = "row"

        edges_table = self.query_one("#edges-table")
        edges_table.add_columns("Source", "Targets", "Routing")
        edges_table.cursor_type = "row"

        if self.workflow_file:
            self.load_workflow(self.workflow_file)
        else:
            self.workflow = Workflow(name="new_workflow")
            self.refresh_ui()

    def load_workflow(self, file_path: str) -> None:
        """加载工作流"""
        try:
            from tui.dsl_parser import parse_file
            self.workflow = parse_file(file_path)
            self.workflow_file = file_path
            self.refresh_ui()
            self.update_status(f"Loaded: {file_path}")
        except Exception as e:
            self.notify(f"Error loading workflow: {e}", severity="error")

    def refresh_ui(self) -> None:
        """刷新 UI"""
        if not self.workflow:
            return

        # 刷新 Agents 表格
        agents_table = self.query_one("#agents-table")
        agents_table.clear()
        for agent in self.workflow.agents:
            model = agent.overrides.get("model", "-")
            agents_table.add_row(
                agent.name,
                agent.component or "-",
                model,
            )

        # 刷新 Connections 表格
        edges_table = self.query_one("#edges-table")
        edges_table.clear()
        for conn in self.workflow.connections:
            routing = str(conn.routing_rules) if conn.routing_rules else "-"
            edges_table.add_row(
                conn.source_agent,
                ", ".join(conn.target_agents),
                routing,
            )

        # 刷新信息面板
        self.refresh_info_panel()

    def refresh_info_panel(self) -> None:
        """刷新信息面板"""
        info = self.query_one("#info-panel")

        if not self.workflow:
            info.update("No workflow loaded")
            return

        lines = [
            f"# Workflow: {self.workflow.name}",
            "",
            f"**Agents:** {len(self.workflow.agents)}",
            f"**Connections:** {len(self.workflow.connections)}",
            "",
            "## Shortcuts",
            "",
            "| Key | Action |",
            "|-----|--------|",
            "| A | Add Agent |",
            "| E | Edit Agent |",
            "| D | Delete Agent |",
            "| C | Add Connection |",
            "| X | Delete Connection |",
            "| S | Save |",
            "| L | Load |",
            "| V | Validate |",
            "| P | Preview DSL |",
            "| N | New |",
            "| Q | Quit |",
        ]

        if self.selected_agent:
            agent = next(
                (a for a in self.workflow.agents if a.name == self.selected_agent),
                None
            )
            if agent:
                lines.extend([
                    "",
                    f"## Selected Agent: {agent.name}",
                    "",
                    f"- **Component:** {agent.component or 'inline'}",
                    f"- **Model:** {agent.overrides.get('model', 'N/A')}",
                    f"- **System Prompt:** {agent.inline_system_prompt or 'N/A'}",
                    f"- **On Fail:** {agent.overrides.get('on_fail', 'stop')}",
                ])

        info.update("\n".join(lines))

    def update_status(self, message: str) -> None:
        """更新状态栏"""
        status = self.query_one("#status-bar")
        status.update(message)

    @on(DataTable.RowSelected, "#agents-table")
    def on_agent_selected(self, event: DataTable.RowSelected) -> None:
        """Agent 选中"""
        if event.row_key:
            table = self.query_one("#agents-table")
            row = table.get_row(event.row_key)
            if row:
                self.selected_agent = row[0]
                self.refresh_info_panel()

    @on(DataTable.RowSelected, "#edges-table")
    def on_connection_selected(self, event: DataTable.RowSelected) -> None:
        """Connection 选中"""
        if event.row_key:
            table = self.query_one("#edges-table")
            row = table.get_row(event.row_key)
            if row:
                self.selected_connection = {
                    "source": row[0],
                    "targets": row[1],
                }

    def action_add_agent(self) -> None:
        """添加 Agent"""
        def callback(result):
            if result:
                try:
                    overrides = {}
                    if result["model"]:
                        overrides["model"] = result["model"]
                    if result["on_fail"]:
                        overrides["on_fail"] = result["on_fail"]

                    agent = AgentInstance(
                        name=result["name"],
                        component=result.get("component"),
                        overrides=overrides,
                        inline_system_prompt=result.get("system_prompt"),
                    )
                    self.workflow.agents.append(agent)
                    self.refresh_ui()
                    self.update_status(f"Added agent: {agent.name}")
                except Exception as e:
                    self.notify(f"Error: {e}", severity="error")

        self.push_screen(AgentEditor(), callback)

    def action_edit_agent(self) -> None:
        """编辑 Agent"""
        if not self.selected_agent:
            self.notify("Select an agent first!", severity="warning")
            return

        agent = next(
            (a for a in self.workflow.agents if a.name == self.selected_agent),
            None
        )
        if not agent:
            return

        def callback(result):
            if result:
                try:
                    agent.component = result.get("component")
                    agent.overrides["model"] = result["model"]
                    agent.overrides["on_fail"] = result["on_fail"]
                    agent.inline_system_prompt = result.get("system_prompt")
                    self.refresh_ui()
                    self.update_status(f"Updated agent: {agent.name}")
                except Exception as e:
                    self.notify(f"Error: {e}", severity="error")

        self.push_screen(AgentEditor(agent=agent), callback)

    def action_delete_agent(self) -> None:
        """删除 Agent"""
        if not self.selected_agent:
            self.notify("Select an agent first!", severity="warning")
            return

        # 删除相关的连接
        self.workflow.connections = [
            c for c in self.workflow.connections
            if c.source_agent != self.selected_agent and
            self.selected_agent not in c.target_agents
        ]

        # 删除 Agent
        self.workflow.agents = [
            a for a in self.workflow.agents
            if a.name != self.selected_agent
        ]

        self.selected_agent = None
        self.refresh_ui()
        self.update_status("Deleted agent")

    def action_add_connection(self) -> None:
        """添加连接"""
        if len(self.workflow.agents) < 2:
            self.notify("Need at least 2 agents!", severity="warning")
            return

        agent_names = [a.name for a in self.workflow.agents]

        def callback(result):
            if result:
                try:
                    conn = Connection(
                        source_agent=result["source_agent"],
                        source_port=result.get("source_port"),
                        target_agents=result["target_agents"],
                        routing_rules=result.get("routing_rules", {}),
                    )
                    self.workflow.connections.append(conn)
                    self.refresh_ui()
                    self.update_status(f"Added connection: {conn.source_agent} -> {', '.join(conn.target_agents)}")
                except Exception as e:
                    self.notify(f"Error: {e}", severity="error")

        self.push_screen(ConnectionEditor(agents=agent_names), callback)

    def action_delete_connection(self) -> None:
        """删除连接"""
        if not self.selected_connection:
            self.notify("Select a connection first!", severity="warning")
            return

        self.workflow.connections = [
            c for c in self.workflow.connections
            if not (c.source_agent == self.selected_connection["source"] and
                    ", ".join(c.target_agents) == self.selected_connection["targets"])
        ]

        self.selected_connection = None
        self.refresh_ui()
        self.update_status("Deleted connection")

    def action_save(self) -> None:
        """保存工作流"""
        if not self.workflow:
            return

        try:
            if self.workflow_file:
                file_path = self.workflow_file
            else:
                file_path = f"{self.workflow.name}.af"

            dsl = self.generate_dsl()

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(dsl)

            self.workflow_file = file_path
            self.update_status(f"Saved: {file_path}")
            self.notify(f"Saved to {file_path}", severity="information")
        except Exception as e:
            self.notify(f"Error saving: {e}", severity="error")

    def action_load(self) -> None:
        """加载工作流"""
        try:
            from core.storage import workflow_storage
            workflows = workflow_storage.list()

            if workflows:
                self.load_workflow(workflows[0])
            else:
                self.notify("No saved workflows found", severity="warning")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_validate(self) -> None:
        """验证工作流"""
        if not self.workflow:
            return

        try:
            dag = DAG(self.workflow)
            order = dag.topological_sort()
            self.notify(f"Valid! Order: {' -> '.join(order)}", severity="information")
        except DAGError as e:
            self.notify(f"Invalid: {e}", severity="error")

    def action_preview(self) -> None:
        """预览 DSL"""
        if not self.workflow:
            return

        dsl = self.generate_dsl()

        info = self.query_one("#info-panel")
        info.update(f"# DSL Preview\n\n```\n{dsl}\n```")

    def action_new(self) -> None:
        """新建工作流"""
        self.workflow = Workflow(name="new_workflow")
        self.workflow_file = None
        self.selected_agent = None
        self.selected_connection = None
        self.refresh_ui()
        self.update_status("New workflow created")

    def action_help(self) -> None:
        """显示帮助"""
        info = self.query_one("#info-panel")
        info.update("""
# GrassFlow Workflow Editor Help

## Navigation
- **Tab** - Switch between panels
- **Enter** - Select item
- **Escape** - Cancel/Close

## Shortcuts
| Key | Action |
|-----|--------|
| A | Add Agent |
| E | Edit selected Agent |
| D | Delete selected Agent |
| C | Add Connection |
| X | Delete selected Connection |
| S | Save workflow |
| L | Load workflow |
| V | Validate DAG |
| P | Preview DSL |
| N | New workflow |
| Q | Quit |

## Workflow Structure
1. **Agents** - Processing units
2. **Connections** - Data flow between agents
3. **Routing Rules** - Conditional branching based on output
""")

    def generate_dsl(self) -> str:
        """生成 DSL（使用共享的 _generate_dsl 函数）"""
        from tui.cli import _generate_dsl
        return _generate_dsl(self.workflow)


def run_editor(workflow_file: Optional[str] = None) -> None:
    """运行编辑器"""
    app = WorkflowEditor(workflow_file=workflow_file)
    app.run()


if __name__ == "__main__":
    run_editor()

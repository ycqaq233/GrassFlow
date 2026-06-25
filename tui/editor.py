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
    Workflow, AgentConfig, Edge,
    AgentType, InteractionType
)
from core.dag import DAG, DAGError


class AgentEditor(Screen):
    """Agent 编辑对话框"""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit"),
    ]

    def __init__(self, agent: Optional[AgentConfig] = None, **kwargs):
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

            yield Label("Type:")
            yield Select(
                [(t.value, t.value) for t in AgentType],
                value=self.agent.type.value if self.agent else "llm",
                id="agent-type"
            )

            yield Label("Model:")
            yield Input(
                value=self.agent.model if self.agent else "gpt-4",
                placeholder="gpt-4",
                id="agent-model"
            )

            yield Label("Prompt:")
            yield Input(
                value=self.agent.prompt if self.agent else "",
                placeholder="处理输入: {input}",
                id="agent-prompt"
            )

            yield Label("On Fail:")
            yield Select(
                [("stop", "stop"), ("skip", "skip"), ("retry", "retry")],
                value=self.agent.on_fail if self.agent else "stop",
                id="agent-on-fail"
            )

            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def action_submit(self):
        """提交表单"""
        name = self.query_one("#agent-name").value
        agent_type = self.query_one("#agent-type").value
        model = self.query_one("#agent-model").value
        prompt = self.query_one("#agent-prompt").value
        on_fail = self.query_one("#agent-on-fail").value

        if not name:
            self.notify("Name is required!", severity="error")
            return

        self.result = {
            "name": name,
            "type": agent_type,
            "model": model,
            "prompt": prompt,
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


class EdgeEditor(Screen):
    """边编辑对话框"""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Submit"),
    ]

    def __init__(self, agents: List[str], edge: Optional[Edge] = None, **kwargs):
        super().__init__(**kwargs)
        self.agents = agents
        self.edge = edge
        self.result = None

    def compose(self) -> ComposeResult:
        with Container(id="edge-dialog"):
            yield Label("Edge Editor", id="dialog-title")

            yield Label("Source:")
            yield Select(
                [(a, a) for a in self.agents],
                value=self.edge.source if self.edge else self.agents[0] if self.agents else "",
                id="edge-source"
            )

            yield Label("Target:")
            yield Select(
                [(a, a) for a in self.agents],
                value=self.edge.target if self.edge else self.agents[0] if self.agents else "",
                id="edge-target"
            )

            yield Label("Type:")
            yield Select(
                [(t.value, t.value) for t in InteractionType],
                value=self.edge.interaction_type.value if self.edge else "sequence",
                id="edge-type"
            )

            yield Label("Condition (for condition edges):")
            yield Input(
                value=self.edge.condition if self.edge and self.edge.condition else "",
                placeholder="urgent",
                id="edge-condition"
            )

            with Horizontal():
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def action_submit(self):
        """提交表单"""
        source = self.query_one("#edge-source").value
        target = self.query_one("#edge-target").value
        edge_type = self.query_one("#edge-type").value
        condition = self.query_one("#edge-condition").value

        if source == target:
            self.notify("Source and target must be different!", severity="error")
            return

        self.result = {
            "source": source,
            "target": target,
            "interaction_type": edge_type,
            "condition": condition if condition else None,
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
        Binding("c", "add_edge", "Add Connection"),
        Binding("x", "delete_edge", "Delete Connection"),
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
    selected_edge = reactive(None)

    def __init__(self, workflow_file: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.workflow_file = workflow_file
        self.workflow = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-container"):
            # 左侧：Agent 和 Edge 列表
            with Vertical(id="sidebar"):
                yield Label("📋 Agents", id="agents-title")
                yield DataTable(id="agents-table")

                yield Label("🔗 Connections", id="edges-title")
                yield DataTable(id="edges-table")

            # 右侧：详细信息
            with Vertical(id="content"):
                yield Static(id="info-panel")

        yield Static("Ready | Press F1 for help", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """初始化"""
        # 初始化 Agents 表格
        agents_table = self.query_one("#agents-table")
        agents_table.add_columns("Name", "Type", "Model")
        agents_table.cursor_type = "row"

        # 初始化 Edges 表格
        edges_table = self.query_one("#edges-table")
        edges_table.add_columns("Source", "Target", "Type", "Condition")
        edges_table.cursor_type = "row"

        # 加载工作流
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
            agents_table.add_row(
                agent.name,
                agent.type.value,
                agent.model or "-"
            )

        # 刷新 Edges 表格
        edges_table = self.query_one("#edges-table")
        edges_table.clear()
        for edge in self.workflow.edges:
            edges_table.add_row(
                edge.source,
                edge.target,
                edge.interaction_type.value,
                edge.condition or "-"
            )

        # 刷新信息面板
        self.refresh_info_panel()

    def refresh_info_panel(self) -> None:
        """刷新信息面板"""
        info = self.query_one("#info-panel")

        if not self.workflow:
            info.update("No workflow loaded")
            return

        # 构建信息文本
        lines = [
            f"# Workflow: {self.workflow.name}",
            "",
            f"**Description:** {self.workflow.description or 'N/A'}",
            f"**Agents:** {len(self.workflow.agents)}",
            f"**Connections:** {len(self.workflow.edges)}",
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

        # 显示选中的 Agent 信息
        if self.selected_agent:
            agent = self.workflow.get_agent(self.selected_agent)
            if agent:
                lines.extend([
                    "",
                    f"## Selected Agent: {agent.name}",
                    "",
                    f"- **Type:** {agent.type.value}",
                    f"- **Model:** {agent.model}",
                    f"- **Prompt:** {agent.prompt or 'N/A'}",
                    f"- **On Fail:** {agent.on_fail}",
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
    def on_edge_selected(self, event: DataTable.RowSelected) -> None:
        """Edge 选中"""
        if event.row_key:
            table = self.query_one("#edges-table")
            row = table.get_row(event.row_key)
            if row:
                self.selected_edge = {
                    "source": row[0],
                    "target": row[1],
                }

    def action_add_agent(self) -> None:
        """添加 Agent"""
        def callback(result):
            if result:
                try:
                    agent_type = AgentType(result["type"])
                    agent = AgentConfig(
                        name=result["name"],
                        type=agent_type,
                        model=result["model"],
                        prompt=result["prompt"],
                        on_fail=result["on_fail"],
                    )
                    self.workflow.add_agent(agent)
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

        agent = self.workflow.get_agent(self.selected_agent)
        if not agent:
            return

        def callback(result):
            if result:
                try:
                    # 更新 Agent
                    agent.type = AgentType(result["type"])
                    agent.model = result["model"]
                    agent.prompt = result["prompt"]
                    agent.on_fail = result["on_fail"]
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

        # 删除相关的边
        self.workflow.edges = [
            e for e in self.workflow.edges
            if e.source != self.selected_agent and e.target != self.selected_agent
        ]

        # 删除 Agent
        self.workflow.agents = [
            a for a in self.workflow.agents
            if a.name != self.selected_agent
        ]

        self.selected_agent = None
        self.refresh_ui()
        self.update_status(f"Deleted agent")

    def action_add_edge(self) -> None:
        """添加边"""
        if len(self.workflow.agents) < 2:
            self.notify("Need at least 2 agents!", severity="warning")
            return

        agent_names = [a.name for a in self.workflow.agents]

        def callback(result):
            if result:
                try:
                    interaction_type = InteractionType(result["interaction_type"])
                    edge = Edge(
                        source=result["source"],
                        target=result["target"],
                        interaction_type=interaction_type,
                        condition=result["condition"],
                    )
                    self.workflow.add_edge(edge)
                    self.refresh_ui()
                    self.update_status(f"Added edge: {edge.source} -> {edge.target}")
                except Exception as e:
                    self.notify(f"Error: {e}", severity="error")

        self.push_screen(EdgeEditor(agents=agent_names), callback)

    def action_delete_edge(self) -> None:
        """删除边"""
        if not self.selected_edge:
            self.notify("Select an edge first!", severity="warning")
            return

        self.workflow.edges = [
            e for e in self.workflow.edges
            if not (e.source == self.selected_edge["source"] and
                   e.target == self.selected_edge["target"])
        ]

        self.selected_edge = None
        self.refresh_ui()
        self.update_status("Deleted edge")

    def action_save(self) -> None:
        """保存工作流"""
        if not self.workflow:
            return

        try:
            if self.workflow_file:
                file_path = self.workflow_file
            else:
                file_path = f"{self.workflow.name}.af"

            # 生成 DSL
            dsl = self.generate_dsl()

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(dsl)

            self.workflow_file = file_path
            self.update_status(f"Saved: {file_path}")
            self.notify(f"Saved to {file_path}", severity="information")
        except Exception as e:
            self.notify(f"Error saving: {e}", severity="error")

    def action_load(self) -> None:
        """加载工作流"""
        # 简单实现：加载默认示例
        try:
            from tui.storage import workflow_storage
            workflows = workflow_storage.list()

            if workflows:
                # 加载第一个
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

        # 更新信息面板显示 DSL
        info = self.query_one("#info-panel")
        info.update(f"# DSL Preview\n\n```\n{dsl}\n```")

    def action_new(self) -> None:
        """新建工作流"""
        self.workflow = Workflow(name="new_workflow")
        self.workflow_file = None
        self.selected_agent = None
        self.selected_edge = None
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
| C | Add Connection (Edge) |
| X | Delete selected Connection |
| S | Save workflow |
| L | Load workflow |
| V | Validate DAG |
| P | Preview DSL |
| N | New workflow |
| Q | Quit |

## Workflow Structure
1. **Agents** - Processing units (LLM, Condition, Manual, etc.)
2. **Connections** - Data flow between agents
3. **Conditions** - Branching logic based on output

## Agent Types
- **LLM** - Language model agent
- **Condition** - Conditional routing
- **Manual** - Human intervention
- **Input** - Workflow input
- **Output** - Workflow output

## Connection Types
- **Sequence** - A -> B (A completes before B starts)
- **Parallel** - (A, B) -> C (A and B run together)
- **Immediate** - A | B (B starts immediately)
- **Condition** - A -> [x] B (B runs if condition x)
""")

    def generate_dsl(self) -> str:
        """生成 DSL"""
        lines = []
        lines.append(f"# {self.workflow.name}")
        lines.append(f"# {self.workflow.description or ''}")
        lines.append("")
        lines.append(f"workflow {self.workflow.name} {{")

        # Agent 声明
        for agent in self.workflow.agents:
            lines.append(f"  agent {agent.name} {{")
            if agent.type.value != "llm":
                lines.append(f'    type: "{agent.type.value}"')
            if agent.model:
                lines.append(f'    model: "{agent.model}"')
            if agent.prompt:
                lines.append(f'    prompt: "{agent.prompt}"')
            if agent.input_schema:
                lines.append(f'    input_schema: {agent.input_schema}')
            if agent.output_schema:
                lines.append(f'    output_schema: {agent.output_schema}')
            if agent.on_fail != "stop":
                lines.append(f'    on_fail: "{agent.on_fail}"')
            lines.append("  }")
            lines.append("")

        # 执行流
        lines.append("  # 执行流")

        # 简化：按顺序输出边
        for edge in self.workflow.edges:
            if edge.interaction_type == InteractionType.CONDITION:
                lines.append(f"  {edge.source} -> [{edge.condition}] {edge.target}")
            elif edge.interaction_type == InteractionType.PARALLEL:
                lines.append(f"  ({edge.source}, {edge.target})")
            elif edge.interaction_type == InteractionType.IMMEDIATE:
                lines.append(f"  {edge.source} | {edge.target}")
            else:
                lines.append(f"  {edge.source} -> {edge.target}")

        lines.append("}")

        return "\n".join(lines)


def run_editor(workflow_file: Optional[str] = None) -> None:
    """运行编辑器"""
    app = WorkflowEditor(workflow_file=workflow_file)
    app.run()


if __name__ == "__main__":
    run_editor()

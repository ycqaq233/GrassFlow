"""
GrassFlow 意图检测器

通过规则匹配检测用户消息中的多步骤任务意图，
并生成对应的 DSL v2 工作流定义。
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SubTask:
    """子任务定义"""
    name: str
    description: str


@dataclass
class WorkflowIntent:
    """工作流意图"""
    task_description: str
    sub_tasks: List[SubTask] = field(default_factory=list)
    estimated_agents: int = 1
    pattern: str = "sequential"  # "sequential" | "parallel" | "parallel_aggregate"


class IntentDetector:
    """
    意图检测器 — 通过规则匹配识别多步骤任务。

    支持的模式：
    - "分析...然后..." → sequential（顺序依赖）
    - "对比...和..." → parallel_aggregate（并行分析 + 聚合）
    - "先...再...最后..." → multi-step sequential（多步顺序）
    - "分别..." → parallel（并行执行）
    """

    # ── 模式定义 ──────────────────────────────────────────────

    # "分析X然后Y" 模式
    _PATTERN_THEN = re.compile(
        r'(.+?)然后(.+)',
        re.DOTALL,
    )

    # "先X再Y最后Z" 模式（2-4 步）
    _PATTERN_FIRST_THEN_LAST = re.compile(
        r'先(.+?)(?:再(.+?))?(?:最后(.+))?$',
        re.DOTALL,
    )

    # "对比X和Y" 模式
    _PATTERN_COMPARE = re.compile(
        r'(?:对比|比较|对照)(.+?)和(.+)',
        re.DOTALL,
    )

    # "分别X" 模式
    _PATTERN_RESPECTIVELY = re.compile(
        r'分别(.+)',
        re.DOTALL,
    )

    # ── 公开接口 ──────────────────────────────────────────────

    def detect_intent(self, message: str) -> Optional[WorkflowIntent]:
        """
        检测消息中的工作流意图。

        Args:
            message: 用户消息文本

        Returns:
            WorkflowIntent 对象，如果检测到多步骤任务；否则 None。
        """
        message = message.strip()
        if not message:
            return None

        # 按优先级依次尝试匹配
        intent = (
            self._try_first_then_last(message)
            or self._try_compare(message)
            or self._try_then(message)
            or self._try_respectively(message)
        )
        return intent

    def generate_dsl(self, intent: WorkflowIntent) -> str:
        """
        根据 WorkflowIntent 生成 DSL v2 文本。

        Args:
            intent: 工作流意图

        Returns:
            合法的 DSL v2 文本
        """
        if intent.pattern == "parallel_aggregate":
            return self._generate_parallel_aggregate_dsl(intent)
        elif intent.pattern == "parallel":
            return self._generate_parallel_dsl(intent)
        else:
            return self._generate_sequential_dsl(intent)

    # ── 模式匹配 ──────────────────────────────────────────────

    def _try_then(self, message: str) -> Optional[WorkflowIntent]:
        """匹配 "X然后Y" 模式 → 顺序依赖"""
        m = self._PATTERN_THEN.search(message)
        if not m:
            return None

        step1 = m.group(1).strip().rstrip("，,")
        step2 = m.group(2).strip().rstrip("，,。.")

        if not step1 or not step2:
            return None

        sub_tasks = [
            SubTask(name=self._make_name(step1, 0), description=step1),
            SubTask(name=self._make_name(step2, 1), description=step2),
        ]
        return WorkflowIntent(
            task_description=message,
            sub_tasks=sub_tasks,
            estimated_agents=len(sub_tasks),
            pattern="sequential",
        )

    def _try_first_then_last(self, message: str) -> Optional[WorkflowIntent]:
        """匹配 "先X再Y最后Z" 模式 → 多步顺序"""
        m = self._PATTERN_FIRST_THEN_LAST.search(message)
        if not m:
            return None

        groups = [g.strip().rstrip("，,。.") for g in m.groups() if g]
        groups = [g for g in groups if g]

        if len(groups) < 2:
            return None

        sub_tasks = [
            SubTask(name=self._make_name(g, i), description=g)
            for i, g in enumerate(groups)
        ]
        return WorkflowIntent(
            task_description=message,
            sub_tasks=sub_tasks,
            estimated_agents=len(sub_tasks),
            pattern="sequential",
        )

    def _try_compare(self, message: str) -> Optional[WorkflowIntent]:
        """匹配 "对比X和Y" 模式 → 并行分析 + 聚合"""
        m = self._PATTERN_COMPARE.search(message)
        if not m:
            return None

        item1 = m.group(1).strip().rstrip("，,")
        item2 = m.group(2).strip().rstrip("，,。.")

        if not item1 or not item2:
            return None

        sub_tasks = [
            SubTask(name=self._make_name(item1, 0), description=f"分析{item1}"),
            SubTask(name=self._make_name(item2, 1), description=f"分析{item2}"),
            SubTask(name="aggregate", description="汇总对比结果"),
        ]
        return WorkflowIntent(
            task_description=message,
            sub_tasks=sub_tasks,
            estimated_agents=3,
            pattern="parallel_aggregate",
        )

    def _try_respectively(self, message: str) -> Optional[WorkflowIntent]:
        """匹配 "分别X" 模式 → 并行执行"""
        m = self._PATTERN_RESPECTIVELY.search(message)
        if not m:
            return None

        content = m.group(1).strip().rstrip("，,。.")

        # 尝试按 "、"、"," 或 "和" 分割
        parts = re.split(r'[、，,]|和', content)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 2:
            return None

        sub_tasks = [
            SubTask(name=self._make_name(p, i), description=p)
            for i, p in enumerate(parts)
        ]
        return WorkflowIntent(
            task_description=message,
            sub_tasks=sub_tasks,
            estimated_agents=len(sub_tasks),
            pattern="parallel",
        )

    # ── DSL 生成 ──────────────────────────────────────────────

    def _generate_sequential_dsl(self, intent: WorkflowIntent) -> str:
        """生成顺序依赖 DSL"""
        lines = [f'workflow auto-generated {{']
        lines.append(f'    description: "{intent.task_description}"')
        lines.append('')

        # component 定义
        for st in intent.sub_tasks:
            comp_name = self._sanitize_name(st.name)
            lines.append(f'    component {comp_name}-agent {{')
            lines.append(f'        description: "{st.description}"')
            lines.append(f'        port input data: object "输入数据"')
            lines.append(f'        port output result: object "输出结果"')
            lines.append(f'    }}')
            lines.append('')

        # agent 实例化
        for st in intent.sub_tasks:
            comp_name = self._sanitize_name(st.name)
            agent_name = self._sanitize_name(st.name)
            lines.append(f'    agent {agent_name} use {comp_name}-agent')
        lines.append('')

        # 连接
        for i in range(len(intent.sub_tasks) - 1):
            src = self._sanitize_name(intent.sub_tasks[i].name)
            dst = self._sanitize_name(intent.sub_tasks[i + 1].name)
            lines.append(f'    {src} -> {dst}')

        lines.append('}')
        return '\n'.join(lines)

    def _generate_parallel_dsl(self, intent: WorkflowIntent) -> str:
        """生成并行执行 DSL"""
        lines = [f'workflow auto-generated {{']
        lines.append(f'    description: "{intent.task_description}"')
        lines.append('')

        # component 定义
        for st in intent.sub_tasks:
            comp_name = self._sanitize_name(st.name)
            lines.append(f'    component {comp_name}-agent {{')
            lines.append(f'        description: "{st.description}"')
            lines.append(f'        port input data: object "输入数据"')
            lines.append(f'        port output result: object "输出结果"')
            lines.append(f'    }}')
            lines.append('')

        # agent 实例化
        for st in intent.sub_tasks:
            comp_name = self._sanitize_name(st.name)
            agent_name = self._sanitize_name(st.name)
            lines.append(f'    agent {agent_name} use {comp_name}-agent')

        lines.append('}')
        return '\n'.join(lines)

    def _generate_parallel_aggregate_dsl(self, intent: WorkflowIntent) -> str:
        """生成并行分析 + 聚合 DSL"""
        lines = [f'workflow auto-generated {{']
        lines.append(f'    description: "{intent.task_description}"')
        lines.append('')

        # 所有子任务的 component 定义
        for st in intent.sub_tasks:
            comp_name = self._sanitize_name(st.name)
            lines.append(f'    component {comp_name}-agent {{')
            lines.append(f'        description: "{st.description}"')
            lines.append(f'        port input data: object "输入数据"')
            lines.append(f'        port output result: object "输出结果"')
            lines.append(f'    }}')
            lines.append('')

        # agent 实例化
        for st in intent.sub_tasks:
            comp_name = self._sanitize_name(st.name)
            agent_name = self._sanitize_name(st.name)
            lines.append(f'    agent {agent_name} use {comp_name}-agent')
        lines.append('')

        # 聚合连接：前 N-1 个 agent → 最后一个 agent（聚合）
        parallel_agents = [self._sanitize_name(st.name) for st in intent.sub_tasks[:-1]]
        aggregator = self._sanitize_name(intent.sub_tasks[-1].name)
        sources = ', '.join(parallel_agents)
        lines.append(f'    ({sources}) -> {aggregator}')

        lines.append('}')
        return '\n'.join(lines)

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _make_name(text: str, index: int) -> str:
        """从描述文本中提取 agent 名称"""
        # 取前 4 个字符作为基础，去掉标点
        clean = re.sub(r'[^\w\s]', '', text)
        words = clean.split()
        if words:
            # 取第一个词，截断到 12 字符
            name = words[0][:12]
        else:
            name = f"step{index + 1}"
        return name

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """将名称转为合法的 DSL 标识符"""
        # 替换非字母数字下划线字符为下划线
        sanitized = re.sub(r'[^\w]', '_', name)
        # 去掉连续下划线
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        if not sanitized or not sanitized[0].isalpha():
            sanitized = f"task_{sanitized}" if sanitized else "task"
        return sanitized.lower()

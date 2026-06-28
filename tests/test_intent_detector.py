"""
GrassFlow 意图检测器测试

覆盖：
- 单步骤任务 → 返回 None
- 顺序依赖 → 返回正确的 WorkflowIntent
- 并行任务 → 返回正确的并行结构
- DSL 生成结果语法正确
"""

import pytest
from tui.intent_detector import IntentDetector, WorkflowIntent, SubTask
from tui.dsl_parser_v2 import DSLv2Parser


class TestDetectIntent:
    """测试意图检测"""

    def setup_method(self):
        self.detector = IntentDetector()

    # ── 单步骤任务 → None ────────────────────────────────────

    def test_empty_message_returns_none(self):
        """空消息返回 None"""
        assert self.detector.detect_intent("") is None
        assert self.detector.detect_intent("   ") is None

    def test_simple_task_returns_none(self):
        """简单单步任务返回 None"""
        assert self.detector.detect_intent("帮我写一首诗") is None
        assert self.detector.detect_intent("翻译这段话") is None
        assert self.detector.detect_intent("今天天气怎么样") is None

    # ── "分析...然后..." → sequential ────────────────────────

    def test_then_pattern_detected(self):
        """'分析X然后Y' 被识别为顺序依赖"""
        intent = self.detector.detect_intent("分析代码然后生成报告")
        assert intent is not None
        assert intent.pattern == "sequential"
        assert len(intent.sub_tasks) == 2
        assert intent.estimated_agents == 2

    def test_then_pattern_sub_tasks(self):
        """顺序依赖的子任务描述正确"""
        intent = self.detector.detect_intent("分析代码然后生成报告")
        assert intent is not None
        assert "分析代码" in intent.sub_tasks[0].description
        assert "生成报告" in intent.sub_tasks[1].description

    def test_then_pattern_with_comma(self):
        """带逗号的顺序依赖"""
        intent = self.detector.detect_intent("抓取网页内容，然后提取关键信息")
        assert intent is not None
        assert len(intent.sub_tasks) == 2

    # ── "先...再...最后..." → multi-step sequential ─────────

    def test_first_then_last_three_steps(self):
        """'先X再Y最后Z' 三步顺序"""
        intent = self.detector.detect_intent("先收集数据再分析趋势最后写报告")
        assert intent is not None
        assert intent.pattern == "sequential"
        assert len(intent.sub_tasks) == 3
        assert intent.estimated_agents == 3

    def test_first_then_last_two_steps(self):
        """'先X再Y' 两步顺序"""
        intent = self.detector.detect_intent("先读取文件再解析内容")
        assert intent is not None
        assert intent.pattern == "sequential"
        assert len(intent.sub_tasks) == 2

    def test_first_then_last_sub_task_order(self):
        """子任务顺序与原文一致"""
        intent = self.detector.detect_intent("先收集数据再分析趋势最后写报告")
        assert intent is not None
        assert "收集数据" in intent.sub_tasks[0].description
        assert "分析趋势" in intent.sub_tasks[1].description
        assert "写报告" in intent.sub_tasks[2].description

    # ── "对比...和..." → parallel_aggregate ─────────────────

    def test_compare_pattern_detected(self):
        """'对比X和Y' 被识别为并行聚合"""
        intent = self.detector.detect_intent("对比方案A和方案B")
        assert intent is not None
        assert intent.pattern == "parallel_aggregate"
        assert len(intent.sub_tasks) == 3  # 2 分析 + 1 聚合
        assert intent.estimated_agents == 3

    def test_compare_pattern_has_aggregator(self):
        """并行聚合的最后一个子任务是汇总"""
        intent = self.detector.detect_intent("对比方案A和方案B")
        assert intent is not None
        assert intent.sub_tasks[-1].name == "aggregate"
        assert "汇总" in intent.sub_tasks[-1].description

    def test_compare_with_chinese(self):
        """中文逗号的对比模式"""
        intent = self.detector.detect_intent("比较Python和Java的性能差异")
        assert intent is not None
        assert intent.pattern == "parallel_aggregate"

    # ── "分别..." → parallel ─────────────────────────────────

    def test_respectively_pattern_detected(self):
        """'分别X、Y、Z' 被识别为并行"""
        intent = self.detector.detect_intent("分别分析Python、Java、Go的优缺点")
        assert intent is not None
        assert intent.pattern == "parallel"
        assert len(intent.sub_tasks) == 3
        assert intent.estimated_agents == 3

    def test_respectively_two_items(self):
        """两个项目的并行"""
        intent = self.detector.detect_intent("分别分析前端和后端的代码")
        assert intent is not None
        assert len(intent.sub_tasks) == 2

    def test_respectively_with_comma_separator(self):
        """用逗号分割的并行任务"""
        intent = self.detector.detect_intent("分别测试登录、注册、找回密码")
        assert intent is not None
        assert len(intent.sub_tasks) == 3


class TestGenerateDSL:
    """测试 DSL 生成"""

    def setup_method(self):
        self.detector = IntentDetector()
        self.parser = DSLv2Parser()

    def _parse_generated_dsl(self, intent: WorkflowIntent):
        """生成 DSL 并解析，返回 ParseResult"""
        dsl = self.detector.generate_dsl(intent)
        result = self.parser.parse(dsl)
        return result, dsl

    # ── 顺序 DSL ─────────────────────────────────────────────

    def test_sequential_dsl_valid(self):
        """顺序 DSL 语法合法"""
        intent = self.detector.detect_intent("分析代码然后生成报告")
        assert intent is not None
        result, dsl = self._parse_generated_dsl(intent)
        assert result.errors == [], f"DSL 解析错误: {result.errors}\nDSL:\n{dsl}"

    def test_sequential_dsl_has_workflow(self):
        """顺序 DSL 包含 workflow"""
        intent = self.detector.detect_intent("分析代码然后生成报告")
        result, _ = self._parse_generated_dsl(intent)
        assert len(result.workflows) == 1

    def test_sequential_dsl_agents_count(self):
        """顺序 DSL agent 数量正确"""
        intent = self.detector.detect_intent("分析代码然后生成报告")
        result, _ = self._parse_generated_dsl(intent)
        assert len(result.workflows[0].agents) == 2

    def test_sequential_dsl_connections(self):
        """顺序 DSL 连接数量正确 (N-1)"""
        intent = self.detector.detect_intent("先收集数据再分析趋势最后写报告")
        result, _ = self._parse_generated_dsl(intent)
        assert len(result.workflows[0].connections) == 2

    def test_sequential_dsl_chain(self):
        """顺序 DSL 连接形成链式结构"""
        intent = self.detector.detect_intent("先收集数据再分析趋势最后写报告")
        result, _ = self._parse_generated_dsl(intent)
        conns = result.workflows[0].connections
        agent_names = [a.name for a in result.workflows[0].agents]

        # 每个连接的 source → target 形成链
        for i in range(len(conns) - 1):
            assert conns[i].target_agents[0] == conns[i + 1].source_agent

    # ── 并行 DSL ─────────────────────────────────────────────

    def test_parallel_dsl_valid(self):
        """并行 DSL 语法合法"""
        intent = self.detector.detect_intent("分别分析Python、Java、Go的优缺点")
        assert intent is not None
        result, dsl = self._parse_generated_dsl(intent)
        assert result.errors == [], f"DSL 解析错误: {result.errors}\nDSL:\n{dsl}"

    def test_parallel_dsl_no_connections(self):
        """并行 DSL 没有连接（各 agent 独立运行）"""
        intent = self.detector.detect_intent("分别分析Python、Java、Go的优缺点")
        result, _ = self._parse_generated_dsl(intent)
        assert len(result.workflows[0].connections) == 0

    def test_parallel_dsl_agents_count(self):
        """并行 DSL agent 数量正确"""
        intent = self.detector.detect_intent("分别分析Python、Java、Go的优缺点")
        result, _ = self._parse_generated_dsl(intent)
        assert len(result.workflows[0].agents) == 3

    # ── 并行聚合 DSL ─────────────────────────────────────────

    def test_parallel_aggregate_dsl_valid(self):
        """并行聚合 DSL 语法合法"""
        intent = self.detector.detect_intent("对比方案A和方案B")
        assert intent is not None
        result, dsl = self._parse_generated_dsl(intent)
        assert result.errors == [], f"DSL 解析错误: {result.errors}\nDSL:\n{dsl}"

    def test_parallel_aggregate_dsl_has_aggregate_connection(self):
        """并行聚合 DSL 包含聚合连接"""
        intent = self.detector.detect_intent("对比方案A和方案B")
        result, _ = self._parse_generated_dsl(intent)
        conns = result.workflows[0].connections
        assert len(conns) == 1
        # 聚合连接的 source 是 __aggregate__
        assert conns[0].source_agent == "__aggregate__"

    def test_parallel_aggregate_dsl_agents_count(self):
        """并行聚合 DSL agent 数量 (2 分析 + 1 聚合)"""
        intent = self.detector.detect_intent("对比方案A和方案B")
        result, _ = self._parse_generated_dsl(intent)
        assert len(result.workflows[0].agents) == 3

    # ── 多步顺序 DSL ─────────────────────────────────────────

    def test_three_step_sequential_dsl_valid(self):
        """三步顺序 DSL 语法合法"""
        intent = self.detector.detect_intent("先收集数据再分析趋势最后写报告")
        assert intent is not None
        result, dsl = self._parse_generated_dsl(intent)
        assert result.errors == [], f"DSL 解析错误: {result.errors}\nDSL:\n{dsl}"

    def test_three_step_sequential_dsl_structure(self):
        """三步顺序 DSL 结构正确"""
        intent = self.detector.detect_intent("先收集数据再分析趋势最后写报告")
        result, _ = self._parse_generated_dsl(intent)
        wf = result.workflows[0]
        assert len(wf.agents) == 3
        assert len(wf.connections) == 2
        assert len(result.components) == 3


class TestEdgeCases:
    """边界情况测试"""

    def setup_method(self):
        self.detector = IntentDetector()

    def test_task_description_preserved(self):
        """task_description 保留原始消息"""
        msg = "分析代码然后生成报告"
        intent = self.detector.detect_intent(msg)
        assert intent is not None
        assert intent.task_description == msg

    def test_sub_task_has_name(self):
        """每个子任务都有 name"""
        intent = self.detector.detect_intent("分析代码然后生成报告")
        assert intent is not None
        for st in intent.sub_tasks:
            assert st.name
            assert len(st.name) > 0

    def test_sub_task_has_description(self):
        """每个子任务都有 description"""
        intent = self.detector.detect_intent("分别分析Python、Java、Go的优缺点")
        assert intent is not None
        for st in intent.sub_tasks:
            assert st.description
            assert len(st.description) > 0

    def test_single_then_step_returns_none(self):
        """只有一个 '然后' 后面为空时不匹配"""
        # "然后" 后面没有内容
        intent = self.detector.detect_intent("然后")
        assert intent is None

    def test_priority_then_over_first_then_last(self):
        """'先X然后Y' 应匹配到 '然后' 模式（因为 '先' 后没有 '再'）"""
        intent = self.detector.detect_intent("先分析代码然后生成报告")
        # 这里 "先分析代码" 会被当作 "然后" 模式的第一步
        assert intent is not None
        assert intent.pattern == "sequential"

"""
Doom Loop 检测测试
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from core.doom_loop import (
    DoomLoopDetector,
    DoomLoopConfig,
    DoomLoopAction,
    DoomLoopDetection,
    DoomLoopError,
    DoomLoopManager,
    get_doom_loop_detector,
    get_doom_loop_manager,
)


class TestDoomLoopConfig:
    """Doom Loop 配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = DoomLoopConfig()
        assert config.max_repeated_calls == 3
        assert config.time_window is None
        assert config.action == DoomLoopAction.ASK_USER
        assert config.include_args is True
        assert config.arg_hash_depth == 3

    def test_custom_config(self):
        """测试自定义配置"""
        config = DoomLoopConfig(
            max_repeated_calls=5,
            time_window=60.0,
            action=DoomLoopAction.AUTO_STOP,
        )
        assert config.max_repeated_calls == 5
        assert config.time_window == 60.0
        assert config.action == DoomLoopAction.AUTO_STOP


class TestDoomLoopDetector:
    """Doom Loop 检测器测试"""

    def test_no_detection_below_threshold(self):
        """测试低于阈值不触发检测"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 2 次调用，低于阈值
        detection1 = detector.check_call("search", {"query": "test"})
        detection2 = detector.check_call("search", {"query": "test"})

        assert not detection1.detected
        assert not detection2.detected
        assert detection2.call_count == 2

    def test_detection_at_threshold(self):
        """测试达到阈值触发检测"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 3 次调用，达到阈值
        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})
        detection = detector.check_call("search", {"query": "test"})

        assert detection.detected
        assert detection.call_count == 3
        assert detection.tool_name == "search"
        assert "test" in str(detection.args)

    def test_different_args_not_detected(self):
        """测试不同参数不触发检测"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 3 次调用，但参数不同
        detector.check_call("search", {"query": "test1"})
        detector.check_call("search", {"query": "test2"})
        detection = detector.check_call("search", {"query": "test3"})

        assert not detection.detected

    def test_different_tools_not_detected(self):
        """测试不同工具不触发检测"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 3 次调用，但工具不同
        detector.check_call("search", {"query": "test"})
        detector.check_call("read", {"file": "test.txt"})
        detection = detector.check_call("write", {"file": "test.txt"})

        assert not detection.detected

    def test_time_window(self):
        """测试时间窗口"""
        config = DoomLoopConfig(max_repeated_calls=3, time_window=0.1)
        detector = DoomLoopDetector(config)

        # 第一次调用
        detector.check_call("search", {"query": "test"})

        # 等待超过时间窗口
        time.sleep(0.15)

        # 第二次调用（第一次已过期）
        detector.check_call("search", {"query": "test"})

        # 第三次调用
        detection = detector.check_call("search", {"query": "test"})

        # 不应该触发，因为第一次调用已过期
        assert not detection.detected
        assert detection.call_count == 2

    def test_include_args_false(self):
        """测试不包含参数"""
        config = DoomLoopConfig(max_repeated_calls=3, include_args=False)
        detector = DoomLoopDetector(config)

        # 即使参数不同，也应该触发检测
        detector.check_call("search", {"query": "test1"})
        detector.check_call("search", {"query": "test2"})
        detection = detector.check_call("search", {"query": "test3"})

        assert detection.detected

    def test_detection_message(self):
        """测试检测消息"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})
        detection = detector.check_call("search", {"query": "test"})

        assert "Doom Loop" in detection.message
        assert "search" in detection.message
        assert "3" in detection.message

    def test_time_span_calculation(self):
        """测试时间跨度计算"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        detector.check_call("search", {"query": "test"})
        time.sleep(0.1)
        detector.check_call("search", {"query": "test"})
        time.sleep(0.1)
        detection = detector.check_call("search", {"query": "test"})

        assert detection.time_span >= 0.2


class TestDoomLoopDetectorHandling:
    """Doom Loop 检测器处理测试"""

    @pytest.mark.asyncio
    async def test_ask_user_action(self):
        """测试询问用户操作"""
        callback = MagicMock(return_value=True)
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.ASK_USER,
        )
        detector = DoomLoopDetector(config, on_detection=callback)

        # 前两次调用
        await detector.check_and_handle("search", {"query": "test"})
        await detector.check_and_handle("search", {"query": "test"})

        # 第三次调用触发检测
        result = await detector.check_and_handle("search", {"query": "test"})

        assert result is True
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_ask_user_action_reject(self):
        """测试询问用户后拒绝"""
        callback = MagicMock(return_value=False)
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.ASK_USER,
        )
        detector = DoomLoopDetector(config, on_detection=callback)

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        result = await detector.check_and_handle("search", {"query": "test"})

        assert result is False

    @pytest.mark.asyncio
    async def test_auto_stop_action(self):
        """测试自动停止操作"""
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.AUTO_STOP,
        )
        detector = DoomLoopDetector(config)

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        with pytest.raises(DoomLoopError) as exc_info:
            await detector.check_and_handle("search", {"query": "test"})

        assert exc_info.value.detection.detected is True

    @pytest.mark.asyncio
    async def test_auto_skip_action(self):
        """测试自动跳过操作"""
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.AUTO_SKIP,
        )
        detector = DoomLoopDetector(config)

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        result = await detector.check_and_handle("search", {"query": "test"})

        assert result is False

    @pytest.mark.asyncio
    async def test_log_warning_action(self):
        """测试仅记录警告操作"""
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.LOG_WARNING,
        )
        detector = DoomLoopDetector(config)

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        result = await detector.check_and_handle("search", {"query": "test"})

        assert result is True


class TestDoomLoopDetectorWrap:
    """Doom Loop 检测器装饰器测试"""

    @pytest.mark.asyncio
    async def test_wrap_no_detection(self):
        """测试装饰器无检测"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        call_count = 0

        @detector.wrap
        async def call_tool(tool_name, args):
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        # 2 次调用，不触发检测
        result1 = await call_tool("search", {"query": "test"})
        result2 = await call_tool("search", {"query": "test"})

        assert result1 == "result_1"
        assert result2 == "result_2"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_wrap_with_detection_continue(self):
        """测试装饰器触发检测后继续"""
        callback = MagicMock(return_value=True)
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.ASK_USER,
        )
        detector = DoomLoopDetector(config, on_detection=callback)

        call_count = 0

        @detector.wrap
        async def call_tool(tool_name, args):
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        # 3 次调用，触发检测
        await call_tool("search", {"query": "test"})
        await call_tool("search", {"query": "test"})
        result = await call_tool("search", {"query": "test"})

        assert result == "result_3"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_wrap_with_detection_stop(self):
        """测试装饰器触发检测后停止"""
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.AUTO_STOP,
        )
        detector = DoomLoopDetector(config)

        @detector.wrap
        async def call_tool(tool_name, args):
            return "result"

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        with pytest.raises(DoomLoopError):
            await call_tool("search", {"query": "test"})

    @pytest.mark.asyncio
    async def test_wrap_preserves_function_name(self):
        """测试装饰器保留函数名"""
        detector = DoomLoopDetector()

        @detector.wrap
        async def my_tool(tool_name, args):
            """My tool docstring"""
            return "result"

        assert my_tool.__name__ == "my_tool"
        assert my_tool.__doc__ == "My tool docstring"


class TestDoomLoopDetectorHistory:
    """Doom Loop 检测器历史测试"""

    def test_get_call_history(self):
        """测试获取调用历史"""
        detector = DoomLoopDetector()

        detector.check_call("search", {"query": "test1"})
        detector.check_call("search", {"query": "test2"})
        detector.check_call("read", {"file": "test.txt"})

        history = detector.get_call_history()
        assert len(history) == 3

    def test_get_call_history_filtered(self):
        """测试获取过滤后的调用历史"""
        detector = DoomLoopDetector()

        detector.check_call("search", {"query": "test1"})
        detector.check_call("search", {"query": "test2"})
        detector.check_call("read", {"file": "test.txt"})

        history = detector.get_call_history(tool_name="search")
        assert len(history) == 2
        assert all(k[0] == "search" for k in history.keys())

    def test_get_suspicious_tools(self):
        """测试获取可疑工具"""
        config = DoomLoopConfig(max_repeated_calls=4)
        detector = DoomLoopDetector(config)

        # 接近阈值的调用
        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        suspicious = detector.get_suspicious_tools()
        assert len(suspicious) > 0
        assert suspicious[0]["tool_name"] == "search"
        assert suspicious[0]["call_count"] == 3

    def test_clear_history(self):
        """测试清除历史"""
        detector = DoomLoopDetector()

        detector.check_call("search", {"query": "test"})
        detector.check_call("read", {"file": "test.txt"})

        detector.clear_history(tool_name="search")

        history = detector.get_call_history()
        assert len(history) == 1
        assert list(history.keys())[0][0] == "read"

    def test_clear_all_history(self):
        """测试清除所有历史"""
        detector = DoomLoopDetector()

        detector.check_call("search", {"query": "test"})
        detector.check_call("read", {"file": "test.txt"})

        detector.clear_history()

        history = detector.get_call_history()
        assert len(history) == 0

    def test_reset(self):
        """测试重置"""
        detector = DoomLoopDetector()

        detector.check_call("search", {"query": "test"})
        detector.check_call("read", {"file": "test.txt"})

        detector.reset()

        history = detector.get_call_history()
        assert len(history) == 0


class TestDoomLoopDetectorToDict:
    """Doom Loop 检测器序列化测试"""

    def test_to_dict(self):
        """测试导出为字典"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        data = detector.to_dict()

        assert data["config"]["max_repeated_calls"] == 3
        assert data["history_size"] == 2
        assert data["unique_calls"] == 1


class TestDoomLoopManager:
    """Doom Loop 管理器测试"""

    def test_get_or_create(self):
        """测试获取或创建"""
        manager = DoomLoopManager()

        detector1 = manager.get_or_create("workflow1")
        detector2 = manager.get_or_create("workflow1")  # 同一个实例
        detector3 = manager.get_or_create("workflow2")  # 不同实例

        assert detector1 is detector2
        assert detector1 is not detector3

    def test_get(self):
        """测试获取"""
        manager = DoomLoopManager()

        manager.get_or_create("test")
        assert manager.get("test") is not None
        assert manager.get("nonexistent") is None

    def test_remove(self):
        """测试移除"""
        manager = DoomLoopManager()

        manager.get_or_create("test")
        assert manager.remove("test") is True
        assert manager.get("test") is None
        assert manager.remove("nonexistent") is False

    def test_clear_all(self):
        """测试清除所有"""
        manager = DoomLoopManager()

        detector1 = manager.get_or_create("test1")
        detector2 = manager.get_or_create("test2")

        detector1.check_call("search", {"query": "test"})
        detector2.check_call("read", {"file": "test.txt"})

        manager.clear_all()

        assert len(detector1.get_call_history()) == 0
        assert len(detector2.get_call_history()) == 0

    def test_reset_all(self):
        """测试重置所有"""
        manager = DoomLoopManager()

        detector1 = manager.get_or_create("test1")
        detector2 = manager.get_or_create("test2")

        detector1.check_call("search", {"query": "test"})
        detector2.check_call("read", {"file": "test.txt"})

        manager.reset_all()

        assert len(detector1.get_call_history()) == 0
        assert len(detector2.get_call_history()) == 0

    def test_get_all_suspicious(self):
        """测试获取所有可疑工具"""
        manager = DoomLoopManager()

        detector = manager.get_or_create("test", DoomLoopConfig(max_repeated_calls=4))
        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})
        detector.check_call("search", {"query": "test"})

        suspicious = manager.get_all_suspicious()
        assert "test" in suspicious
        assert len(suspicious["test"]) > 0


class TestGlobalFunctions:
    """全局函数测试"""

    def test_get_doom_loop_detector(self):
        """测试获取全局检测器"""
        # 清理全局管理器
        manager = get_doom_loop_manager()
        manager.remove("global_test")

        detector = get_doom_loop_detector("global_test")
        assert detector is not None

    def test_get_doom_loop_manager(self):
        """测试获取全局管理器"""
        manager = get_doom_loop_manager()
        assert isinstance(manager, DoomLoopManager)


class TestDoomLoopIntegration:
    """Doom Loop 集成测试"""

    @pytest.mark.asyncio
    async def test_agent_loop_detection(self):
        """测试 Agent 循环检测"""
        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.AUTO_STOP,
        )
        detector = DoomLoopDetector(config)

        # 模拟 Agent 反复调用同一工具
        async def agent_loop():
            for _ in range(5):
                detection = detector.check_call("search", {"query": "same query"})
                if detection.detected:
                    raise DoomLoopError(detection)
            return "completed"

        with pytest.raises(DoomLoopError) as exc_info:
            await agent_loop()

        assert exc_info.value.detection.call_count == 3

    @pytest.mark.asyncio
    async def test_workflow_loop_detection(self):
        """测试工作流循环检测"""
        manager = DoomLoopManager()

        # 模拟工作流中的多个 Agent
        detector1 = manager.get_or_create("workflow1", DoomLoopConfig(max_repeated_calls=3))
        detector2 = manager.get_or_create("workflow1", DoomLoopConfig(max_repeated_calls=3))

        # Agent 1 和 Agent 2 使用相同的检测器
        detector1.check_call("tool_a", {"param": "value"})
        detector1.check_call("tool_a", {"param": "value"})

        # 第三次调用触发检测
        detection = detector2.check_call("tool_a", {"param": "value"})
        assert detection.detected

    @pytest.mark.asyncio
    async def test_prevention_with_different_args(self):
        """测试不同参数不会误触发"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 模拟正常的不同参数调用
        results = []
        for i in range(10):
            detection = detector.check_call("search", {"query": f"query_{i}"})
            results.append(detection.detected)

        # 不应该有任何检测触发
        assert not any(results)

    @pytest.mark.asyncio
    async def test_detection_with_user_interaction(self):
        """测试带用户交互的检测"""
        user_responses = []

        def mock_ask_user(detection: DoomLoopDetection) -> bool:
            user_responses.append(detection)
            # 用户选择继续
            return True

        config = DoomLoopConfig(
            max_repeated_calls=3,
            action=DoomLoopAction.ASK_USER,
        )
        detector = DoomLoopDetector(config, on_detection=mock_ask_user)

        # 模拟调用
        for _ in range(5):
            result = await detector.check_and_handle("search", {"query": "test"})
            if not result:
                break

        # 应该询问了用户
        assert len(user_responses) > 0
        assert user_responses[0].detected is True

    @pytest.mark.asyncio
    async def test_complex_tool_args(self):
        """测试复杂参数的检测"""
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 复杂嵌套参数
        complex_args = {
            "nested": {
                "deep": {
                    "value": [1, 2, 3],
                    "text": "hello",
                },
            },
            "list": [{"a": 1}, {"b": 2}],
        }

        # 相同复杂参数调用 3 次
        detector.check_call("complex_tool", complex_args)
        detector.check_call("complex_tool", complex_args)
        detection = detector.check_call("complex_tool", complex_args)

        assert detection.detected

        # 不同复杂参数
        different_args = complex_args.copy()
        different_args["nested"]["deep"]["value"] = [4, 5, 6]

        detector.check_call("complex_tool", different_args)
        detector.check_call("complex_tool", different_args)
        detection = detector.check_call("complex_tool", different_args)

        assert detection.detected

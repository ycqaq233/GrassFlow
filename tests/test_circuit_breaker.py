"""
熔断器（Circuit Breaker）测试
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerManager,
    CircuitState,
    CircuitBreakerOpenError,
    CircuitBreakerTimeoutError,
    get_circuit_breaker,
    get_circuit_breaker_manager,
)


class TestCircuitBreakerConfig:
    """熔断器配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 3
        assert config.cooldown_period == 60.0
        assert config.half_open_max_attempts == 1
        assert config.success_threshold == 1
        assert config.timeout is None

    def test_custom_config(self):
        """测试自定义配置"""
        config = CircuitBreakerConfig(
            failure_threshold=5,
            cooldown_period=30.0,
            timeout=10.0,
        )
        assert config.failure_threshold == 5
        assert config.cooldown_period == 30.0
        assert config.timeout == 10.0


class TestCircuitBreakerState:
    """熔断器状态测试"""

    def test_initial_state_closed(self):
        """测试初始状态为关闭"""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open
        assert not breaker.is_half_open

    def test_state_transition_to_open(self):
        """测试状态转换到打开"""
        breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

        # 记录 3 次失败
        for _ in range(3):
            breaker.record_failure(Exception("test error"))

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    def test_state_transition_to_half_open(self):
        """测试状态转换到半开"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            cooldown_period=0.1,  # 0.1 秒冷却期
        )
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))
        assert breaker.is_open

        # 等待冷却期结束
        time.sleep(0.15)

        # 检查状态应该转为半开
        breaker.check_state()
        assert breaker.is_half_open

    def test_state_transition_half_open_to_closed(self):
        """测试半开状态成功后回到关闭"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            cooldown_period=0.1,
        )
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))

        # 等待冷却期
        time.sleep(0.15)
        breaker.check_state()

        # 半开状态下成功
        breaker.record_success()
        assert breaker.is_closed

    def test_state_transition_half_open_to_open(self):
        """测试半开状态下失败回到打开"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            cooldown_period=0.1,
        )
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))

        # 等待冷却期
        time.sleep(0.15)
        breaker.check_state()

        # 半开状态下失败
        breaker.record_failure(Exception("error"))
        assert breaker.is_open

    def test_consecutive_failures_reset_on_success(self):
        """测试成功后重置连续失败计数"""
        breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

        # 2 次失败
        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))
        assert breaker.stats.consecutive_failures == 2

        # 1 次成功
        breaker.record_success()
        assert breaker.stats.consecutive_failures == 0
        assert breaker.is_closed

    def test_check_state_raises_when_open(self):
        """测试打开状态下检查状态抛出异常"""
        config = CircuitBreakerConfig(failure_threshold=2, cooldown_period=60.0)
        breaker = CircuitBreaker("test", config)

        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            breaker.check_state()

        assert exc_info.value.breaker_name == "test"
        assert exc_info.value.cooldown_remaining > 0

    def test_state_change_callback(self):
        """测试状态变化回调"""
        callback = MagicMock()
        breaker = CircuitBreaker(
            "test",
            CircuitBreakerConfig(failure_threshold=2),
            on_state_change=callback,
        )

        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))

        callback.assert_called_with("test", CircuitState.CLOSED, CircuitState.OPEN)


class TestCircuitBreakerExecute:
    """熔断器执行测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """测试成功执行"""
        breaker = CircuitBreaker("test")

        async def success_func():
            return "success"

        result = await breaker.execute(success_func)
        assert result == "success"
        assert breaker.stats.total_successes == 1

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        """测试失败执行"""
        breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

        async def fail_func():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            await breaker.execute(fail_func)

        assert breaker.stats.total_failures == 1

    @pytest.mark.asyncio
    async def test_execute_open_circuit(self):
        """测试熔断状态下执行"""
        config = CircuitBreakerConfig(failure_threshold=2, cooldown_period=60.0)
        breaker = CircuitBreaker("test", config)

        # 触发熔断
        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))

        async def any_func():
            return "result"

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.execute(any_func)

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """测试超时执行"""
        config = CircuitBreakerConfig(timeout=0.1)
        breaker = CircuitBreaker("test", config)

        async def slow_func():
            await asyncio.sleep(1)
            return "result"

        with pytest.raises(CircuitBreakerTimeoutError):
            await breaker.execute(slow_func)

    @pytest.mark.asyncio
    async def test_protect_decorator(self):
        """测试装饰器"""
        breaker = CircuitBreaker("test")

        @breaker.protect
        async def protected_func(x, y):
            return x + y

        result = await protected_func(1, 2)
        assert result == 3

    @pytest.mark.asyncio
    async def test_context_manager_success(self):
        """测试上下文管理器成功"""
        breaker = CircuitBreaker("test")

        async with breaker:
            pass  # 成功

        assert breaker.stats.total_successes == 1

    @pytest.mark.asyncio
    async def test_context_manager_failure(self):
        """测试上下文管理器失败"""
        breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

        with pytest.raises(ValueError):
            async with breaker:
                raise ValueError("test error")

        assert breaker.stats.total_failures == 1


class TestCircuitBreakerManager:
    """熔断器管理器测试"""

    def test_get_or_create(self):
        """测试获取或创建"""
        manager = CircuitBreakerManager()

        breaker1 = manager.get_or_create("service1")
        breaker2 = manager.get_or_create("service1")  # 同一个实例
        breaker3 = manager.get_or_create("service2")  # 不同实例

        assert breaker1 is breaker2
        assert breaker1 is not breaker3

    def test_get(self):
        """测试获取"""
        manager = CircuitBreakerManager()

        manager.get_or_create("test")
        assert manager.get("test") is not None
        assert manager.get("nonexistent") is None

    def test_remove(self):
        """测试移除"""
        manager = CircuitBreakerManager()

        manager.get_or_create("test")
        assert manager.remove("test") is True
        assert manager.get("test") is None
        assert manager.remove("nonexistent") is False

    def test_reset_all(self):
        """测试重置所有"""
        manager = CircuitBreakerManager()

        breaker1 = manager.get_or_create("test1")
        breaker2 = manager.get_or_create("test2")

        breaker1.record_failure(Exception("error"))
        breaker2.record_failure(Exception("error"))

        manager.reset_all()

        assert breaker1.stats.consecutive_failures == 0
        assert breaker2.stats.consecutive_failures == 0

    def test_get_all_stats(self):
        """测试获取所有统计"""
        manager = CircuitBreakerManager()

        manager.get_or_create("test1")
        manager.get_or_create("test2")

        stats = manager.get_all_stats()
        assert "test1" in stats
        assert "test2" in stats

    def test_get_open_breakers(self):
        """测试获取打开的熔断器"""
        manager = CircuitBreakerManager()

        breaker = manager.get_or_create("test", CircuitBreakerConfig(failure_threshold=2))
        breaker.record_failure(Exception("error"))
        breaker.record_failure(Exception("error"))

        open_breakers = manager.get_open_breakers()
        assert "test" in open_breakers


class TestGlobalFunctions:
    """全局函数测试"""

    def test_get_circuit_breaker(self):
        """测试获取全局熔断器"""
        # 清理全局管理器
        manager = get_circuit_breaker_manager()
        manager.remove("global_test")

        breaker = get_circuit_breaker("global_test")
        assert breaker is not None
        assert breaker.name == "global_test"

    def test_get_circuit_breaker_manager(self):
        """测试获取全局管理器"""
        manager = get_circuit_breaker_manager()
        assert isinstance(manager, CircuitBreakerManager)


class TestCircuitBreakerIntegration:
    """熔断器集成测试"""

    @pytest.mark.asyncio
    async def test_full_circuit_lifecycle(self):
        """测试完整的熔断器生命周期"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            cooldown_period=0.2,
        )
        breaker = CircuitBreaker("integration_test", config)

        # 模拟不稳定的外部服务
        call_count = 0

        async def unstable_service():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionError("Service unavailable")
            return "success"

        # 前 3 次调用失败，触发熔断
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await breaker.execute(unstable_service)

        assert breaker.is_open

        # 熔断期间，调用被拒绝
        with pytest.raises(CircuitBreakerOpenError):
            await breaker.execute(unstable_service)

        # 等待冷却期结束
        time.sleep(0.25)

        # 半开状态下，调用成功
        result = await breaker.execute(unstable_service)
        assert result == "success"
        assert breaker.is_closed

    @pytest.mark.asyncio
    async def test_cascading_failure_prevention(self):
        """测试防止级联故障"""
        # 创建两个相互依赖的服务
        service_a_breaker = get_circuit_breaker(
            "service_a",
            CircuitBreakerConfig(failure_threshold=2, cooldown_period=0.1),
        )
        service_b_breaker = get_circuit_breaker(
            "service_b",
            CircuitBreakerConfig(failure_threshold=2, cooldown_period=0.1),
        )

        async def service_a():
            raise ConnectionError("Service A down")

        async def service_b():
            # Service B 依赖 Service A
            try:
                await service_a_breaker.execute(service_a)
            except (ConnectionError, CircuitBreakerOpenError):
                # Service A 失败，Service B 也应该失败
                raise ConnectionError("Service B failed due to Service A")

        # 触发 Service A 熔断
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await service_a_breaker.execute(service_a)

        assert service_a_breaker.is_open

        # Service B 调用时，Service A 已经熔断，快速失败
        with pytest.raises(ConnectionError):
            await service_b_breaker.execute(service_b)

        # 清理
        manager = get_circuit_breaker_manager()
        manager.remove("service_a")
        manager.remove("service_b")

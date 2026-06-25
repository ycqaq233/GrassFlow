"""
GrassFlow 熔断器（Circuit Breaker）

参考 Hermes Agent 的熔断器机制，提供：
- 连续 N 次失败触发熔断
- 冷却期后半开探测
- 防止级联故障

状态机：
    CLOSED (正常) --[连续 N 次失败]--> OPEN (熔断)
    OPEN --[冷却期结束]--> HALF_OPEN (半开探测)
    HALF_OPEN --[成功]--> CLOSED
    HALF_OPEN --[失败]--> OPEN
"""

import time
import asyncio
from enum import Enum
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field
from collections import defaultdict


class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"         # 正常状态，允许请求通过
    OPEN = "open"             # 熔断状态，拒绝所有请求
    HALF_OPEN = "half_open"   # 半开状态，允许探测请求


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 3        # 触发熔断的连续失败次数
    cooldown_period: float = 60.0     # 熔断冷却期（秒）
    half_open_max_attempts: int = 1   # 半开状态下的最大探测次数
    success_threshold: int = 1        # 从半开恢复到关闭所需的成功次数
    timeout: Optional[float] = None   # 单次操作超时时间（秒）


@dataclass
class CircuitBreakerStats:
    """熔断器统计信息"""
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state_changes: int = 0
    half_open_attempts: int = 0
    half_open_successes: int = 0


class CircuitBreakerError(Exception):
    """熔断器错误基类"""

    def __init__(self, message: str, breaker_name: str):
        super().__init__(message)
        self.breaker_name = breaker_name


class CircuitBreakerOpenError(CircuitBreakerError):
    """熔断器处于打开状态时的错误"""

    def __init__(self, breaker_name: str, cooldown_remaining: float):
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker '{breaker_name}' is open. "
            f"Cooldown remaining: {cooldown_remaining:.1f}s",
            breaker_name,
        )


class CircuitBreakerTimeoutError(CircuitBreakerError):
    """操作超时错误"""

    def __init__(self, breaker_name: str, timeout: float):
        self.timeout = timeout
        super().__init__(
            f"Operation timed out after {timeout}s (breaker: '{breaker_name}')",
            breaker_name,
        )


class CircuitBreaker:
    """
    熔断器实现

    用法：
        breaker = CircuitBreaker("my_service", CircuitBreakerConfig(failure_threshold=3))

        # 方式 1: 使用装饰器
        @breaker.protect
        async def my_function():
            ...

        # 方式 2: 使用上下文管理器
        async with breaker:
            await do_something()

        # 方式 3: 手动调用
        try:
            breaker.check_state()
            result = await do_something()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure(e)
            raise
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        on_state_change: Optional[Callable[[str, CircuitState, CircuitState], None]] = None,
    ):
        """
        初始化熔断器

        Args:
            name: 熔断器名称
            config: 配置
            on_state_change: 状态变化回调函数 (name, old_state, new_state) -> None
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._stats = CircuitBreakerStats()
        self._last_state_change_time = time.time()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        return self._state

    @property
    def stats(self) -> CircuitBreakerStats:
        """获取统计信息"""
        return self._stats

    @property
    def is_closed(self) -> bool:
        """是否处于关闭（正常）状态"""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """是否处于打开（熔断）状态"""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """是否处于半开状态"""
        return self._state == CircuitState.HALF_OPEN

    def _change_state(self, new_state: CircuitState) -> None:
        """改变状态"""
        old_state = self._state
        if old_state == new_state:
            return

        self._state = new_state
        self._last_state_change_time = time.time()
        self._stats.state_changes += 1

        if new_state == CircuitState.HALF_OPEN:
            self._stats.half_open_attempts = 0
            self._stats.half_open_successes = 0

        if self.on_state_change:
            try:
                self.on_state_change(self.name, old_state, new_state)
            except Exception:
                pass  # 忽略回调错误

    def _get_cooldown_remaining(self) -> float:
        """获取冷却期剩余时间"""
        if self._state != CircuitState.OPEN:
            return 0.0

        elapsed = time.time() - self._last_state_change_time
        remaining = self.config.cooldown_period - elapsed
        return max(0.0, remaining)

    def _should_attempt_reset(self) -> bool:
        """是否应该尝试重置（冷却期是否结束）"""
        if self._state != CircuitState.OPEN:
            return False
        return self._get_cooldown_remaining() <= 0

    def check_state(self) -> None:
        """
        检查熔断器状态，如果处于打开状态则抛出异常

        Raises:
            CircuitBreakerOpenError: 熔断器处于打开状态
        """
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._change_state(CircuitState.HALF_OPEN)
            else:
                remaining = self._get_cooldown_remaining()
                raise CircuitBreakerOpenError(self.name, remaining)

    def record_success(self) -> None:
        """记录成功"""
        self._stats.total_requests += 1
        self._stats.total_successes += 1
        self._stats.consecutive_failures = 0
        self._stats.last_success_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._stats.half_open_successes += 1
            if self._stats.half_open_successes >= self.config.success_threshold:
                self._change_state(CircuitState.CLOSED)

    def record_failure(self, error: Optional[Exception] = None) -> None:
        """
        记录失败

        Args:
            error: 导致失败的异常
        """
        self._stats.total_requests += 1
        self._stats.total_failures += 1
        self._stats.consecutive_failures += 1
        self._stats.last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态下的失败，立即回到打开状态
            self._change_state(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            # 关闭状态下，检查是否达到熔断阈值
            if self._stats.consecutive_failures >= self.config.failure_threshold:
                self._change_state(CircuitState.OPEN)

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args,
        **kwargs,
    ) -> Any:
        """
        执行受保护的异步函数

        Args:
            func: 要执行的异步函数
            *args: 函数参数
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            CircuitBreakerOpenError: 熔断器处于打开状态
            CircuitBreakerTimeoutError: 操作超时
        """
        self.check_state()

        try:
            if self.config.timeout:
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.timeout,
                )
            else:
                result = await func(*args, **kwargs)

            self.record_success()
            return result

        except asyncio.TimeoutError:
            self.record_failure(CircuitBreakerTimeoutError(self.name, self.config.timeout))
            raise CircuitBreakerTimeoutError(self.name, self.config.timeout)

        except Exception as e:
            self.record_failure(e)
            raise

    def protect(self, func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        """
        装饰器：保护异步函数

        用法：
            @breaker.protect
            async def my_function():
                ...
        """
        async def wrapper(*args, **kwargs):
            return await self.execute(func, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.check_state()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if exc_type is not None:
            self.record_failure(exc_val)
        else:
            self.record_success()
        return False  # 不抑制异常

    def reset(self) -> None:
        """手动重置熔断器到关闭状态"""
        self._change_state(CircuitState.CLOSED)
        self._stats.consecutive_failures = 0

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "name": self.name,
            "state": self._state.value,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "cooldown_period": self.config.cooldown_period,
                "half_open_max_attempts": self.config.half_open_max_attempts,
                "success_threshold": self.config.success_threshold,
                "timeout": self.config.timeout,
            },
            "stats": {
                "total_requests": self._stats.total_requests,
                "total_successes": self._stats.total_successes,
                "total_failures": self._stats.total_failures,
                "consecutive_failures": self._stats.consecutive_failures,
                "last_failure_time": self._stats.last_failure_time,
                "last_success_time": self._stats.last_success_time,
                "state_changes": self._stats.state_changes,
            },
            "cooldown_remaining": self._get_cooldown_remaining(),
        }


class CircuitBreakerManager:
    """
    熔断器管理器

    管理多个熔断器实例
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        on_state_change: Optional[Callable[[str, CircuitState, CircuitState], None]] = None,
    ) -> CircuitBreaker:
        """
        获取或创建熔断器

        Args:
            name: 熔断器名称
            config: 配置（仅在创建时使用）
            on_state_change: 状态变化回调

        Returns:
            CircuitBreaker 实例
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                config=config,
                on_state_change=on_state_change,
            )
        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """获取熔断器"""
        return self._breakers.get(name)

    def remove(self, name: str) -> bool:
        """移除熔断器"""
        if name in self._breakers:
            del self._breakers[name]
            return True
        return False

    def reset_all(self) -> None:
        """重置所有熔断器"""
        for breaker in self._breakers.values():
            breaker.reset()

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器的统计信息"""
        return {name: breaker.to_dict() for name, breaker in self._breakers.items()}

    def get_open_breakers(self) -> list[str]:
        """获取所有处于打开状态的熔断器名称"""
        return [
            name for name, breaker in self._breakers.items()
            if breaker.is_open
        ]


# ============ 全局熔断器管理器 ============

_global_manager = CircuitBreakerManager()


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None,
    on_state_change: Optional[Callable[[str, CircuitState, CircuitState], None]] = None,
) -> CircuitBreaker:
    """
    获取或创建全局熔断器

    Args:
        name: 熔断器名称
        config: 配置
        on_state_change: 状态变化回调

    Returns:
        CircuitBreaker 实例
    """
    return _global_manager.get_or_create(name, config, on_state_change)


def get_circuit_breaker_manager() -> CircuitBreakerManager:
    """获取全局熔断器管理器"""
    return _global_manager

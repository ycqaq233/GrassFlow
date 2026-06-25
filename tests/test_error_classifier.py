"""
GrassFlow 错误分类器测试

测试结构化错误分类、重试逻辑等功能
"""

import sys
import os
import importlib.util
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# 直接加载模块，避免触发 core/__init__.py 中的 tool_registry 导入问题
_spec = importlib.util.spec_from_file_location(
    "error_classifier",
    os.path.join(os.path.dirname(__file__), "..", "core", "error_classifier.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ErrorCategory = _mod.ErrorCategory
ErrorSeverity = _mod.ErrorSeverity
ErrorContext = _mod.ErrorContext
RetryPolicy = _mod.RetryPolicy
GrassFlowError = _mod.GrassFlowError
RateLimitError = _mod.RateLimitError
AuthExpiredError = _mod.AuthExpiredError
ContextOverflowError = _mod.ContextOverflowError
ProviderError = _mod.ProviderError
NetworkError = _mod.NetworkError
ToolError = _mod.ToolError
PermissionDeniedError = _mod.PermissionDeniedError
TimeoutError = _mod.TimeoutError
ValidationError = _mod.ValidationError
ErrorClassifier = _mod.ErrorClassifier
RetryExecutor = _mod.RetryExecutor
classify_error = _mod.classify_error
create_retry_executor = _mod.create_retry_executor
DEFAULT_RETRY_POLICIES = _mod.DEFAULT_RETRY_POLICIES
DEFAULT_SEVERITY_MAP = _mod.DEFAULT_SEVERITY_MAP


# ============ 枚举测试 ============

class TestEnums:
    """测试枚举类型"""

    def test_error_category_values(self):
        """测试 ErrorCategory 枚举值"""
        assert ErrorCategory.RATE_LIMITED == "rate_limited"
        assert ErrorCategory.AUTH_EXPIRED == "auth_expired"
        assert ErrorCategory.CONTEXT_OVERFLOW == "context_overflow"
        assert ErrorCategory.PROVIDER_ERROR == "provider_error"
        assert ErrorCategory.NETWORK_ERROR == "network_error"
        assert ErrorCategory.TOOL_ERROR == "tool_error"
        assert ErrorCategory.PERMISSION_DENIED == "permission_denied"
        assert ErrorCategory.TIMEOUT == "timeout"
        assert ErrorCategory.VALIDATION_ERROR == "validation_error"
        assert ErrorCategory.UNKNOWN == "unknown"

    def test_error_severity_values(self):
        """测试 ErrorSeverity 枚举值"""
        assert ErrorSeverity.LOW == "low"
        assert ErrorSeverity.MEDIUM == "medium"
        assert ErrorSeverity.HIGH == "high"
        assert ErrorSeverity.CRITICAL == "critical"


# ============ 错误上下文测试 ============

class TestErrorContext:
    """测试 ErrorContext"""

    def test_default_context(self):
        """测试默认上下文"""
        ctx = ErrorContext()
        assert ctx.agent_name is None
        assert ctx.workflow_id is None
        assert ctx.attempt == 1
        assert ctx.max_attempts == 1
        assert ctx.provider is None
        assert ctx.model is None
        assert ctx.extra == {}

    def test_custom_context(self):
        """测试自定义上下文"""
        ctx = ErrorContext(
            agent_name="test_agent",
            workflow_id="wf_001",
            attempt=2,
            max_attempts=5,
            provider="openai",
            model="gpt-4",
            extra={"key": "value"},
        )
        assert ctx.agent_name == "test_agent"
        assert ctx.workflow_id == "wf_001"
        assert ctx.attempt == 2
        assert ctx.max_attempts == 5
        assert ctx.provider == "openai"
        assert ctx.model == "gpt-4"
        assert ctx.extra == {"key": "value"}


# ============ 重试策略测试 ============

class TestRetryPolicy:
    """测试 RetryPolicy"""

    def test_default_policy(self):
        """测试默认策略"""
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.exponential_base == 2.0
        assert policy.jitter is True

    def test_custom_policy(self):
        """测试自定义策略"""
        policy = RetryPolicy(
            max_retries=5,
            base_delay=2.0,
            max_delay=120.0,
            exponential_base=3.0,
            jitter=False,
        )
        assert policy.max_retries == 5
        assert policy.base_delay == 2.0
        assert policy.max_delay == 120.0
        assert policy.exponential_base == 3.0
        assert policy.jitter is False

    def test_default_retry_policies(self):
        """测试默认重试策略映射"""
        assert ErrorCategory.RATE_LIMITED in DEFAULT_RETRY_POLICIES
        assert ErrorCategory.AUTH_EXPIRED in DEFAULT_RETRY_POLICIES
        assert ErrorCategory.CONTEXT_OVERFLOW in DEFAULT_RETRY_POLICIES
        assert ErrorCategory.PROVIDER_ERROR in DEFAULT_RETRY_POLICIES
        assert ErrorCategory.NETWORK_ERROR in DEFAULT_RETRY_POLICIES

    def test_context_overflow_no_retry(self):
        """测试上下文溢出不重试"""
        policy = DEFAULT_RETRY_POLICIES[ErrorCategory.CONTEXT_OVERFLOW]
        assert policy.max_retries == 0

    def test_permission_denied_no_retry(self):
        """测试权限拒绝不重试"""
        policy = DEFAULT_RETRY_POLICIES[ErrorCategory.PERMISSION_DENIED]
        assert policy.max_retries == 0


# ============ 基础异常测试 ============

class TestGrassFlowError:
    """测试 GrassFlowError 基础异常"""

    def test_basic_error(self):
        """测试基础错误"""
        error = GrassFlowError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.category == ErrorCategory.UNKNOWN
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.context is not None
        assert error.original_error is None

    def test_error_with_category(self):
        """测试带类别的错误"""
        error = GrassFlowError(
            "Rate limit",
            category=ErrorCategory.RATE_LIMITED,
        )
        assert error.category == ErrorCategory.RATE_LIMITED
        assert error.severity == ErrorSeverity.LOW

    def test_error_with_severity(self):
        """测试带严重程度的错误"""
        error = GrassFlowError(
            "Critical error",
            severity=ErrorSeverity.CRITICAL,
        )
        assert error.severity == ErrorSeverity.CRITICAL

    def test_error_with_context(self):
        """测试带上下文的错误"""
        ctx = ErrorContext(agent_name="test_agent")
        error = GrassFlowError("Error", context=ctx)
        assert error.context.agent_name == "test_agent"

    def test_error_with_original(self):
        """测试带原始错误的错误"""
        original = ValueError("original")
        error = GrassFlowError("wrapped", original_error=original)
        assert error.original_error is original

    def test_is_retryable(self):
        """测试是否可重试"""
        # 可重试
        error = GrassFlowError(
            "Rate limit",
            category=ErrorCategory.RATE_LIMITED,
        )
        assert error.is_retryable() is True

        # 不可重试
        error = GrassFlowError(
            "Context overflow",
            category=ErrorCategory.CONTEXT_OVERFLOW,
        )
        assert error.is_retryable() is False

    def test_get_retry_delay(self):
        """测试获取重试延迟"""
        error = GrassFlowError(
            "Test",
            category=ErrorCategory.RATE_LIMITED,
        )

        # 第一次重试
        delay = error.get_retry_delay(0)
        assert delay > 0

        # 延迟应该随尝试次数增加（考虑抖动，使用多次采样）
        delays_0 = [error.get_retry_delay(0) for _ in range(10)]
        delays_1 = [error.get_retry_delay(1) for _ in range(10)]
        avg_0 = sum(delays_0) / len(delays_0)
        avg_1 = sum(delays_1) / len(delays_1)
        assert avg_1 >= avg_0 * 0.8  # 允许 20% 的抖动容差

    def test_to_dict(self):
        """测试转换为字典"""
        ctx = ErrorContext(agent_name="test")
        error = GrassFlowError(
            "Test error",
            category=ErrorCategory.RATE_LIMITED,
            context=ctx,
        )

        d = error.to_dict()
        assert d["error_type"] == "GrassFlowError"
        assert d["message"] == "Test error"
        assert d["category"] == "rate_limited"
        assert d["severity"] == "low"
        assert d["is_retryable"] is True
        assert d["context"]["agent_name"] == "test"


# ============ 具体错误类型测试 ============

class TestSpecificErrors:
    """测试具体错误类型"""

    def test_rate_limit_error(self):
        """测试速率限制错误"""
        error = RateLimitError("Too many requests", retry_after=30.0)
        assert error.category == ErrorCategory.RATE_LIMITED
        assert error.retry_after == 30.0
        assert error.get_retry_delay(0) == 30.0

    def test_rate_limit_error_without_retry_after(self):
        """测试没有 retry_after 的速率限制错误"""
        error = RateLimitError("Too many requests")
        delay = error.get_retry_delay(0)
        assert delay > 0

    def test_auth_expired_error(self):
        """测试认证过期错误"""
        error = AuthExpiredError("Token expired", provider="openai")
        assert error.category == ErrorCategory.AUTH_EXPIRED
        assert error.context.provider == "openai"

    def test_context_overflow_error(self):
        """测试上下文溢出错误"""
        error = ContextOverflowError(
            "Context too long",
            current_tokens=5000,
            max_tokens=4096,
        )
        assert error.category == ErrorCategory.CONTEXT_OVERFLOW
        assert error.current_tokens == 5000
        assert error.max_tokens == 4096
        assert error.is_retryable() is False

    def test_provider_error(self):
        """测试提供商错误"""
        error = ProviderError(
            "Server error",
            provider="anthropic",
            status_code=500,
        )
        assert error.category == ErrorCategory.PROVIDER_ERROR
        assert error.status_code == 500
        assert error.context.provider == "anthropic"

    def test_network_error(self):
        """测试网络错误"""
        error = NetworkError("Connection refused")
        assert error.category == ErrorCategory.NETWORK_ERROR

    def test_tool_error(self):
        """测试工具错误"""
        error = ToolError("Tool failed", tool_name="search")
        assert error.category == ErrorCategory.TOOL_ERROR
        assert error.tool_name == "search"
        assert error.context.extra["tool_name"] == "search"

    def test_permission_denied_error(self):
        """测试权限拒绝错误"""
        error = PermissionDeniedError("Access denied", resource="/api/admin")
        assert error.category == ErrorCategory.PERMISSION_DENIED
        assert error.resource == "/api/admin"
        assert error.is_retryable() is False

    def test_timeout_error(self):
        """测试超时错误"""
        error = TimeoutError("Request timed out", timeout_seconds=30.0)
        assert error.category == ErrorCategory.TIMEOUT
        assert error.timeout_seconds == 30.0

    def test_validation_error(self):
        """测试校验错误"""
        error = ValidationError("Invalid input", field="email")
        assert error.category == ErrorCategory.VALIDATION_ERROR
        assert error.field == "email"


# ============ 错误分类器测试 ============

class TestErrorClassifier:
    """测试 ErrorClassifier"""

    def test_classify_already_classified(self):
        """测试分类已经是 GrassFlowError 的错误"""
        original = RateLimitError("Rate limit")
        classified = ErrorClassifier.classify(original)
        assert classified is original

    def test_classify_rate_limit_by_message(self):
        """测试通过消息分类速率限制"""
        error = Exception("Rate limit exceeded")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.RATE_LIMITED

    def test_classify_rate_limit_by_429(self):
        """测试通过 429 状态码分类速率限制"""
        error = Exception("HTTP 429 Too Many Requests")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.RATE_LIMITED

    def test_classify_auth_by_message(self):
        """测试通过消息分类认证错误"""
        error = Exception("Invalid API key provided")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.AUTH_EXPIRED

    def test_classify_auth_by_401(self):
        """测试通过 401 状态码分类认证错误"""
        error = Exception("HTTP 401 Unauthorized")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.AUTH_EXPIRED

    def test_classify_context_overflow(self):
        """测试分类上下文溢出"""
        error = Exception("Context length exceeded maximum limit")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.CONTEXT_OVERFLOW

    def test_classify_network_error(self):
        """测试分类网络错误"""
        error = Exception("Connection refused")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.NETWORK_ERROR

    def test_classify_permission_by_403(self):
        """测试通过 403 状态码分类权限拒绝"""
        error = Exception("HTTP 403 Forbidden")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.PERMISSION_DENIED

    def test_classify_timeout(self):
        """测试分类超时"""
        error = Exception("Request timed out after 30 seconds")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.TIMEOUT

    def test_classify_by_exception_type_timeout(self):
        """测试通过异常类型分类超时"""
        error = TimeoutError("timed out")
        # Python 内置的 TimeoutError
        import builtins
        error = builtins.TimeoutError("timed out")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.TIMEOUT

    def test_classify_by_exception_type_connection(self):
        """测试通过异常类型分类连接错误"""
        error = ConnectionError("Connection refused")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.NETWORK_ERROR

    def test_classify_by_exception_type_permission(self):
        """测试通过异常类型分类权限错误"""
        error = PermissionError("Permission denied")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.PERMISSION_DENIED

    def test_classify_unknown_error(self):
        """测试分类未知错误"""
        error = Exception("Something completely unknown happened")
        classified = ErrorClassifier.classify(error)
        assert classified.category == ErrorCategory.UNKNOWN

    def test_classify_with_context(self):
        """测试带上下文的分类"""
        ctx = ErrorContext(agent_name="test_agent")
        error = Exception("Rate limit exceeded")
        classified = ErrorClassifier.classify(error, context=ctx)
        assert classified.context.agent_name == "test_agent"

    def test_extract_status_code_from_attribute(self):
        """测试从属性提取状态码"""
        error = Exception("Error")
        error.status_code = 429
        code = ErrorClassifier._extract_status_code(error)
        assert code == 429

    def test_extract_status_code_from_message(self):
        """测试从消息提取状态码"""
        error = Exception("Error 500 occurred")
        code = ErrorClassifier._extract_status_code(error)
        assert code == 500

    def test_extract_status_code_none(self):
        """测试无法提取状态码"""
        error = Exception("Some error")
        code = ErrorClassifier._extract_status_code(error)
        assert code is None


# ============ 重试执行器测试 ============

class TestRetryExecutor:
    """测试 RetryExecutor"""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """测试成功执行"""
        executor = RetryExecutor()
        mock_func = AsyncMock(return_value="success")

        result = await executor.execute(mock_func)
        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_retry_on_failure(self):
        """测试失败后重试"""
        executor = RetryExecutor(
            default_policy=RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)
        )

        # 前两次失败，第三次成功
        mock_func = AsyncMock(side_effect=[Exception("fail"), Exception("fail"), "success"])

        result = await executor.execute(mock_func)
        assert result == "success"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_no_retry_on_non_retryable(self):
        """测试不可重试错误不重试"""
        executor = RetryExecutor()
        mock_func = AsyncMock(
            side_effect=ContextOverflowError("Context too long")
        )

        with pytest.raises(ContextOverflowError):
            await executor.execute(mock_func)
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_max_retries_exceeded(self):
        """测试超过最大重试次数"""
        executor = RetryExecutor(
            default_policy=RetryPolicy(max_retries=2, base_delay=0.01, jitter=False)
        )

        mock_func = AsyncMock(side_effect=Exception("Rate limit exceeded"))

        with pytest.raises(RateLimitError):
            await executor.execute(mock_func)
        assert mock_func.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_execute_with_on_retry_callback(self):
        """测试重试回调"""
        retry_attempts = []

        def on_retry(attempt, error, delay):
            retry_attempts.append((attempt, error.category, delay))

        executor = RetryExecutor(
            default_policy=RetryPolicy(max_retries=2, base_delay=0.01, jitter=False),
            on_retry=on_retry,
        )

        mock_func = AsyncMock(side_effect=[Exception("Rate limit"), "success"])

        result = await executor.execute(mock_func)
        assert result == "success"
        assert len(retry_attempts) == 1
        assert retry_attempts[0][0] == 1
        assert retry_attempts[0][1] == ErrorCategory.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_execute_with_on_error_callback(self):
        """测试错误回调"""
        errors = []

        def on_error(error):
            errors.append(error)

        executor = RetryExecutor(
            default_policy=RetryPolicy(max_retries=1, base_delay=0.01, jitter=False),
            on_error=on_error,
        )

        mock_func = AsyncMock(side_effect=[Exception("Network error"), "success"])

        result = await executor.execute(mock_func)
        assert result == "success"
        assert len(errors) == 1
        assert errors[0].category == ErrorCategory.NETWORK_ERROR

    @pytest.mark.asyncio
    async def test_execute_with_context(self):
        """测试带上下文的执行"""
        ctx = ErrorContext(agent_name="test_agent")
        executor = RetryExecutor(
            default_policy=RetryPolicy(max_retries=1, base_delay=0.01, jitter=False)
        )

        mock_func = AsyncMock(side_effect=[Exception("fail"), "success"])

        result = await executor.execute(mock_func, context=ctx)
        assert result == "success"
        assert ctx.attempt == 2
        assert ctx.max_attempts == 2


# ============ 便捷函数测试 ============

class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_classify_error_function(self):
        """测试 classify_error 函数"""
        error = Exception("Rate limit exceeded")
        classified = classify_error(error)
        assert isinstance(classified, GrassFlowError)
        assert classified.category == ErrorCategory.RATE_LIMITED

    def test_classify_error_with_context(self):
        """测试带上下文的 classify_error"""
        ctx = ErrorContext(agent_name="test")
        error = Exception("Auth failed")
        classified = classify_error(error, context=ctx)
        assert classified.context.agent_name == "test"

    def test_create_retry_executor(self):
        """测试 create_retry_executor"""
        retry_attempts = []

        def on_retry(attempt, error, delay):
            retry_attempts.append(attempt)

        executor = create_retry_executor(
            max_retries=5,
            base_delay=0.1,
            on_retry=on_retry,
        )

        assert executor.default_policy.max_retries == 5
        assert executor.default_policy.base_delay == 0.1


# ============ 集成测试 ============

class TestIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_retry_flow(self):
        """测试完整的重试流程"""
        call_count = 0

        async def flaky_api():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Rate limit exceeded")
            return {"result": "success"}

        executor = RetryExecutor(
            default_policy=RetryPolicy(max_retries=5, base_delay=0.01, jitter=False)
        )

        ctx = ErrorContext(agent_name="api_caller")
        result = await executor.execute(flaky_api, context=ctx)

        assert result == {"result": "success"}
        assert call_count == 3
        assert ctx.attempt == 3
        assert ctx.max_attempts == 6  # 5 retries + 1 initial

    @pytest.mark.asyncio
    async def test_error_chain(self):
        """测试错误链"""
        original = ValueError("Invalid value")
        wrapped = GrassFlowError(
            "Validation failed",
            category=ErrorCategory.VALIDATION_ERROR,
            original_error=original,
        )

        d = wrapped.to_dict()
        assert d["original_error"] == "Invalid value"
        assert d["category"] == "validation_error"

    def test_severity_mapping(self):
        """测试严重程度映射"""
        assert DEFAULT_SEVERITY_MAP[ErrorCategory.RATE_LIMITED] == ErrorSeverity.LOW
        assert DEFAULT_SEVERITY_MAP[ErrorCategory.AUTH_EXPIRED] == ErrorSeverity.MEDIUM
        assert DEFAULT_SEVERITY_MAP[ErrorCategory.CONTEXT_OVERFLOW] == ErrorSeverity.HIGH
        assert DEFAULT_SEVERITY_MAP[ErrorCategory.PERMISSION_DENIED] == ErrorSeverity.HIGH

    def test_retry_policy_mapping(self):
        """测试重试策略映射"""
        # 速率限制应该有较多重试
        rate_policy = DEFAULT_RETRY_POLICIES[ErrorCategory.RATE_LIMITED]
        assert rate_policy.max_retries > 3

        # 上下文溢出不应该重试
        ctx_policy = DEFAULT_RETRY_POLICIES[ErrorCategory.CONTEXT_OVERFLOW]
        assert ctx_policy.max_retries == 0

        # 权限拒绝不应该重试
        perm_policy = DEFAULT_RETRY_POLICIES[ErrorCategory.PERMISSION_DENIED]
        assert perm_policy.max_retries == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

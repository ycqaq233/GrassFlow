"""
GrassFlow 结构化错误分类器

参考 Hermes Agent 的 FailoverReason 枚举，提供：
- 结构化错误分类
- 错误严重程度
- 自动重试逻辑
- 错误上下文信息
"""

from enum import Enum
from typing import Optional, Dict, Any, Type
from dataclasses import dataclass, field
import re
import traceback


# ============ 错误类别枚举 ============

class ErrorCategory(str, Enum):
    """错误类别枚举"""
    RATE_LIMITED = "rate_limited"           # 速率限制
    AUTH_EXPIRED = "auth_expired"           # 认证过期
    CONTEXT_OVERFLOW = "context_overflow"   # 上下文溢出
    PROVIDER_ERROR = "provider_error"       # 提供商错误
    NETWORK_ERROR = "network_error"         # 网络错误
    TOOL_ERROR = "tool_error"               # 工具错误
    PERMISSION_DENIED = "permission_denied" # 权限拒绝
    TIMEOUT = "timeout"                     # 超时
    VALIDATION_ERROR = "validation_error"   # 校验错误
    UNKNOWN = "unknown"                     # 未知错误


class ErrorSeverity(str, Enum):
    """错误严重程度"""
    LOW = "low"           # 低：可自动恢复
    MEDIUM = "medium"     # 中：需要重试
    HIGH = "high"         # 高：需要人工干预
    CRITICAL = "critical" # 严重：立即停止


# ============ 重试策略 ============

@dataclass
class RetryPolicy:
    """重试策略"""
    max_retries: int = 3              # 最大重试次数
    base_delay: float = 1.0           # 基础延迟（秒）
    max_delay: float = 60.0           # 最大延迟（秒）
    exponential_base: float = 2.0     # 指数退避基数
    jitter: bool = True               # 是否添加抖动


# 默认重试策略映射
DEFAULT_RETRY_POLICIES: Dict[ErrorCategory, RetryPolicy] = {
    ErrorCategory.RATE_LIMITED: RetryPolicy(
        max_retries=5,
        base_delay=2.0,
        max_delay=120.0,
        exponential_base=2.0,
        jitter=True,
    ),
    ErrorCategory.AUTH_EXPIRED: RetryPolicy(
        max_retries=1,  # 认证过期通常需要刷新 token，不频繁重试
        base_delay=1.0,
        max_delay=5.0,
        exponential_base=1.0,
        jitter=False,
    ),
    ErrorCategory.CONTEXT_OVERFLOW: RetryPolicy(
        max_retries=0,  # 上下文溢出无法通过重试解决
        base_delay=0.0,
        max_delay=0.0,
        exponential_base=1.0,
        jitter=False,
    ),
    ErrorCategory.PROVIDER_ERROR: RetryPolicy(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        exponential_base=2.0,
        jitter=True,
    ),
    ErrorCategory.NETWORK_ERROR: RetryPolicy(
        max_retries=4,
        base_delay=1.0,
        max_delay=60.0,
        exponential_base=2.0,
        jitter=True,
    ),
    ErrorCategory.TOOL_ERROR: RetryPolicy(
        max_retries=2,
        base_delay=0.5,
        max_delay=10.0,
        exponential_base=2.0,
        jitter=True,
    ),
    ErrorCategory.PERMISSION_DENIED: RetryPolicy(
        max_retries=0,  # 权限拒绝无法通过重试解决
        base_delay=0.0,
        max_delay=0.0,
        exponential_base=1.0,
        jitter=False,
    ),
    ErrorCategory.TIMEOUT: RetryPolicy(
        max_retries=3,
        base_delay=2.0,
        max_delay=60.0,
        exponential_base=2.0,
        jitter=True,
    ),
    ErrorCategory.VALIDATION_ERROR: RetryPolicy(
        max_retries=1,  # 校验错误可能是临时数据问题
        base_delay=0.5,
        max_delay=5.0,
        exponential_base=1.0,
        jitter=False,
    ),
    ErrorCategory.UNKNOWN: RetryPolicy(
        max_retries=2,
        base_delay=1.0,
        max_delay=30.0,
        exponential_base=2.0,
        jitter=True,
    ),
}


# ============ 错误严重程度映射 ============

DEFAULT_SEVERITY_MAP: Dict[ErrorCategory, ErrorSeverity] = {
    ErrorCategory.RATE_LIMITED: ErrorSeverity.LOW,
    ErrorCategory.AUTH_EXPIRED: ErrorSeverity.MEDIUM,
    ErrorCategory.CONTEXT_OVERFLOW: ErrorSeverity.HIGH,
    ErrorCategory.PROVIDER_ERROR: ErrorSeverity.MEDIUM,
    ErrorCategory.NETWORK_ERROR: ErrorSeverity.MEDIUM,
    ErrorCategory.TOOL_ERROR: ErrorSeverity.MEDIUM,
    ErrorCategory.PERMISSION_DENIED: ErrorSeverity.HIGH,
    ErrorCategory.TIMEOUT: ErrorSeverity.MEDIUM,
    ErrorCategory.VALIDATION_ERROR: ErrorSeverity.LOW,
    ErrorCategory.UNKNOWN: ErrorSeverity.MEDIUM,
}


# ============ 错误上下文 ============

@dataclass
class ErrorContext:
    """错误上下文信息"""
    agent_name: Optional[str] = None      # 发生错误的 Agent 名称
    workflow_id: Optional[str] = None     # 工作流 ID
    attempt: int = 1                      # 当前尝试次数
    max_attempts: int = 1                 # 最大尝试次数
    provider: Optional[str] = None        # LLM 提供商
    model: Optional[str] = None           # 模型名称
    extra: Dict[str, Any] = field(default_factory=dict)  # 额外信息


# ============ 基础异常类 ============

class GrassFlowError(Exception):
    """GrassFlow 基础异常类"""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: Optional[ErrorSeverity] = None,
        context: Optional[ErrorContext] = None,
        original_error: Optional[Exception] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity or DEFAULT_SEVERITY_MAP.get(category, ErrorSeverity.MEDIUM)
        self.context = context or ErrorContext()
        self.original_error = original_error
        self.retry_policy = retry_policy or DEFAULT_RETRY_POLICIES.get(category, RetryPolicy())

    def is_retryable(self) -> bool:
        """判断是否可重试"""
        return self.retry_policy.max_retries > 0

    def get_retry_delay(self, attempt: int) -> float:
        """获取重试延迟时间"""
        import random

        policy = self.retry_policy
        if attempt >= policy.max_retries:
            return 0.0

        # 指数退避
        delay = min(
            policy.base_delay * (policy.exponential_base ** attempt),
            policy.max_delay,
        )

        # 添加抖动
        if policy.jitter:
            delay = delay * (0.5 + random.random())

        return delay

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "is_retryable": self.is_retryable(),
            "context": {
                "agent_name": self.context.agent_name,
                "workflow_id": self.context.workflow_id,
                "attempt": self.context.attempt,
                "max_attempts": self.context.max_attempts,
                "provider": self.context.provider,
                "model": self.context.model,
                "extra": self.context.extra,
            } if self.context else None,
            "original_error": str(self.original_error) if self.original_error else None,
        }


# ============ 具体错误类型 ============

class RateLimitError(GrassFlowError):
    """速率限制错误"""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.RATE_LIMITED)
        super().__init__(message, **kwargs)
        self.retry_after = retry_after

    def get_retry_delay(self, attempt: int) -> float:
        """如果提供了 retry_after，使用它"""
        if self.retry_after is not None:
            return self.retry_after
        return super().get_retry_delay(attempt)


class AuthExpiredError(GrassFlowError):
    """认证过期错误"""

    def __init__(
        self,
        message: str = "Authentication expired",
        provider: Optional[str] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.AUTH_EXPIRED)
        super().__init__(message, **kwargs)
        if provider and self.context:
            self.context.provider = provider


class ContextOverflowError(GrassFlowError):
    """上下文溢出错误"""

    def __init__(
        self,
        message: str = "Context window overflow",
        current_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.CONTEXT_OVERFLOW)
        super().__init__(message, **kwargs)
        self.current_tokens = current_tokens
        self.max_tokens = max_tokens
        if self.context:
            self.context.extra["current_tokens"] = current_tokens
            self.context.extra["max_tokens"] = max_tokens


class ProviderError(GrassFlowError):
    """提供商错误"""

    def __init__(
        self,
        message: str = "Provider error",
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.PROVIDER_ERROR)
        super().__init__(message, **kwargs)
        self.status_code = status_code
        if provider and self.context:
            self.context.provider = provider
        if self.context:
            self.context.extra["status_code"] = status_code


class NetworkError(GrassFlowError):
    """网络错误"""

    def __init__(
        self,
        message: str = "Network error",
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.NETWORK_ERROR)
        super().__init__(message, **kwargs)


class ToolError(GrassFlowError):
    """工具执行错误"""

    def __init__(
        self,
        message: str = "Tool execution error",
        tool_name: Optional[str] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.TOOL_ERROR)
        super().__init__(message, **kwargs)
        self.tool_name = tool_name
        if self.context:
            self.context.extra["tool_name"] = tool_name


class PermissionDeniedError(GrassFlowError):
    """权限拒绝错误"""

    def __init__(
        self,
        message: str = "Permission denied",
        resource: Optional[str] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.PERMISSION_DENIED)
        super().__init__(message, **kwargs)
        self.resource = resource
        if self.context:
            self.context.extra["resource"] = resource


class TimeoutError(GrassFlowError):
    """超时错误"""

    def __init__(
        self,
        message: str = "Operation timed out",
        timeout_seconds: Optional[float] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.TIMEOUT)
        super().__init__(message, **kwargs)
        self.timeout_seconds = timeout_seconds
        if self.context:
            self.context.extra["timeout_seconds"] = timeout_seconds


class ValidationError(GrassFlowError):
    """校验错误"""

    def __init__(
        self,
        message: str = "Validation error",
        field: Optional[str] = None,
        **kwargs,
    ):
        kwargs.setdefault("category", ErrorCategory.VALIDATION_ERROR)
        super().__init__(message, **kwargs)
        self.field = field
        if self.context:
            self.context.extra["field"] = field


# ============ 错误分类器 ============

class ErrorClassifier:
    """
    错误分类器

    将原始异常分类为结构化的 GrassFlowError
    """

    # 错误模式匹配规则
    PATTERNS: Dict[ErrorCategory, list] = {
        ErrorCategory.RATE_LIMITED: [
            r"rate.?limit",
            r"too.?many.?requests",
            r"429",
            r"throttl",
            r"quota.?exceed",
        ],
        ErrorCategory.AUTH_EXPIRED: [
            r"auth",
            r"invalid.?api.?key",
            r"unauthorized",
            r"401",
            r"token.?expired",
            r"invalid.?token",
        ],
        ErrorCategory.CONTEXT_OVERFLOW: [
            r"context.?length",
            r"token.?limit",
            r"maximum.?context",
            r"too.?long",
            r"overflow",
        ],
        ErrorCategory.NETWORK_ERROR: [
            r"network",
            r"connection",
            r"timeout",
            r"socket",
            r"dns",
            r"ssl",
            r"tls",
            r"eof",
            r"reset",
        ],
        ErrorCategory.PERMISSION_DENIED: [
            r"permission",
            r"forbidden",
            r"403",
            r"access.?denied",
            r"not.?allowed",
        ],
        ErrorCategory.TIMEOUT: [
            r"timeout",
            r"timed? ?out",
            r"deadline",
        ],
    }

    # HTTP 状态码到错误类别的映射
    STATUS_CODE_MAP: Dict[int, ErrorCategory] = {
        401: ErrorCategory.AUTH_EXPIRED,
        403: ErrorCategory.PERMISSION_DENIED,
        429: ErrorCategory.RATE_LIMITED,
        500: ErrorCategory.PROVIDER_ERROR,
        502: ErrorCategory.PROVIDER_ERROR,
        503: ErrorCategory.PROVIDER_ERROR,
        504: ErrorCategory.PROVIDER_ERROR,
    }

    @classmethod
    def classify(
        cls,
        error: Exception,
        context: Optional[ErrorContext] = None,
    ) -> GrassFlowError:
        """
        将原始异常分类为 GrassFlowError

        Args:
            error: 原始异常
            context: 错误上下文

        Returns:
            分类后的 GrassFlowError
        """
        # 如果已经是 GrassFlowError，直接返回
        if isinstance(error, GrassFlowError):
            return error

        error_message = str(error).lower()
        error_type = type(error).__name__

        # 1. 检查 HTTP 状态码
        status_code = cls._extract_status_code(error)
        if status_code and status_code in cls.STATUS_CODE_MAP:
            category = cls.STATUS_CODE_MAP[status_code]
            return cls._create_error(
                category=category,
                message=str(error),
                context=context,
                original_error=error,
                status_code=status_code,
            )

        # 2. 模式匹配
        for category, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_message, re.IGNORECASE):
                    return cls._create_error(
                        category=category,
                        message=str(error),
                        context=context,
                        original_error=error,
                    )

        # 3. 异常类型匹配
        category = cls._classify_by_type(error)
        if category:
            return cls._create_error(
                category=category,
                message=str(error),
                context=context,
                original_error=error,
            )

        # 4. 默认为未知错误
        return GrassFlowError(
            message=str(error),
            category=ErrorCategory.UNKNOWN,
            context=context,
            original_error=error,
        )

    @classmethod
    def _extract_status_code(cls, error: Exception) -> Optional[int]:
        """从异常中提取 HTTP 状态码"""
        # 检查常见属性
        for attr in ("status_code", "status", "code"):
            code = getattr(error, attr, None)
            if isinstance(code, int) and 400 <= code < 600:
                return code

        # 从消息中提取
        message = str(error)
        match = re.search(r"\b(4\d{2}|5\d{2})\b", message)
        if match:
            return int(match.group(1))

        return None

    @classmethod
    def _classify_by_type(cls, error: Exception) -> Optional[ErrorCategory]:
        """根据异常类型分类"""
        error_type = type(error).__name__.lower()

        type_map = {
            "timeouterror": ErrorCategory.TIMEOUT,
            "timeout": ErrorCategory.TIMEOUT,
            "connectionerror": ErrorCategory.NETWORK_ERROR,
            "connectionrefusederror": ErrorCategory.NETWORK_ERROR,
            "connectionreseterror": ErrorCategory.NETWORK_ERROR,
            "socketerror": ErrorCategory.NETWORK_ERROR,
            "oserror": ErrorCategory.NETWORK_ERROR,
            "ioerror": ErrorCategory.NETWORK_ERROR,
            "permissionerror": ErrorCategory.PERMISSION_DENIED,
            "validationerror": ErrorCategory.VALIDATION_ERROR,
            "valueerror": ErrorCategory.VALIDATION_ERROR,
            "typeerror": ErrorCategory.VALIDATION_ERROR,
        }

        for type_pattern, category in type_map.items():
            if type_pattern in error_type:
                return category

        return None

    @classmethod
    def _create_error(
        cls,
        category: ErrorCategory,
        message: str,
        context: Optional[ErrorContext] = None,
        original_error: Optional[Exception] = None,
        status_code: Optional[int] = None,
    ) -> GrassFlowError:
        """创建对应的错误实例"""
        error_map: Dict[ErrorCategory, Type[GrassFlowError]] = {
            ErrorCategory.RATE_LIMITED: RateLimitError,
            ErrorCategory.AUTH_EXPIRED: AuthExpiredError,
            ErrorCategory.CONTEXT_OVERFLOW: ContextOverflowError,
            ErrorCategory.PROVIDER_ERROR: ProviderError,
            ErrorCategory.NETWORK_ERROR: NetworkError,
            ErrorCategory.TOOL_ERROR: ToolError,
            ErrorCategory.PERMISSION_DENIED: PermissionDeniedError,
            ErrorCategory.TIMEOUT: TimeoutError,
            ErrorCategory.VALIDATION_ERROR: ValidationError,
        }

        error_class = error_map.get(category, GrassFlowError)

        kwargs = {
            "message": message,
            "category": category,
            "context": context,
            "original_error": original_error,
        }

        if status_code and category == ErrorCategory.PROVIDER_ERROR:
            kwargs["status_code"] = status_code

        return error_class(**kwargs)


# ============ 重试执行器 ============

class RetryExecutor:
    """
    重试执行器

    根据错误分类和重试策略执行重试逻辑
    """

    def __init__(
        self,
        default_policy: Optional[RetryPolicy] = None,
        on_retry: Optional[callable] = None,
        on_error: Optional[callable] = None,
    ):
        """
        初始化重试执行器

        Args:
            default_policy: 默认重试策略
            on_retry: 重试回调函数 (attempt, error, delay) -> None
            on_error: 错误回调函数 (error) -> None
        """
        self.default_policy = default_policy or RetryPolicy()
        self.on_retry = on_retry
        self.on_error = on_error

    async def execute(
        self,
        func: callable,
        *args,
        context: Optional[ErrorContext] = None,
        policy: Optional[RetryPolicy] = None,
        **kwargs,
    ) -> Any:
        """
        执行函数，失败时自动重试

        Args:
            func: 要执行的异步函数
            *args: 函数参数
            context: 错误上下文
            policy: 重试策略（覆盖默认策略）
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            GrassFlowError: 最终失败时抛出
        """
        import asyncio

        retry_policy = policy or self.default_policy
        last_error = None

        for attempt in range(retry_policy.max_retries + 1):
            try:
                # 更新上下文
                if context:
                    context.attempt = attempt + 1
                    context.max_attempts = retry_policy.max_retries + 1

                return await func(*args, **kwargs)

            except Exception as e:
                # 分类错误
                classified_error = ErrorClassifier.classify(e, context)
                last_error = classified_error

                # 调用错误回调
                if self.on_error:
                    self.on_error(classified_error)

                # 检查是否可重试
                if not classified_error.is_retryable():
                    raise classified_error

                # 检查是否还有重试次数
                if attempt >= retry_policy.max_retries:
                    raise classified_error

                # 计算延迟
                delay = classified_error.get_retry_delay(attempt)

                # 调用重试回调
                if self.on_retry:
                    self.on_retry(attempt + 1, classified_error, delay)

                # 等待
                await asyncio.sleep(delay)

        # 不应该到达这里
        raise last_error or GrassFlowError("Unknown error during retry")


# ============ 便捷函数 ============

def classify_error(
    error: Exception,
    context: Optional[ErrorContext] = None,
) -> GrassFlowError:
    """
    分类错误的便捷函数

    Args:
        error: 原始异常
        context: 错误上下文

    Returns:
        分类后的 GrassFlowError
    """
    return ErrorClassifier.classify(error, context)


def create_retry_executor(
    max_retries: int = 3,
    base_delay: float = 1.0,
    on_retry: Optional[callable] = None,
) -> RetryExecutor:
    """
    创建重试执行器的便捷函数

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟
        on_retry: 重试回调

    Returns:
        RetryExecutor 实例
    """
    policy = RetryPolicy(max_retries=max_retries, base_delay=base_delay)
    return RetryExecutor(default_policy=policy, on_retry=on_retry)

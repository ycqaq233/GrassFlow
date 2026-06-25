"""
GrassFlow Doom Loop 检测

参考 OpenCode 的 Doom Loop 检测机制，提供：
- 同一工具被相同参数调用 N 次检测
- 自动询问用户是否继续
- 防止 Agent 陷入死循环

使用场景：
- Agent 反复调用同一工具但没有进展
- 工具调用陷入无限重试
- 工作流中出现循环依赖
"""

import hashlib
import json
import time
from typing import Any, Dict, Optional, Callable, List, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum


class DoomLoopAction(str, Enum):
    """检测到 Doom Loop 后的操作"""
    ASK_USER = "ask_user"       # 询问用户是否继续
    AUTO_STOP = "auto_stop"     # 自动停止
    AUTO_SKIP = "auto_skip"     # 自动跳过
    LOG_WARNING = "log_warning" # 仅记录警告


@dataclass
class DoomLoopConfig:
    """Doom Loop 检测配置"""
    max_repeated_calls: int = 3           # 触发检测的重复调用次数
    time_window: Optional[float] = None   # 时间窗口（秒），None 表示不限时间
    action: DoomLoopAction = DoomLoopAction.ASK_USER  # 检测到后的操作
    include_args: bool = True             # 是否将参数纳入重复检测
    arg_hash_depth: int = 3               # 参数哈希深度（防止深嵌套参数影响性能）


@dataclass
class ToolCallRecord:
    """工具调用记录"""
    tool_name: str
    args_hash: str
    args: Dict[str, Any]
    timestamp: float
    result_hash: Optional[str] = None
    success: bool = True


@dataclass
class DoomLoopDetection:
    """Doom Loop 检测结果"""
    detected: bool
    tool_name: str
    args_hash: str
    call_count: int
    first_call_time: float
    last_call_time: float
    time_span: float
    args: Dict[str, Any]
    message: str


class DoomLoopDetector:
    """
    Doom Loop 检测器

    用法：
        detector = DoomLoopDetector(DoomLoopConfig(max_repeated_calls=3))

        # 检查工具调用
        detection = detector.check_call("search", {"query": "test"})
        if detection.detected:
            # 处理 Doom Loop
            should_continue = await ask_user(detection.message)
            if not should_continue:
                raise DoomLoopError(detection)

        # 或使用装饰器
        @detector.wrap
        async def call_tool(name, args):
            return await execute_tool(name, args)
    """

    def __init__(
        self,
        config: Optional[DoomLoopConfig] = None,
        on_detection: Optional[Callable[[DoomLoopDetection], bool]] = None,
    ):
        """
        初始化 Doom Loop 检测器

        Args:
            config: 配置
            on_detection: 检测回调函数，返回 True 表示继续，False 表示停止
        """
        self.config = config or DoomLoopConfig()
        self.on_detection = on_detection

        # 记录历史调用: {(tool_name, args_hash): [ToolCallRecord, ...]}
        self._call_history: Dict[Tuple[str, str], List[ToolCallRecord]] = defaultdict(list)

    def _hash_args(self, args: Dict[str, Any]) -> str:
        """
        计算参数哈希

        Args:
            args: 工具参数

        Returns:
            参数的哈希值
        """
        if not self.config.include_args:
            return "no_args"

        try:
            # 序列化参数为 JSON 字符串
            args_str = json.dumps(args, sort_keys=True, default=str)
            # 计算哈希
            return hashlib.md5(args_str.encode()).hexdigest()[:16]
        except Exception:
            # 如果序列化失败，使用字符串表示
            return hashlib.md5(str(args).encode()).hexdigest()[:16]

    def _cleanup_old_records(
        self,
        records: List[ToolCallRecord],
        current_time: float,
    ) -> List[ToolCallRecord]:
        """清理过期记录"""
        if self.config.time_window is None:
            return records

        cutoff_time = current_time - self.config.time_window
        return [r for r in records if r.timestamp >= cutoff_time]

    def check_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        success: bool = True,
    ) -> DoomLoopDetection:
        """
        检查工具调用是否形成 Doom Loop

        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 工具结果
            success: 是否成功

        Returns:
            DoomLoopDetection 检测结果
        """
        current_time = time.time()
        args_hash = self._hash_args(args)
        key = (tool_name, args_hash)

        # 创建调用记录
        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            args=args,
            timestamp=current_time,
            result_hash=hashlib.md5(str(result).encode()).hexdigest()[:16] if result else None,
            success=success,
        )

        # 添加到历史记录
        self._call_history[key].append(record)

        # 清理过期记录
        self._call_history[key] = self._cleanup_old_records(
            self._call_history[key],
            current_time,
        )

        # 获取调用次数
        call_count = len(self._call_history[key])

        # 检查是否达到阈值
        detected = call_count >= self.config.max_repeated_calls

        # 计算时间跨度
        first_call_time = self._call_history[key][0].timestamp
        time_span = current_time - first_call_time

        # 生成消息
        if detected:
            message = (
                f"Doom Loop 检测: 工具 '{tool_name}' 使用相同参数被调用了 {call_count} 次\n"
                f"  参数: {json.dumps(args, indent=2, ensure_ascii=False)}\n"
                f"  时间跨度: {time_span:.1f} 秒\n"
                f"  是否继续执行?"
            )
        else:
            message = ""

        return DoomLoopDetection(
            detected=detected,
            tool_name=tool_name,
            args_hash=args_hash,
            call_count=call_count,
            first_call_time=first_call_time,
            last_call_time=current_time,
            time_span=time_span,
            args=args,
            message=message,
        )

    async def check_and_handle(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        success: bool = True,
    ) -> bool:
        """
        检查并处理 Doom Loop

        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 工具结果
            success: 是否成功

        Returns:
            True 表示继续执行，False 表示应该停止

        Raises:
            DoomLoopError: 当配置为自动停止时
        """
        detection = self.check_call(tool_name, args, result, success)

        if not detection.detected:
            return True

        # 根据配置的操作处理
        if self.config.action == DoomLoopAction.LOG_WARNING:
            return True

        elif self.config.action == DoomLoopAction.AUTO_STOP:
            raise DoomLoopError(detection)

        elif self.config.action == DoomLoopAction.AUTO_SKIP:
            return False

        elif self.config.action == DoomLoopAction.ASK_USER:
            if self.on_detection:
                return self.on_detection(detection)
            # 默认行为：如果没有设置回调，抛出异常让用户处理
            raise DoomLoopError(detection)

        return True

    def wrap(
        self,
        func: Callable,
    ) -> Callable:
        """
        装饰器：包装工具调用函数

        用法：
            @detector.wrap
            async def call_tool(tool_name: str, args: dict):
                return await execute_tool(tool_name, args)
        """
        async def wrapper(tool_name: str, args: Dict[str, Any], *inner_args, **inner_kwargs):
            # 检查 Doom Loop
            detection = self.check_call(tool_name, args)

            if detection.detected:
                should_continue = await self.check_and_handle(tool_name, args)
                if not should_continue:
                    return None

            # 执行原函数
            try:
                result = await func(tool_name, args, *inner_args, **inner_kwargs)
                # 更新最后一次调用的结果
                key = (tool_name, self._hash_args(args))
                if self._call_history[key]:
                    self._call_history[key][-1].result_hash = (
                        hashlib.md5(str(result).encode()).hexdigest()[:16]
                    )
                return result

            except Exception as e:
                # 记录失败
                key = (tool_name, self._hash_args(args))
                if self._call_history[key]:
                    self._call_history[key][-1].success = False
                raise

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    def get_call_history(
        self,
        tool_name: Optional[str] = None,
    ) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
        """
        获取调用历史

        Args:
            tool_name: 过滤特定工具的历史

        Returns:
            调用历史字典
        """
        result = {}
        for key, records in self._call_history.items():
            if tool_name and key[0] != tool_name:
                continue
            result[key] = [
                {
                    "tool_name": r.tool_name,
                    "args_hash": r.args_hash,
                    "timestamp": r.timestamp,
                    "success": r.success,
                    "result_hash": r.result_hash,
                }
                for r in records
            ]
        return result

    def get_suspicious_tools(self) -> List[Dict[str, Any]]:
        """
        获取可疑的工具调用（接近或达到阈值的）

        Returns:
            可疑工具列表
        """
        suspicious = []
        threshold = self.config.max_repeated_calls

        for (tool_name, args_hash), records in self._call_history.items():
            count = len(records)
            if count >= threshold * 0.5:  # 达到阈值的 50% 就标记为可疑
                suspicious.append({
                    "tool_name": tool_name,
                    "args_hash": args_hash,
                    "call_count": count,
                    "threshold": threshold,
                    "ratio": count / threshold,
                    "last_args": records[-1].args if records else None,
                })

        return sorted(suspicious, key=lambda x: x["ratio"], reverse=True)

    def clear_history(
        self,
        tool_name: Optional[str] = None,
    ) -> None:
        """
        清除调用历史

        Args:
            tool_name: 清除特定工具的历史，None 表示清除所有
        """
        if tool_name:
            keys_to_remove = [k for k in self._call_history if k[0] == tool_name]
            for key in keys_to_remove:
                del self._call_history[key]
        else:
            self._call_history.clear()

    def reset(self) -> None:
        """重置检测器"""
        self._call_history.clear()

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "config": {
                "max_repeated_calls": self.config.max_repeated_calls,
                "time_window": self.config.time_window,
                "action": self.config.action.value,
                "include_args": self.config.include_args,
            },
            "history_size": sum(len(records) for records in self._call_history.values()),
            "unique_calls": len(self._call_history),
            "suspicious_tools": self.get_suspicious_tools(),
        }


class DoomLoopError(Exception):
    """Doom Loop 错误"""

    def __init__(self, detection: DoomLoopDetection):
        self.detection = detection
        super().__init__(detection.message)


class DoomLoopManager:
    """
    Doom Loop 管理器

    管理多个 Doom Loop 检测器实例（按工作流或 Agent 隔离）
    """

    def __init__(self):
        self._detectors: Dict[str, DoomLoopDetector] = {}

    def get_or_create(
        self,
        scope: str,
        config: Optional[DoomLoopConfig] = None,
        on_detection: Optional[Callable[[DoomLoopDetection], bool]] = None,
    ) -> DoomLoopDetector:
        """
        获取或创建检测器

        Args:
            scope: 作用域（如工作流 ID、Agent 名称）
            config: 配置
            on_detection: 检测回调

        Returns:
            DoomLoopDetector 实例
        """
        if scope not in self._detectors:
            self._detectors[scope] = DoomLoopDetector(
                config=config,
                on_detection=on_detection,
            )
        return self._detectors[scope]

    def get(self, scope: str) -> Optional[DoomLoopDetector]:
        """获取检测器"""
        return self._detectors.get(scope)

    def remove(self, scope: str) -> bool:
        """移除检测器"""
        if scope in self._detectors:
            del self._detectors[scope]
            return True
        return False

    def clear_all(self) -> None:
        """清除所有检测器的历史"""
        for detector in self._detectors.values():
            detector.clear_history()

    def reset_all(self) -> None:
        """重置所有检测器"""
        for detector in self._detectors.values():
            detector.reset()

    def get_all_suspicious(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取所有作用域的可疑工具"""
        result = {}
        for scope, detector in self._detectors.items():
            suspicious = detector.get_suspicious_tools()
            if suspicious:
                result[scope] = suspicious
        return result


# ============ 全局 Doom Loop 管理器 ============

_global_manager = DoomLoopManager()


def get_doom_loop_detector(
    scope: str = "default",
    config: Optional[DoomLoopConfig] = None,
    on_detection: Optional[Callable[[DoomLoopDetection], bool]] = None,
) -> DoomLoopDetector:
    """
    获取或创建全局 Doom Loop 检测器

    Args:
        scope: 作用域
        config: 配置
        on_detection: 检测回调

    Returns:
        DoomLoopDetector 实例
    """
    return _global_manager.get_or_create(scope, config, on_detection)


def get_doom_loop_manager() -> DoomLoopManager:
    """获取全局 Doom Loop 管理器"""
    return _global_manager

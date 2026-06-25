"""
GrassFlow 权限控制系统

参考 opencode 的权限控制实现，提供 allow/deny/ask 三级权限控制：
- allow: 允许操作，无需用户确认
- deny: 拒绝操作，抛出异常
- ask: 询问用户，等待用户回复（once/always/reject）

权限规则格式：{ permission, pattern, action }
- permission: 权限名称（如 "read_file", "write_file", "execute_command"）
- pattern: 匹配模式（支持通配符 * 和 ?）
- action: allow / deny / ask
"""

import asyncio
import fnmatch
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class PermissionAction(str, Enum):
    """权限动作"""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class ReplyAction(str, Enum):
    """用户回复动作"""
    ONCE = "once"        # 仅本次允许
    ALWAYS = "always"    # 总是允许（添加到 approved 规则）
    REJECT = "reject"    # 拒绝


@dataclass
class PermissionRule:
    """权限规则"""
    permission: str
    pattern: str = "*"
    action: PermissionAction = PermissionAction.ASK

    def to_dict(self) -> Dict[str, str]:
        return {
            "permission": self.permission,
            "pattern": self.pattern,
            "action": self.action.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "PermissionRule":
        return cls(
            permission=data["permission"],
            pattern=data.get("pattern", "*"),
            action=PermissionAction(data.get("action", "ask")),
        )


# 类型别名
Ruleset = List[PermissionRule]


@dataclass
class PermissionRequest:
    """权限请求"""
    id: str
    permission: str
    patterns: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "permission": self.permission,
            "patterns": self.patterns,
            "metadata": self.metadata,
            "tool": self.tool,
        }


@dataclass
class PendingEntry:
    """待处理的权限请求"""
    request: PermissionRequest
    future: asyncio.Future


class PermissionRuleDeniedError(Exception):
    """权限规则拒绝异常"""
    def __init__(self, permission: str, pattern: str, ruleset: Optional[List[Dict]] = None):
        self.permission = permission
        self.pattern = pattern
        self.ruleset = ruleset
        super().__init__(f"Permission denied: {permission} for pattern '{pattern}'")


class PermissionRequestNotFoundError(Exception):
    """权限请求未找到异常"""
    def __init__(self, request_id: str):
        self.request_id = request_id
        super().__init__(f"Permission request not found: {request_id}")


class PermissionUserRejectedError(Exception):
    """用户拒绝权限请求异常"""
    def __init__(self, message: Optional[str] = None):
        self.message = message
        super().__init__(message or "Permission request rejected by user")


def wildcard_match(text: str, pattern: str) -> bool:
    """
    通配符匹配

    支持：
    - *: 匹配任意字符序列
    - ?: 匹配单个字符
    - [seq]: 匹配 seq 中的任意字符
    - [!seq]: 匹配不在 seq 中的任意字符

    Args:
        text: 要匹配的文本
        pattern: 通配符模式

    Returns:
        是否匹配
    """
    return fnmatch.fnmatch(text, pattern)


def evaluate(permission: str, pattern: str, *rulesets: Ruleset) -> PermissionRule:
    """
    评估权限

    在规则集中查找匹配的规则，返回最后一个匹配的规则。
    如果没有匹配的规则，默认返回 ask 动作。

    Args:
        permission: 权限名称
        pattern: 匹配模式
        *rulesets: 规则集列表

    Returns:
        匹配的权限规则，如果没有匹配则返回默认的 ask 规则
    """
    # 合并所有规则集
    all_rules: List[PermissionRule] = []
    for ruleset in rulesets:
        all_rules.extend(ruleset)

    # 从后往前查找最后一个匹配的规则
    for rule in reversed(all_rules):
        if wildcard_match(permission, rule.permission) and wildcard_match(pattern, rule.pattern):
            return rule

    # 默认返回 ask
    return PermissionRule(permission=permission, pattern="*", action=PermissionAction.ASK)


def expand_path(pattern: str) -> str:
    """
    展开路径中的特殊符号

    支持：
    - ~/ -> 用户主目录
    - ~ -> 用户主目录
    - $HOME/ -> 用户主目录

    Args:
        pattern: 路径模式

    Returns:
        展开后的路径
    """
    import os
    home = os.path.expanduser("~")

    if pattern.startswith("~/"):
        return home + pattern[1:]
    if pattern == "~":
        return home
    if pattern.startswith("$HOME/"):
        return home + pattern[5:]
    if pattern == "$HOME":
        return home

    return pattern


def from_config(config: Dict[str, Any]) -> Ruleset:
    """
    从配置创建规则集

    配置格式：
    {
        "permission_name": "allow" | "deny" | "ask",
        "permission_name": {
            "pattern1": "allow" | "deny" | "ask",
            "pattern2": "allow" | "deny" | "ask"
        }
    }

    Args:
        config: 配置字典

    Returns:
        规则集
    """
    ruleset: Ruleset = []

    for key, value in config.items():
        if isinstance(value, str):
            # 简单格式：permission -> action
            ruleset.append(PermissionRule(
                permission=key,
                pattern="*",
                action=PermissionAction(value),
            ))
        elif isinstance(value, dict):
            # 详细格式：permission -> { pattern -> action }
            for pattern, action in value.items():
                ruleset.append(PermissionRule(
                    permission=key,
                    pattern=expand_path(pattern),
                    action=PermissionAction(action),
                ))

    return ruleset


class PermissionService:
    """
    权限服务

    管理权限规则、处理权限请求和用户回复。
    """

    def __init__(self, on_ask: Optional[Callable[[PermissionRequest], None]] = None):
        """
        初始化权限服务

        Args:
            on_ask: 当需要询问用户时的回调函数
        """
        self._pending: Dict[str, PendingEntry] = {}
        self._approved: Ruleset = []
        self._on_ask = on_ask

    def evaluate(self, permission: str, pattern: str, *rulesets: Ruleset) -> PermissionRule:
        """
        评估权限

        Args:
            permission: 权限名称
            pattern: 匹配模式
            *rulesets: 额外的规则集

        Returns:
            匹配的权限规则
        """
        return evaluate(permission, pattern, *rulesets, self._approved)

    async def ask(
        self,
        permission: str,
        patterns: List[str],
        *rulesets: Ruleset,
        metadata: Optional[Dict[str, Any]] = None,
        tool: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """
        请求权限

        Args:
            permission: 权限名称
            patterns: 需要匹配的模式列表
            *rulesets: 规则集
            metadata: 额外元数据
            tool: 工具名称
            request_id: 请求 ID（可选）

        Raises:
            PermissionDeniedError: 权限被拒绝
            PermissionRejectedError: 用户拒绝
        """
        needs_ask = False

        # 检查所有 pattern
        for pattern in patterns:
            rule = self.evaluate(permission, pattern, *rulesets)
            if rule.action == PermissionAction.DENY:
                # 收集相关的拒绝规则
                denied_rules = [
                    r.to_dict()
                    for ruleset in rulesets
                    for r in ruleset
                    if wildcard_match(permission, r.permission)
                ]
                raise PermissionRuleDeniedError(permission, pattern, denied_rules)
            if rule.action == PermissionAction.ALLOW:
                continue
            needs_ask = True

        # 如果所有 pattern 都是 allow，直接返回
        if not needs_ask:
            return

        # 需要询问用户
        req_id = request_id or str(uuid.uuid4())
        request = PermissionRequest(
            id=req_id,
            permission=permission,
            patterns=patterns,
            metadata=metadata or {},
            tool=tool,
        )

        # 创建 Future 等待用户回复
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending[req_id] = PendingEntry(request=request, future=future)

        # 调用回调通知用户
        if self._on_ask:
            self._on_ask(request)

        # 等待用户回复
        try:
            await future
        finally:
            # 清理
            self._pending.pop(req_id, None)

    async def reply(
        self,
        request_id: str,
        reply: ReplyAction,
        message: Optional[str] = None,
    ) -> None:
        """
        回复权限请求

        Args:
            request_id: 请求 ID
            reply: 回复动作
            message: 可选的消息（用于 reject 时的反馈）

        Raises:
            PermissionNotFoundError: 请求未找到
        """
        entry = self._pending.get(request_id)
        if not entry:
            raise PermissionRequestNotFoundError(request_id)

        # 从 pending 中移除
        self._pending.pop(request_id, None)

        if reply == ReplyAction.REJECT:
            # 拒绝当前请求
            if not entry.future.done():
                entry.future.set_exception(
                    PermissionUserRejectedError(message)
                )
            return

        # 允许当前请求
        if not entry.future.done():
            entry.future.set_result(None)

        if reply == ReplyAction.ALWAYS:
            # 添加到 approved 规则
            for pattern in entry.request.patterns:
                self._approved.append(PermissionRule(
                    permission=entry.request.permission,
                    pattern=pattern,
                    action=PermissionAction.ALLOW,
                ))

            # 自动批准其他匹配的 pending 请求
            await self._auto_approve_pending()

    async def _auto_approve_pending(self) -> None:
        """自动批准匹配的 pending 请求"""
        to_approve: List[str] = []

        for req_id, entry in self._pending.items():
            # 检查所有 pattern 是否都匹配 approved 规则
            all_approved = all(
                evaluate(
                    entry.request.permission,
                    pattern,
                    self._approved,
                ).action == PermissionAction.ALLOW
                for pattern in entry.request.patterns
            )
            if all_approved:
                to_approve.append(req_id)

        # 批准匹配的请求
        for req_id in to_approve:
            entry = self._pending.pop(req_id, None)
            if entry and not entry.future.done():
                entry.future.set_result(None)

    def list_pending(self) -> List[PermissionRequest]:
        """
        列出所有待处理的权限请求

        Returns:
            待处理请求列表
        """
        return [entry.request for entry in self._pending.values()]

    def get_approved_rules(self) -> Ruleset:
        """
        获取已批准的规则列表

        Returns:
            已批准的规则列表
        """
        return self._approved.copy()

    def clear_approved(self) -> None:
        """清空已批准的规则"""
        self._approved.clear()

    def add_approved_rule(self, rule: PermissionRule) -> None:
        """
        添加已批准的规则

        Args:
            rule: 权限规则
        """
        self._approved.append(rule)

    def from_config(self, config: Dict[str, Any]) -> None:
        """
        从配置加载规则

        Args:
            config: 配置字典
        """
        rules = from_config(config)
        self._approved.extend(rules)

    def to_config(self) -> Dict[str, Any]:
        """
        导出为配置格式

        Returns:
            配置字典
        """
        config: Dict[str, Any] = {}
        for rule in self._approved:
            if rule.permission not in config:
                config[rule.permission] = {}
            if isinstance(config[rule.permission], dict):
                config[rule.permission][rule.pattern] = rule.action.value
        return config


# 预定义的权限常量
class Permissions:
    """预定义的权限名称"""
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    EXECUTE_COMMAND = "execute_command"
    LIST_DIRECTORY = "list_directory"
    SEARCH_CODE = "search_code"
    CREATE_DIRECTORY = "create_directory"

    # Agent 相关权限
    CALL_LLM = "call_llm"
    CALL_TOOL = "call_tool"
    ACCESS_MCP = "access_mcp"

    # 工作流相关权限
    CREATE_WORKFLOW = "create_workflow"
    RUN_WORKFLOW = "run_workflow"
    DELETE_WORKFLOW = "delete_workflow"


# 默认规则集
DEFAULT_RULESET: Ruleset = [
    # 默认允许读取操作
    PermissionRule(permission=Permissions.READ_FILE, pattern="*", action=PermissionAction.ALLOW),
    PermissionRule(permission=Permissions.LIST_DIRECTORY, pattern="*", action=PermissionAction.ALLOW),
    PermissionRule(permission=Permissions.SEARCH_CODE, pattern="*", action=PermissionAction.ALLOW),

    # 默认询问写入操作
    PermissionRule(permission=Permissions.WRITE_FILE, pattern="*", action=PermissionAction.ASK),
    PermissionRule(permission=Permissions.EDIT_FILE, pattern="*", action=PermissionAction.ASK),
    PermissionRule(permission=Permissions.DELETE_FILE, pattern="*", action=PermissionAction.ASK),
    PermissionRule(permission=Permissions.CREATE_DIRECTORY, pattern="*", action=PermissionAction.ASK),

    # 默认询问执行命令
    PermissionRule(permission=Permissions.EXECUTE_COMMAND, pattern="*", action=PermissionAction.ASK),

    # 默认允许 LLM 调用
    PermissionRule(permission=Permissions.CALL_LLM, pattern="*", action=PermissionAction.ALLOW),
    PermissionRule(permission=Permissions.CALL_TOOL, pattern="*", action=PermissionAction.ASK),
    PermissionRule(permission=Permissions.ACCESS_MCP, pattern="*", action=PermissionAction.ASK),

    # 默认询问工作流操作
    PermissionRule(permission=Permissions.CREATE_WORKFLOW, pattern="*", action=PermissionAction.ALLOW),
    PermissionRule(permission=Permissions.RUN_WORKFLOW, pattern="*", action=PermissionAction.ALLOW),
    PermissionRule(permission=Permissions.DELETE_WORKFLOW, pattern="*", action=PermissionAction.ASK),
]


def create_permission_service(
    config: Optional[Dict[str, Any]] = None,
    on_ask: Optional[Callable[[PermissionRequest], None]] = None,
    use_defaults: bool = True,
) -> PermissionService:
    """
    创建权限服务

    Args:
        config: 配置字典
        on_ask: 当需要询问用户时的回调函数
        use_defaults: 是否使用默认规则

    Returns:
        权限服务实例
    """
    service = PermissionService(on_ask=on_ask)

    # 添加默认规则
    if use_defaults:
        service._approved.extend(DEFAULT_RULESET)

    # 从配置加载规则
    if config:
        service.from_config(config)

    return service

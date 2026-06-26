"""
GrassFlow 工具权限检查器

参考 hermes tools/approval.py 的设计，为 GrassFlow 提供工具调用前的权限控制。
支持三级权限模型：allow（直接允许）、ask（询问用户）、deny（禁止调用）。
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ApprovalChoice(str, Enum):
    """审批选择"""
    ONCE = "once"        # 仅本次允许
    SESSION = "session"  # 本会话允许
    ALWAYS = "always"    # 永久允许
    DENY = "deny"        # 拒绝


# 危险工具模式 -- 需要审批的操作类型
DANGEROUS_TOOL_PATTERNS: List[Tuple[str, str]] = [
    # 文件写入类
    (r"write_file|patch_file|create_file", "文件写入操作"),
    (r"delete_file|remove_file|unlink", "文件删除操作"),
    # 命令执行类
    (r"run_command|execute_command|shell_exec|terminal", "命令执行操作"),
    # 代码执行类
    (r"execute_code|eval_code|exec_code", "代码执行操作"),
    # 网络请求类
    (r"http_request|fetch|curl|wget|send_request", "网络请求操作"),
    # 数据库操作
    (r"drop_table|truncate|delete_from", "数据库破坏性操作"),
    # 系统操作
    (r"system_call|process_exec|spawn", "系统调用操作"),
]

_COMPILED_DANGEROUS = [
    (re.compile(pattern, re.IGNORECASE), desc)
    for pattern, desc in DANGEROUS_TOOL_PATTERNS
]


def detect_dangerous_tool(tool_name: str) -> Tuple[bool, Optional[str]]:
    """检测工具名是否匹配危险模式。

    Args:
        tool_name: 工具名称

    Returns:
        (is_dangerous, description) 或 (False, None)
    """
    for pattern_re, description in _COMPILED_DANGEROUS:
        if pattern_re.search(tool_name):
            return (True, description)
    return (False, None)


class PermissionHandler:
    """工具权限检查器。

    在工具执行前检查权限，根据 ToolDef.permission 和危险模式检测
    决定是否允许、询问或拒绝工具调用。

    使用方式::

        handler = PermissionHandler()
        handler.set_approval_callback(my_callback)

        decision = await handler.check_permission(
            tool_name="write_file",
            tool_args={"path": "/etc/passwd"},
            permission=ToolPermission.ASK,
        )
        if decision.approved:
            # 执行工具
            ...
    """

    def __init__(self) -> None:
        self._approval_callback: Optional[Callable] = None
        self._session_approved: set = set()   # 本会话已批准的工具名
        self._permanent_approved: set = set()  # 永久批准的工具名

    def set_approval_callback(
        self,
        callback: Callable[[str, str, str], "str"],
    ) -> None:
        """设置审批回调函数。

        callback 签名:
            async def callback(tool_name: str, description: str, args_preview: str) -> str
            返回值: "once", "session", "always", "deny"
        """
        self._approval_callback = callback

    def approve_session(self, tool_name: str) -> None:
        """标记工具在本会话中已批准"""
        self._session_approved.add(tool_name)

    def approve_permanent(self, tool_name: str) -> None:
        """标记工具永久批准"""
        self._permanent_approved.add(tool_name)
        self._session_approved.add(tool_name)

    def is_approved(self, tool_name: str) -> bool:
        """检查工具是否已被批准（会话级或永久）"""
        return tool_name in self._permanent_approved or tool_name in self._session_approved

    def clear_session(self) -> None:
        """清除本会话的审批状态"""
        self._session_approved.clear()

    def check_permission(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        permission: str = "allow",
    ) -> "PermissionDecision":
        """检查工具调用权限。

        优先级:
          1. 已批准的工具 -> 直接允许
          2. ToolDef.permission == DENY -> 拒绝
          3. ToolDef.permission == ASK 或匹配危险模式 -> 需要审批
          4. ToolDef.permission == ALLOW 且不危险 -> 直接允许

        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            permission: ToolDef.permission 的值 ("allow", "ask", "deny")

        Returns:
            PermissionDecision 对象
        """
        from core.tool_registry import ToolPermission

        # 1. 已批准 -> 直接通过
        if self.is_approved(tool_name):
            return PermissionDecision(approved=True)

        # 2. 显式 DENY
        if permission == ToolPermission.DENY.value:
            return PermissionDecision(
                approved=False,
                message=f"工具 '{tool_name}' 已被配置为禁止调用 (permission=deny)",
            )

        # 3. 显式 ASK 或危险模式匹配
        is_dangerous, danger_desc = detect_dangerous_tool(tool_name)
        needs_ask = permission == ToolPermission.ASK.value or is_dangerous

        if needs_ask:
            desc = danger_desc or f"工具 '{tool_name}' 需要用户审批"
            args_preview = str(tool_args)[:200] if tool_args else "(无参数)"
            return PermissionDecision(
                approved=False,
                needs_approval=True,
                message=f"需要审批: {desc}",
                description=desc,
                args_preview=args_preview,
            )

        # 4. ALLOW 且不危险 -> 直接通过
        return PermissionDecision(approved=True)

    async def resolve_approval(
        self,
        tool_name: str,
        description: str,
        args_preview: str,
    ) -> "PermissionDecision":
        """通过回调解析审批请求。

        如果没有设置回调，默认拒绝。
        """
        if self._approval_callback is None:
            logger.warning(
                "Permission approval needed for '%s' but no callback set; denying",
                tool_name,
            )
            return PermissionDecision(
                approved=False,
                message=f"工具 '{tool_name}' 需要审批但未设置审批回调，默认拒绝",
            )

        try:
            choice = await self._approval_callback(tool_name, description, args_preview)
        except Exception as e:
            logger.error("Approval callback failed: %s", e)
            return PermissionDecision(
                approved=False,
                message=f"审批回调执行失败: {e}",
            )

        if choice == ApprovalChoice.DENY.value or choice == "deny":
            return PermissionDecision(
                approved=False,
                message=f"用户拒绝了工具 '{tool_name}' 的调用",
            )

        # 审批通过
        if choice == ApprovalChoice.SESSION.value or choice == "session":
            self.approve_session(tool_name)
        elif choice == ApprovalChoice.ALWAYS.value or choice == "always":
            self.approve_permanent(tool_name)
        # choice == "once": 不持久化

        return PermissionDecision(approved=True)


class PermissionDecision:
    """权限检查决策结果"""

    def __init__(
        self,
        approved: bool,
        message: str = "",
        needs_approval: bool = False,
        description: str = "",
        args_preview: str = "",
    ) -> None:
        self.approved = approved
        self.message = message
        self.needs_approval = needs_approval
        self.description = description
        self.args_preview = args_preview


# 全局单例
_permission_handler: Optional[PermissionHandler] = None


def get_permission_handler() -> PermissionHandler:
    """获取全局权限处理器单例"""
    global _permission_handler
    if _permission_handler is None:
        _permission_handler = PermissionHandler()
    return _permission_handler

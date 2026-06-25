"""
GrassFlow 审批系统

直接从 Hermes ``tools/approval.py`` 搬过来的审批逻辑，适配为 GrassFlow 的接口风格。

支持的审批模式：
- NORMAL: 正常审批（危险操作需要用户确认）
- YOLO: 自动批准一切（硬性阻止除外）
- STRICT: 任何操作都要审批
"""

from enum import Enum
from typing import Dict, Optional, Set

try:
    from .dangerous_commands import DangerousCommandDetector
except ImportError:
    from dangerous_commands import DangerousCommandDetector  # type: ignore


class ApprovalMode(Enum):
    """审批模式"""
    NORMAL = "normal"     # 正常审批
    YOLO = "yolo"         # 自动批准一切（硬性阻止除外）
    STRICT = "strict"     # 任何操作都要审批


class ApprovalHandler:
    """审批处理器

    直接从 Hermes ``tools/approval.py`` 搬过来的审批逻辑，简化了会话管理和持久化，
    适配为 GrassFlow 的接口风格。
    """

    def __init__(self, mode: ApprovalMode = ApprovalMode.NORMAL):
        self.mode = mode
        self._permanently_allowed: Set[str] = set()
        self._session_allowed: Set[str] = set()
        self._detector = DangerousCommandDetector()

    @property
    def mode(self) -> ApprovalMode:
        return self._mode

    @mode.setter
    def mode(self, value: ApprovalMode):
        self._mode = value

    def set_yolo(self) -> None:
        """启用 YOLO 模式"""
        self._mode = ApprovalMode.YOLO

    def set_normal(self) -> None:
        """恢复正常审批模式"""
        self._mode = ApprovalMode.NORMAL

    def set_strict(self) -> None:
        """启用严格审批模式"""
        self._mode = ApprovalMode.STRICT

    def allow_permanently(self, pattern: str) -> None:
        """永久允许某个命令模式"""
        self._permanently_allowed.add(pattern)

    def allow_session(self, pattern: str) -> None:
        """本次会话允许某个命令模式"""
        self._session_allowed.add(pattern)

    def is_permanently_allowed(self, command: str) -> bool:
        """检查命令是否永久允许

        检查 command_allowlist 中的精确匹配和通配符匹配。
        """
        command = command.strip()
        for pattern in self._permanently_allowed:
            if command == pattern:
                return True
        return False

    def request_approval(self, command: str, description: str = "") -> dict:
        """请求审批

        这是主入口方法。调用者传入命令和描述，返回审批结果。

        Args:
            command: 要执行的命令
            description: 可选的描述信息

        Returns:
            审批结果字典：
            {
                "approved": bool,       # 是否批准
                "hardline": bool,       # 是否硬性阻止
                "message": str,         # 审批消息
                "mode": str,            # 当前审批模式
            }
        """
        # 1. 硬性阻止检查（YOLO 模式下也执行）
        is_hardline, hardline_desc = self._detector.is_hardline(command)
        if is_hardline:
            return {
                "approved": False,
                "hardline": True,
                "message": (
                    f"BLOCKED (hardline): {hardline_desc}. "
                    "This command is on the unconditional blocklist and cannot "
                    "be executed — not even in YOLO mode. If you genuinely "
                    "need to run it, execute it manually in a terminal outside "
                    "the agent."
                ),
                "mode": self._mode.value,
            }

        # 2. YOLO 模式：自动批准
        if self._mode == ApprovalMode.YOLO:
            return {
                "approved": True,
                "hardline": False,
                "message": "YOLO mode: auto-approved",
                "mode": self._mode.value,
            }

        # 3. 永久允许检查
        if self.is_permanently_allowed(command):
            return {
                "approved": True,
                "hardline": False,
                "message": "Permanently allowed",
                "mode": self._mode.value,
            }

        # 4. 危险命令检测
        is_dangerous, danger_desc = self._detector.detect(command)
        if not danger_desc and description:
            danger_desc = description

        # 5. STRICT 模式：任何命令都要审批
        if self._mode == ApprovalMode.STRICT:
            return {
                "approved": False,
                "hardline": False,
                "message": (
                    f"⚠️ STRICT mode: approval required. "
                    f"{danger_desc or 'Command execution needs approval'}.\n\n"
                    f"Command:\n```\n{command}\n```"
                ),
                "mode": self._mode.value,
                "needs_approval": True,
                "command": command,
                "description": danger_desc,
            }

        # 6. NORMAL 模式：仅危险命令需要审批
        if is_dangerous:
            # 检查会话级别是否已允许
            if danger_desc in self._session_allowed:
                return {
                    "approved": True,
                    "hardline": False,
                    "message": "Session-approved",
                    "mode": self._mode.value,
                }

            return {
                "approved": False,
                "hardline": False,
                "message": (
                    f"⚠️ This command is potentially dangerous "
                    f"({danger_desc}). Please confirm.\n\n"
                    f"Command:\n```\n{command}\n```"
                ),
                "mode": self._mode.value,
                "needs_approval": True,
                "command": command,
                "description": danger_desc,
            }

        # 7. 安全命令：自动批准
        return {
            "approved": True,
            "hardline": False,
            "message": "Safe command, auto-approved",
            "mode": self._mode.value,
        }

    def approve_command(self, command: str, description: str = "",
                        scope: str = "once") -> dict:
        """手动批准命令

        在 request_approval 返回 needs_approval=True 后，调用此方法来批准。

        Args:
            command: 要批准的命令
            description: 命令的危险描述
            scope: 批准范围 — "once" | "session" | "always"

        Returns:
            批准结果
        """
        if scope == "always":
            self._permanently_allowed.add(command.strip())
            self._session_allowed.add(description)
        elif scope == "session":
            if description:
                self._session_allowed.add(description)

        return {
            "approved": True,
            "scope": scope,
            "message": f"Command approved (scope: {scope})",
        }

    def deny_command(self, command: str = "", description: str = "") -> dict:
        """拒绝命令

        Returns:
            拒绝结果
        """
        return {
            "approved": False,
            "message": (
                "BLOCKED: User denied this command. Do NOT retry this command, "
                "do NOT rephrase it, and do NOT attempt the same outcome via "
                "a different command."
            ),
        }

    def check_command(self, command: str, description: str = "",
                      auto_approve_callback=None) -> dict:
        """检查命令并自动处理审批

        这是一个高层方法，整合了检测和审批逻辑。
        如果 auto_approve_callback 已提供且命令危险，会调用回调来获取用户确认。

        Args:
            command: 要检查的命令
            description: 可选的描述
            auto_approve_callback: 可选的回调函数，签名为
                callback(command, description) -> str ("approve"|"deny")

        Returns:
            审批结果
        """
        result = self.request_approval(command, description)

        if result["approved"]:
            return result

        if result.get("hardline"):
            return result

        # 需要审批
        if auto_approve_callback and result.get("needs_approval"):
            try:
                choice = auto_approve_callback(command, result.get("description", ""))
                if choice in ("approve", "yes", "y"):
                    return self.approve_command(command, result.get("description", ""))
                else:
                    return self.deny_command(command, result.get("description", ""))
            except Exception:
                # 回调失败 = 拒绝
                return self.deny_command(command, result.get("description", ""))

        return result

    def clear_session(self) -> None:
        """清除会话级别的批准记录"""
        self._session_allowed.clear()

    def reset(self) -> None:
        """重置审批处理器"""
        self._mode = ApprovalMode.NORMAL
        self._permanently_allowed.clear()
        self._session_allowed.clear()


# 全局默认审批处理器
_default_handler = ApprovalHandler()


def get_default_handler() -> ApprovalHandler:
    """获取全局默认审批处理器"""
    return _default_handler


def set_approval_mode(mode: ApprovalMode) -> None:
    """设置全局审批模式"""
    _default_handler.mode = mode

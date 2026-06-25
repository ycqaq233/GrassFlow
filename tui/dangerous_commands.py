"""
GrassFlow 危险命令检测模块

直接从 Hermes ``tools/approval.py`` 搬过来的危险命令模式和检测逻辑。
模式列表和检测方法是 Hermes 经过长期实践得出的，不需要重复造轮子。
"""

import re
import unicodedata
from typing import Tuple, Optional


# =============================================================================
# 危险命令模式（直接从 Hermes tools/approval.py 搬过来）
# =============================================================================

DANGEROUS_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*/', "delete in root path"),
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\brm\s+-[^\s]*f', "force delete"),
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666)', "world-writable permissions"),
    (r'\bchown\s+(-[^\s]*\s+)*root', "change owner to root"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)', "SQL DELETE without WHERE"),
    (r'\bgit\s+push\s+(-[^\s]*\s+)*--force', "force push"),
    (r'\bgit\s+reset\s+--hard\b', "git hard reset"),
    (r'\bdd\s+if=', "dd disk operations"),
    (r'\bmkfs\.', "format filesystem"),
    (r'>\s*/dev/sd[a-z]', "write to block device"),
    (r'\bchmod\s+(-[^\s]*\s+)*\+x\b', "make file executable"),
    (r'\bcurl\b.*\|\s*(?:[/\w]*/)?(?:ba)?sh\b', "pipe remote content to shell"),
    (r'\bwget\b.*\|\s*(?:[/\w]*/)?(?:ba)?sh\b', "pipe remote content to shell"),
    (r'\bgit\s+clean\s+-[^\s]*f', "git clean with force (deletes untracked files)"),
    (r'\bgit\s+branch\s+-D\b', "git branch force delete"),
    (r'\bfind\b.*-exec\s+(/\S*/)?rm\b', "find -exec rm"),
    (r'\bfind\b.*-delete\b', "find -delete"),
    (r'\bkill\s+-9\b', "force kill process"),
    (r'\bpkill\b', "kill process by name"),
    (r'\bkillall\b', "killall"),
    (r'\bxargs\s+.*\brm\b', "xargs with rm"),
    (r'\bchmod\s+-[^\s]*R\b', "recursive chmod"),
    (r'\bchown\s+-[^\s]*R\b', "recursive chown"),
    (r'\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b', "stop/restart system service"),
    (r'\b(bash|sh|zsh|ksh)\s+-[^\s]*c(\s+|$)', "shell command via -c flag"),
    (r'\b(python[23]?|perl|ruby|node)\s+-[ec]\s+', "script execution via -e/-c flag"),
    (r'\btruncate\b', "truncate file"),
]

# =============================================================================
# 硬性阻止列表（YOLO 模式也不允许，直接从 Hermes 搬过来）
# =============================================================================

HARDLINE_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*(-rf|-fr)\s+(/|/\*|\*)', "recursive delete of root"),
    (r'\bmkfs(\.[a-z0-9]+)?\s+', "format filesystem"),
    (r'\bkill\s+(-[^\s]+\s+)*-1\b', "kill all processes"),
    (r'\b(shutdown|reboot|halt|poweroff)\b', "system shutdown"),
    (r'\bchmod\s+(-[^\s]*\s+)*777\s+/', "world-writable root"),
    (r'\bdd\s+if=/dev/zero\s+of=/dev/', "zero out block device"),
    (r'\bdd\s+if=.*\s+of=/dev/', "dd to block device"),
    (r'>\s*/dev/sd[a-z]', "write to block device via redirect"),
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "fork bomb"),
]

# 预编译正则（提升性能）
_RE_FLAGS = re.IGNORECASE | re.DOTALL

DANGEROUS_PATTERNS_COMPILED = [
    (re.compile(pattern, _RE_FLAGS), description)
    for pattern, description in DANGEROUS_PATTERNS
]

HARDLINE_PATTERNS_COMPILED = [
    (re.compile(pattern, _RE_FLAGS), description)
    for pattern, description in HARDLINE_PATTERNS
]


# =============================================================================
# DangerousCommandDetector
# =============================================================================

class DangerousCommandDetector:
    """危险命令检测器

    直接从 Hermes ``tools/approval.py`` 搬过来的检测逻辑。
    """

    def _normalize_command(self, command: str) -> str:
        """规范化命令用于检测

        - 去除 ANSI 转义序列（简单实现）
        - 去除 null 字节
        - Unicode 规范化（全角→半角等）
        - 去除 shell 反斜杠转义
        """
        # 简单去除常见 ANSI 序列
        command = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', command)
        # 去除 null 字节
        command = command.replace('\x00', '')
        # Unicode 规范化
        command = unicodedata.normalize('NFKC', command)
        # 去除 shell 反斜杠转义
        command = re.sub(r'\\([^\n])', r'\1', command)
        return command

    def detect(self, command: str) -> Tuple[bool, str]:
        """检测命令是否危险

        Args:
            command: 要检测的命令

        Returns:
            (is_dangerous, description) — 如果是危险命令则 is_dangerous=True，
            description 为危险描述
        """
        normalized = self._normalize_command(command).lower()
        for pattern_re, description in DANGEROUS_PATTERNS_COMPILED:
            if pattern_re.search(normalized):
                return (True, description)
        return (False, "")

    def is_hardline(self, command: str) -> Tuple[bool, str]:
        """检测是否硬性阻止命令

        硬性阻止的命令即使在 YOLO 模式下也不允许执行。

        Args:
            command: 要检测的命令

        Returns:
            (is_hardline, description)
        """
        normalized = self._normalize_command(command).lower()
        for pattern_re, description in HARDLINE_PATTERNS_COMPILED:
            if pattern_re.search(normalized):
                return (True, description)
        return (False, "")

    def normalize(self, command: str) -> str:
        """规范化命令用于检测（公开方法）"""
        return self._normalize_command(command)


# 全局默认检测器
_default_detector = DangerousCommandDetector()


def detect_dangerous_command(command: str) -> Tuple[bool, str]:
    """便捷函数：检测命令是否危险"""
    return _default_detector.detect(command)


def detect_hardline_command(command: str) -> Tuple[bool, str]:
    """便捷函数：检测是否硬性阻止命令"""
    return _default_detector.is_hardline(command)

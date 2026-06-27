"""Bridge between legacy tools.tool.Tool and core.tool_registry.BaseTool.

Converts the old tool system (tools.tool.Tool with execute()) into the
active core.tool_registry.BaseTool interface (with run()), so that built-in
tools (ShellTool, ReadTool, etc.) can be registered into the core ToolRegistry
and used by AgentLoop.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from core.tool_registry import (
    BaseTool,
    ToolResult as CoreToolResult,
    ToolContext as CoreToolContext,
    ToolSource,
    ToolPermission,
)

logger = logging.getLogger(__name__)


class LegacyToolAdapter(BaseTool):
    """Wraps a tools.tool.Tool instance as a core.tool_registry.BaseTool.

    Usage::

        from tools.shell import ShellTool
        from tools.bridge import LegacyToolAdapter

        adapter = LegacyToolAdapter(ShellTool())
        registry.register(adapter)  # registers into core ToolRegistry
    """

    def __init__(self, legacy_tool: Any) -> None:
        """Initialize the adapter.

        Args:
            legacy_tool: An instance of tools.tool.Tool (or subclass).
        """
        self._tool = legacy_tool

    @property
    def id(self) -> str:
        return self._tool.id

    @property
    def description(self) -> str:
        return self._tool.description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._tool.parameters

    @property
    def source(self) -> ToolSource:
        return ToolSource.BUILTIN

    @property
    def permission(self) -> ToolPermission:
        # Shell tool gets ASK permission, others get ALLOW
        if self._tool.id == "shell":
            return ToolPermission.ASK
        return ToolPermission.ALLOW

    @property
    def tags(self) -> list:
        return ["builtin", self._tool.id]

    async def run(self, args: Dict[str, Any], ctx: CoreToolContext) -> CoreToolResult:
        """Execute the legacy tool and convert the result.

        Bridges the core ToolContext -> legacy ToolContext -> legacy ToolResult -> core ToolResult.
        """
        from tools.tool import ToolContext as LegacyCtx, ToolResult as LegacyResult

        # Build a legacy ToolContext from the core one
        legacy_ctx = LegacyCtx(
            cwd=ctx.extra.get("cwd", os.getcwd()),
            session_id=ctx.session_id or None,
            message_id=ctx.message_id or None,
            agent=ctx.agent_name or None,
            timeout=ctx.extra.get("timeout", 60),
        )

        try:
            # Call the legacy tool's execute()
            legacy_result: LegacyResult = await self._tool.execute(args, legacy_ctx)

            # Convert legacy ToolResult to core ToolResult
            return CoreToolResult(
                output=legacy_result.output or "",
                title=legacy_result.title or "",
                metadata=legacy_result.metadata or {},
                attachments=legacy_result.attachments or None,
                is_error=bool(legacy_result.metadata.get("error")),
            )
        except Exception as e:
            logger.warning("Legacy tool '%s' execution failed: %s", self._tool.id, e)
            return CoreToolResult.error(f"Tool '{self._tool.id}' execution failed: {e}")

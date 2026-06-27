"""
GrassFlow Agent Loop 集成层

从 tui/repl.py 中提取的 Agent Loop 集成逻辑，提供独立的 AgentIntegration 类，
封装 Agent Loop 初始化、流式/非流式消息处理、线程安全 UI 更新队列等功能。

使用方式::

    integration = AgentIntegration(config_manager, session_manager)
    integration.init_agent_loop()

    # 流式处理
    async for event in integration.process_streaming(text, history, system_prompt):
        ...

    # 非流式处理
    result = await integration.process(messages)
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import traceback
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 事件回调类型
# ============================================================================

# on_token(token: str) -> None
TokenCallback = Callable[[str], None]
# on_tool_call(name: str, args: dict) -> None
ToolCallCallback = Callable[[str, dict], None]
# on_error(message: str) -> None
ErrorCallback = Callable[[str], None]


class AgentIntegration:
    """Agent Loop 集成层

    封装 Agent Loop 的初始化、流式/非流式处理逻辑，以及线程安全的 UI 更新队列。
    供 GrassFlowREPL 和其他消费方使用。
    """

    def __init__(
        self,
        config_manager: Any = None,
        session_manager: Any = None,
        enable_streaming: bool = True,
    ):
        """初始化集成层

        Args:
            config_manager: 配置管理器（用于初始化 Agent Loop）
            session_manager: 会话管理器（可选）
            enable_streaming: 是否启用流式输出
        """
        self._config_manager = config_manager
        self._session_mgr = session_manager
        self._enable_streaming = enable_streaming

        # Agent Loop 实例（延迟初始化）
        self._agent_loop: Any = None  # 类型: Optional[AgentLoop]

        # 线程安全 UI 更新队列：Agent Loop 后台线程 → UI 主线程
        self._ui_update_queue: queue.Queue = queue.Queue()

        # 运行状态
        self._agent_running: bool = False

        # 统计
        self._token_count: int = 0
        self._api_call_count: int = 0

        # MCP 管理器（延迟初始化）
        self._mcp_manager: Any = None

        # Skills 管理器（延迟初始化）
        self._skills_manager: Any = None

    # ==================== 初始化 ====================

    def init_agent_loop(self) -> bool:
        """初始化 Agent Loop（使用 create_agent_loop_from_config）

        初始化顺序：
        1. 获取全局 ToolRegistry
        2. 注册内置工具（ShellTool, ReadTool, WriteTool, GlobTool, GrepTool）
        3. 启动 MCP 服务器并注册 MCP 工具
        4. 初始化 SkillsManager
        5. 创建 AgentLoop

        Returns:
            True 表示初始化成功，False 表示失败（将回退到 echo 模式）
        """
        try:
            from tui.agent_loop import AgentLoop, create_agent_loop_from_config
            from core.tool_registry import get_default_registry, register_builtin_tools

            tool_registry = get_default_registry()

            # 1. Register built-in tools (ShellTool, ReadTool, etc.)
            try:
                count = register_builtin_tools(tool_registry)
                if count:
                    logger.info("Registered %d builtin tools", count)
            except Exception as e:
                logger.warning("Failed to register builtin tools: %s", e)

            # 2. Start MCP servers and register MCP tools
            try:
                from tui.mcp_integration import MCPManager
                from tui.config_integration import load_config as _load_cfg
                _cfg_obj = _load_cfg()
                mcp_config = _cfg_obj.mcp_servers if _cfg_obj.mcp_servers else None
                if mcp_config:
                    self._mcp_manager = MCPManager()
                    self._mcp_manager.load_config({"mcp_servers": mcp_config})

                    # Register callback: when MCP servers finish connecting,
                    # re-register tools into the shared tool_registry and log.
                    def _on_mcp_ready():
                        try:
                            cnt = self._mcp_manager.register_tools_to_registry(tool_registry)
                            if cnt:
                                logger.info(
                                    "MCP on_ready: %d tools registered into tool registry", cnt
                                )
                        except Exception as cb_err:
                            logger.warning("MCP on_ready tool registration error: %s", cb_err)

                    self._mcp_manager.set_on_ready_callback(_on_mcp_ready)

                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Schedule MCP startup as background task.
                            # start_all() now waits for connected_event per server,
                            # so tools are registered before the task completes.
                            # The on_ready callback fires after tools are in the registry.
                            loop.create_task(self._mcp_manager.start_all())
                            logger.info("MCP startup scheduled as background task")
                        else:
                            loop.run_until_complete(self._mcp_manager.start_all())
                    except RuntimeError:
                        logger.debug("No event loop for MCP startup, will start later")

                    # Register any already-discovered MCP tools (covers the
                    # synchronous path where start_all() already completed).
                    try:
                        mcp_count = self._mcp_manager.register_tools_to_registry(tool_registry)
                        if mcp_count:
                            logger.info("Registered %d MCP tools into tool registry", mcp_count)
                    except Exception as reg_err:
                        logger.warning("MCP tool registration error: %s", reg_err)
            except Exception as e:
                logger.warning("MCP initialization failed: %s", e)
                self._mcp_manager = None

            # 3. Initialize SkillsManager
            try:
                from tui.skills_system import get_skills_manager
                self._skills_manager = get_skills_manager()
                logger.info("SkillsManager initialized.")
            except Exception as e:
                logger.warning("SkillsManager init failed: %s", e)
                self._skills_manager = None

            # 4. Create agent loop
            self._agent_loop = create_agent_loop_from_config(tool_registry=tool_registry)
            logger.info("Agent loop initialized successfully.")
            return True
        except ImportError as e:
            logger.warning("AgentLoop not available: %s — falling back to echo mode.", e)
            self._agent_loop = None
            return False
        except Exception as e:
            logger.error("Failed to initialize agent loop: %s", e)
            self._agent_loop = None
            return False

    @property
    def is_initialized(self) -> bool:
        """Agent Loop 是否已初始化"""
        return self._agent_loop is not None

    @property
    def is_running(self) -> bool:
        """Agent Loop 是否正在运行"""
        return self._agent_running

    @property
    def token_count(self) -> int:
        """累计 token 数"""
        return self._token_count

    @property
    def api_call_count(self) -> int:
        """累计 API 调用次数"""
        return self._api_call_count

    # ==================== 流式处理 ====================

    async def process_streaming(
        self,
        text: str,
        history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: str = "",
        reasoning_effort: Optional[str] = None,
        on_token: Optional[TokenCallback] = None,
        on_thinking: Optional[TokenCallback] = None,
        on_tool_call_start: Optional[ToolCallCallback] = None,
        on_tool_result: Optional[Callable[[str, bool], None]] = None,
        on_error: Optional[ErrorCallback] = None,
        on_usage: Optional[Callable[[dict], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
    ) -> AsyncIterator[Any]:
        """流式处理消息（在主 asyncio 事件循环中运行）

        将 Agent Loop 的 LoopEvent 逐个 yield 给调用方，
        同时可选地触发回调函数。

        Args:
            text: 用户输入文本
            history: 历史消息列表 [{"role": "user"|"assistant", "content": "..."}]
            system_prompt: 系统提示词
            on_token: 流式文本 token 回调
            on_thinking: 思考 token 回调
            on_tool_call_start: 工具调用开始回调
            on_tool_result: 工具结果回调 (result_text, is_error)
            on_error: 错误回调
            on_usage: 使用统计回调
            on_done: 处理完成回调

        Yields:
            LoopEvent 对象
        """
        if not self._agent_loop:
            raise RuntimeError("Agent Loop not initialized. Call init_agent_loop() first.")

        self._agent_running = True
        try:
            history = history or []
            async for event in self._agent_loop.process_streaming(text, history, system_prompt, reasoning_effort=reasoning_effort):
                etype = event.type
                edata = event.data

                # 更新统计
                if etype == "usage" and isinstance(edata, dict):
                    self._token_count = edata.get("total_tokens", self._token_count)
                    self._api_call_count += 1
                    if on_usage:
                        on_usage(edata)

                elif etype == "text_delta":
                    if on_token:
                        on_token(edata.get("text", ""))

                elif etype == "thinking_delta":
                    if on_thinking:
                        on_thinking(edata.get("text", ""))

                elif etype == "tool_call_start":
                    if on_tool_call_start:
                        on_tool_call_start(
                            edata.get("name", "?"),
                            edata.get("args", {}),
                        )

                elif etype == "tool_result":
                    if on_tool_result:
                        result = edata.get("result", edata.get("output", ""))
                        is_err = edata.get("is_error", edata.get("success", True) is False)
                        on_tool_result(str(result)[:800], is_err)

                elif etype == "error":
                    if on_error:
                        on_error(edata.get("message", str(edata)))

                yield event

            if on_done:
                on_done()

        except Exception as e:
            if on_error:
                on_error(f"Agent error: {e}\n{traceback.format_exc()}")
            raise
        finally:
            self._agent_running = False

    # ==================== 非流式处理 ====================

    async def process(
        self,
        text: str,
        history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: str = "",
        reasoning_effort: Optional[str] = None,
    ) -> str:
        """非流式处理消息

        消费整个事件流，返回最终的文本响应。

        Args:
            text: 用户输入文本
            history: 历史消息列表
            system_prompt: 系统提示词
            reasoning_effort: 推理力度 ("low" | "medium" | "high" | "xhigh")

        Returns:
            完整的 assistant 回复文本
        """
        full_text = ""

        async for event in self.process_streaming(
            text=text,
            history=history,
            system_prompt=system_prompt,
            reasoning_effort=reasoning_effort,
        ):
            if event.type == "text_delta":
                full_text += event.data.get("text", "")

        return full_text

    # ==================== 后台线程处理 ====================

    def process_in_background(
        self,
        text: str,
        history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: str = "",
        reasoning_effort: Optional[str] = None,
        on_done: Optional[Callable[[], None]] = None,
    ) -> threading.Thread:
        """在后台线程中运行 Agent Loop（适用于无 asyncio 事件循环的场景）

        UI 更新通过 _ui_update_queue 线程安全队列传递到主线程。

        Args:
            text: 用户输入文本
            history: 历史消息列表
            system_prompt: 系统提示词
            on_done: 处理完成回调（在后台线程中调用）

        Returns:
            后台线程对象
        """
        if not self._agent_loop:
            raise RuntimeError("Agent Loop not initialized. Call init_agent_loop() first.")

        self._agent_running = True

        def _run():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    self._background_agent_loop(text, history or [], system_prompt, reasoning_effort)
                )
                loop.close()
            except Exception as e:
                self._ui_update_queue.put(("error", {"message": f"Agent error: {e}"}))
            finally:
                self._agent_running = False
                self._ui_update_queue.put(("agent_done", {}))
                if on_done:
                    on_done()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    async def _background_agent_loop(
        self,
        text: str,
        history: List[Dict[str, Any]],
        system_prompt: str,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        """后台线程中的异步 Agent Loop

        将 UI 更新推入 _ui_update_queue，由主线程的定时器消费。
        """

        def _push_ui(action: str, **kwargs):
            self._ui_update_queue.put((action, kwargs))

        try:
            async for event in self._agent_loop.process_streaming(text, history, system_prompt, reasoning_effort=reasoning_effort):
                etype = event.type
                edata = event.data

                if etype == "loop_start" or etype == "loop_end":
                    pass

                elif etype == "text_delta":
                    _push_ui("text_delta", text=edata.get("text", ""))

                elif etype == "text_end":
                    _push_ui("text_end")

                elif etype == "thinking_delta":
                    _push_ui("thinking_delta", text=edata.get("text", ""))

                elif etype == "tool_call_start":
                    _push_ui(
                        "tool_call_start",
                        name=edata.get("name", "?"),
                        args=edata.get("args", {}),
                    )

                elif etype == "tool_call_end":
                    pass

                elif etype == "tool_result":
                    result = edata.get("result", edata.get("output", ""))
                    is_err = edata.get("is_error", edata.get("success", True) is False)
                    _push_ui("tool_result", output=str(result)[:800], is_error=is_err)

                elif etype == "error":
                    _push_ui("error", message=edata.get("message", str(edata)))

                elif etype == "interrupted":
                    _push_ui("interrupted")
                    break

                elif etype == "usage":
                    if isinstance(edata, dict):
                        self._token_count = edata.get("total_tokens", self._token_count)
                        self._api_call_count += 1
                    _push_ui("invalidate")

        except ImportError:
            _push_ui("error", message="AgentLoop module not found. Install required dependencies.")
        except Exception as e:
            _push_ui("error", message=f"Agent error: {e}\n{traceback.format_exc()}")

    # ==================== 同步回显模式 ====================

    def process_echo(
        self,
        text: str,
        console: Any = None,
    ) -> str:
        """降级回显模式：在无 Agent Loop 时直接回显用户输入

        Args:
            text: 用户输入文本
            console: Rich Console 实例（可选）
        """
        if console:
            console.print(f"  {text}")
        return text

    # ==================== 降级模式流式处理 ====================

    def process_streaming_sync(
        self,
        text: str,
        console: Any,
        history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: str = "",
        reasoning_effort: Optional[str] = None,
    ) -> None:
        """同步流式处理（降级模式，使用 asyncio.run 消费事件流）

        适用于无法使用 prompt_toolkit 事件循环的场景（如 fallback REPL）。

        Args:
            text: 用户输入文本
            console: Rich Console 实例
            history: 历史消息列表
            system_prompt: 系统提示词
        """
        if not self._agent_loop:
            console.print(f"  {text}")
            return

        async def _consume():
            full_text = ""
            thinking_shown = False
            async for event in self._agent_loop.process_streaming(text, history or [], system_prompt, reasoning_effort=reasoning_effort):
                etype = event.type
                edata = event.data

                if etype in ("text_delta",):
                    token = edata.get("text", "")
                    full_text += token
                    console.print(token, end="", highlight=False)

                elif etype == "thinking_delta":
                    token = edata.get("text", "")
                    if not full_text and not thinking_shown:
                        console.print("  [dim italic]思考中...[/dim italic]")
                        thinking_shown = True

                elif etype == "tool_call_start":
                    name = edata.get("name", "?")
                    args = edata.get("args", {})
                    args_str = json.dumps(args, ensure_ascii=False)[:200] if args else ""
                    console.print(f"\n  [bold yellow][tool] Calling {name}[/bold yellow]", highlight=False)
                    if args_str:
                        console.print(f"  [dim]  args: {args_str}[/dim]", highlight=False)

                elif etype == "tool_result":
                    result = edata.get("result", edata.get("output", ""))
                    is_err = edata.get("is_error", edata.get("success", True) is False)
                    style = "bold red" if is_err else "dim"
                    result_preview = str(result)[:500]
                    console.print(f"  [{style}][tool result] {result_preview}[/{style}]", highlight=False)

                elif etype == "error":
                    msg = edata.get("message", str(edata))
                    console.print(f"\n  [bold red][error] {msg}[/bold red]", highlight=False)

                elif etype == "interrupted":
                    console.print("\n  [yellow]Interrupted.[/yellow]", highlight=False)

                elif etype == "usage" and isinstance(edata, dict):
                    self._token_count = edata.get("total_tokens", self._token_count)
                    self._api_call_count += 1

        asyncio.run(_consume())

    # ==================== UI 更新队列 ====================

    def drain_ui_updates(self) -> List[Tuple[str, Dict[str, Any]]]:
        """从 UI 更新队列中取出所有待处理的更新

        主线程应定期调用此方法来消费后台线程产出的 UI 更新。

        Returns:
            [(action, kwargs), ...] 列表
        """
        updates = []
        try:
            while True:
                updates.append(self._ui_update_queue.get_nowait())
        except queue.Empty:
            pass
        return updates

    def get_ui_update_queue(self) -> queue.Queue:
        """获取 UI 更新队列（供直接消费）

        Returns:
            线程安全的 Queue 实例
        """
        return self._ui_update_queue

    # ==================== 中断 ====================

    def interrupt(self) -> None:
        """中断 Agent 执行"""
        if self._agent_loop:
            try:
                self._agent_loop.interrupt()
            except Exception:
                pass
        self._agent_running = False

    async def shutdown(self) -> None:
        """Shutdown MCP servers and clean up resources."""
        if self._mcp_manager:
            try:
                await self._mcp_manager.stop_all()
            except Exception:
                pass

    # ==================== 统计重置 ====================

    def reset_stats(self) -> None:
        """重置统计计数"""
        self._token_count = 0
        self._api_call_count = 0

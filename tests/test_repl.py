"""
GrassFlow REPL 测试

测试 REPL 的核心功能：
- 命令解析和执行
- 消息渲染
- 中断处理
- 输入历史
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from io import StringIO
from datetime import datetime

# 导入待测模块
from tui.repl import (
    Message,
    MessageRole,
    MessageRenderer,
    CommandHandler,
    CommandResult,
    InputHandler,
    REPL,
    create_repl,
    run_repl,
)


# ==================== Message 测试 ====================

class TestMessage:
    """Message 类测试"""

    def test_create_message(self):
        """测试创建消息"""
        msg = Message(MessageRole.USER, "Hello")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"
        assert isinstance(msg.timestamp, datetime)
        assert msg.metadata == {}

    def test_create_message_with_metadata(self):
        """测试带元数据创建消息"""
        meta = {"key": "value"}
        msg = Message(MessageRole.ASSISTANT, "Response", metadata=meta)
        assert msg.metadata == {"key": "value"}

    def test_message_repr(self):
        """测试消息字符串表示"""
        msg = Message(MessageRole.USER, "This is a test message that is quite long")
        repr_str = repr(msg)
        assert "user" in repr_str
        assert "This is a test message" in repr_str

    def test_message_roles(self):
        """测试所有消息角色"""
        for role in MessageRole:
            msg = Message(role, f"Test {role.value}")
            assert msg.role == role


# ==================== CommandHandler 测试 ====================

class TestCommandHandler:
    """CommandHandler 类测试"""

    def setup_method(self):
        """测试前准备"""
        self.handler = CommandHandler()

    def test_parse_command(self):
        """测试命令解析"""
        result = self.handler.parse("/help")
        assert result is not None
        assert result[0] == "help"
        assert result[1] == []

    def test_parse_command_with_args(self):
        """测试带参数的命令解析"""
        result = self.handler.parse("/run workflow.af")
        assert result is not None
        assert result[0] == "run"
        assert result[1] == ["workflow.af"]

    def test_parse_not_command(self):
        """测试非命令输入"""
        result = self.handler.parse("Hello, this is a message")
        assert result is None

    def test_parse_empty_command(self):
        """测试空命令"""
        result = self.handler.parse("/")
        assert result is None

    def test_execute_help_command(self):
        """测试 help 命令"""
        result = self.handler.execute("/help")
        assert result.success is True
        assert "Available commands" in result.message

    def test_execute_unknown_command(self):
        """测试未知命令"""
        result = self.handler.execute("/unknown")
        assert result.success is False
        assert "Unknown command" in result.message

    def test_execute_not_command(self):
        """测试非命令执行"""
        result = self.handler.execute("Hello")
        assert result.success is False
        assert "Not a command" in result.message

    def test_exit_command(self):
        """测试退出命令"""
        result = self.handler.execute("/exit")
        assert result.success is True
        assert result.should_exit is True

    def test_exit_aliases(self):
        """测试退出命令别名"""
        for cmd in ["/exit", "/quit", "/q"]:
            result = self.handler.execute(cmd)
            assert result.should_exit is True, f"Failed for {cmd}"

    def test_clear_command(self):
        """测试清屏命令"""
        result = self.handler.execute("/clear")
        assert result.success is True
        assert result.data == {"action": "clear"}

    def test_run_command_no_args(self):
        """测试 run 命令无参数"""
        result = self.handler.execute("/run")
        assert result.success is False
        assert "Usage" in result.message

    def test_run_command_with_args(self):
        """测试 run 命令带参数"""
        result = self.handler.execute("/run test.af")
        assert result.success is True
        assert result.data == {"action": "run", "file": "test.af"}

    def test_validate_command_no_args(self):
        """测试 validate 命令无参数"""
        result = self.handler.execute("/validate")
        assert result.success is False
        assert "Usage" in result.message

    def test_validate_command_with_args(self):
        """测试 validate 命令带参数"""
        result = self.handler.execute("/validate test.af")
        assert result.success is True
        assert result.data == {"action": "validate", "file": "test.af"}

    def test_register_custom_command(self):
        """测试注册自定义命令"""
        def custom_handler(args):
            return CommandResult(success=True, message="Custom!")

        self.handler.register("custom", custom_handler, "Custom command")
        result = self.handler.execute("/custom")
        assert result.success is True
        assert result.message == "Custom!"

    def test_get_help_text(self):
        """测试获取帮助文本"""
        help_text = self.handler.get_help_text()
        assert "Available commands" in help_text
        assert "/help" in help_text
        assert "/run" in help_text
        assert "/exit" in help_text


# ==================== CommandResult 测试 ====================

class TestCommandResult:
    """CommandResult 类测试"""

    def test_default_values(self):
        """测试默认值"""
        result = CommandResult()
        assert result.success is True
        assert result.message == ""
        assert result.should_exit is False
        assert result.data is None

    def test_custom_values(self):
        """测试自定义值"""
        result = CommandResult(
            success=False,
            message="Error",
            should_exit=True,
            data={"key": "value"},
        )
        assert result.success is False
        assert result.message == "Error"
        assert result.should_exit is True
        assert result.data == {"key": "value"}


# ==================== InputHandler 测试 ====================

class TestInputHandler:
    """InputHandler 类测试"""

    def setup_method(self):
        """测试前准备"""
        self.handler = InputHandler()

    def test_add_to_history(self):
        """测试添加历史记录"""
        self.handler.add_to_history("first")
        self.handler.add_to_history("second")
        assert len(self.handler.history) == 2
        assert self.handler.history == ["first", "second"]

    def test_no_duplicate_history(self):
        """测试不重复添加历史"""
        self.handler.add_to_history("same")
        self.handler.add_to_history("same")
        assert len(self.handler.history) == 1

    def test_no_empty_history(self):
        """测试不添加空历史"""
        self.handler.add_to_history("")
        self.handler.add_to_history("   ")
        assert len(self.handler.history) == 0

    def test_history_max_size(self):
        """测试历史记录大小限制"""
        handler = InputHandler(history_max_size=3)
        handler.add_to_history("a")
        handler.add_to_history("b")
        handler.add_to_history("c")
        handler.add_to_history("d")
        assert len(handler.history) == 3
        assert handler.history == ["b", "c", "d"]

    def test_get_previous(self):
        """测试获取上一条历史"""
        self.handler.add_to_history("first")
        self.handler.add_to_history("second")
        self.handler.add_to_history("third")
        self.handler.reset_history_index()

        assert self.handler.get_previous() == "third"
        assert self.handler.get_previous() == "second"
        assert self.handler.get_previous() == "first"
        assert self.handler.get_previous() == "first"  # 已到顶部

    def test_get_next(self):
        """测试获取下一条历史"""
        self.handler.add_to_history("first")
        self.handler.add_to_history("second")
        self.handler.reset_history_index()

        # 先移到上一条（second, index=1）
        self.handler.get_previous()
        # 再移到上一条（first, index=0）
        self.handler.get_previous()
        # 下一条回到 second
        assert self.handler.get_next() == "second"
        # 再下一条应该返回空（已在末尾）
        assert self.handler.get_next() == ""

    def test_interrupt_handling(self):
        """测试中断处理"""
        assert self.handler.is_interrupted is False

        self.handler.signal_interrupt()
        assert self.handler.is_interrupted is True

        self.handler.clear_interrupt()
        assert self.handler.is_interrupted is False

    def test_reset_history_index(self):
        """测试重置历史索引"""
        self.handler.add_to_history("a")
        self.handler.add_to_history("b")
        self.handler.get_previous()
        self.handler.reset_history_index()
        # 重置后应该指向末尾
        assert self.handler.history_index == len(self.handler.history)


# ==================== MessageRenderer 测试 ====================

class TestMessageRenderer:
    """MessageRenderer 类测试"""

    def setup_method(self):
        """测试前准备"""
        self.console = MagicMock()
        self.renderer = MessageRenderer(console=self.console)

    def test_render_user_message(self):
        """测试渲染用户消息"""
        msg = Message(MessageRole.USER, "Hello")
        self.renderer.render_message(msg)
        self.console.print.assert_called()

    def test_render_assistant_message(self):
        """测试渲染助手消息"""
        msg = Message(MessageRole.ASSISTANT, "Response")
        self.renderer.render_message(msg)
        self.console.print.assert_called()

    def test_render_system_message(self):
        """测试渲染系统消息"""
        msg = Message(MessageRole.SYSTEM, "System notice")
        self.renderer.render_message(msg)
        self.console.print.assert_called()

    def test_render_error_message(self):
        """测试渲染错误消息"""
        msg = Message(MessageRole.ERROR, "Error occurred")
        self.renderer.render_message(msg)
        self.console.print.assert_called()

    def test_render_markdown(self):
        """测试渲染 Markdown"""
        self.renderer.render_markdown("# Hello\n\nWorld")
        self.console.print.assert_called()

    def test_render_code(self):
        """测试渲染代码块"""
        self.renderer.render_code("print('hello')", "python")
        self.console.print.assert_called()

    def test_render_table(self):
        """测试渲染表格"""
        self.renderer.render_table("Test", ["A", "B"], [["1", "2"]])
        self.console.print.assert_called()

    def test_render_panel(self):
        """测试渲染面板"""
        self.renderer.render_panel("Content", title="Test")
        self.console.print.assert_called()

    def test_looks_like_markdown(self):
        """测试 Markdown 检测"""
        assert self.renderer._looks_like_markdown("# Title") is True
        assert self.renderer._looks_like_markdown("**bold**") is True
        assert self.renderer._looks_like_markdown("```python\ncode\n```") is True
        assert self.renderer._looks_like_markdown("Simple text") is False


# ==================== REPL 测试 ====================

class TestREPL:
    """REPL 类测试"""

    def setup_method(self):
        """测试前准备"""
        self.console = MagicMock()
        self.repl = REPL(console=self.console)

    def test_create_repl(self):
        """测试创建 REPL"""
        repl = REPL()
        assert repl is not None
        assert repl._running is False

    def test_create_repl_with_callback(self):
        """测试带回调创建 REPL"""
        callback = MagicMock(return_value="response")
        repl = REPL(on_message=callback)
        assert repl.on_message == callback

    def test_process_empty_input(self):
        """测试处理空输入"""
        result = self.repl._process_input("")
        assert result is False

    def test_process_whitespace_input(self):
        """测试处理空白输入"""
        result = self.repl._process_input("   ")
        assert result is False

    def test_process_exit_command(self):
        """测试处理退出命令"""
        result = self.repl._process_input("/exit")
        assert result is True

    def test_process_help_command(self):
        """测试处理帮助命令"""
        result = self.repl._process_input("/help")
        assert result is False

    def test_process_clear_command(self):
        """测试处理清屏命令"""
        result = self.repl._process_input("/clear")
        assert result is False

    def test_process_message_with_callback(self):
        """测试处理消息（带回调）"""
        callback = MagicMock(return_value="Response!")
        repl = REPL(console=self.console, on_message=callback)

        repl._process_input("Hello")
        callback.assert_called_once_with("Hello")

    def test_process_message_callback_exception(self):
        """测试回调异常处理"""
        callback = MagicMock(side_effect=Exception("Test error"))
        repl = REPL(console=self.console, on_message=callback)

        # 不应抛出异常
        repl._process_input("Hello")
        assert len(repl.messages) == 2  # user + error

    def test_clear_screen(self):
        """测试清屏"""
        self.repl._clear_screen()
        self.console.clear.assert_called_once()

    def test_stop(self):
        """测试停止"""
        self.repl._running = True
        self.repl.stop()
        assert self.repl._running is False

    def test_message_history(self):
        """测试消息历史"""
        callback = MagicMock(return_value="ok")
        repl = REPL(console=self.console, on_message=callback)

        repl._process_input("First message")
        repl._process_input("Second message")

        # 2 user messages + 2 assistant messages
        assert len(repl.messages) == 4

    def test_get_prompt_text(self):
        """测试获取提示符"""
        prompt = self.repl._get_prompt_text()
        assert prompt == ">>> "


# ==================== 便捷函数测试 ====================

class TestConvenienceFunctions:
    """便捷函数测试"""

    def test_create_repl(self):
        """测试 create_repl 函数"""
        repl = create_repl()
        assert isinstance(repl, REPL)

    def test_create_repl_with_callback(self):
        """测试 create_repl 带回调"""
        callback = MagicMock()
        repl = create_repl(on_message=callback)
        assert repl.on_message == callback


# ==================== 集成测试 ====================

class TestIntegration:
    """集成测试"""

    def test_command_flow(self):
        """测试完整命令流程"""
        handler = CommandHandler()

        # 帮助命令
        result = handler.execute("/help")
        assert result.success

        # 退出命令
        result = handler.execute("/exit")
        assert result.should_exit

    def test_message_rendering_flow(self):
        """测试完整消息渲染流程"""
        console = MagicMock()
        renderer = MessageRenderer(console=console)

        # 渲染不同类型的消息
        messages = [
            Message(MessageRole.USER, "User message"),
            Message(MessageRole.ASSISTANT, "Assistant response"),
            Message(MessageRole.SYSTEM, "System notice"),
            Message(MessageRole.ERROR, "Error message"),
        ]

        for msg in messages:
            renderer.render_message(msg)

        # 每条消息至少调用一次 console.print
        assert console.print.call_count >= len(messages)

    def test_input_history_flow(self):
        """测试输入历史流程"""
        handler = InputHandler()

        # 添加历史
        for i in range(5):
            handler.add_to_history(f"message {i}")

        # 浏览历史
        handler.reset_history_index()
        assert handler.get_previous() == "message 4"
        assert handler.get_previous() == "message 3"
        assert handler.get_next() == "message 4"


# ==================== 运行测试 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

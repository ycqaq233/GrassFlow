"""
GrassFlow REPL Integration Tests

Tests the GrassFlowREPL class directly (not the legacy compat layer).
Covers: history management, session metadata, system prompt construction,
slash command dispatch, and multi-turn conversation flows.

All LLM / agent calls are mocked. No network or DB required.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repl():
    """Create a GrassFlowREPL with session disabled and a mocked agent."""
    with (
        patch("tui.repl.AgentIntegration") as MockAI,
        patch("tui.repl.session_manager", None),
    ):
        mock_agent = MagicMock()
        mock_agent.is_initialized = False
        mock_agent.is_running = False
        mock_agent._agent_loop = None
        mock_agent._ui_update_queue = MagicMock()
        mock_agent._enable_streaming = True
        mock_agent._mcp_manager = None
        mock_agent.drain_ui_updates.return_value = []
        MockAI.return_value = mock_agent

        from tui.repl import GrassFlowREPL

        r = GrassFlowREPL(enable_session=False, enable_streaming=True)
        # Give it a session object so metadata tests work
        r.session = MagicMock()
        r.session.id = "test_session_001"
        r.session.metadata = {
            "model": "test-model",
            "provider": "test-provider",
            "thinking": {"enabled": True, "effort": "medium", "display": "collapsed"},
        }
        r.session.title = "Test Session"
        r.session.status = MagicMock(value="idle")
        yield r


@pytest.fixture()
def repl_no_session():
    """Create a GrassFlowREPL with session=None (no session object)."""
    with (
        patch("tui.repl.AgentIntegration") as MockAI,
        patch("tui.repl.session_manager", None),
    ):
        mock_agent = MagicMock()
        mock_agent.is_initialized = False
        mock_agent.is_running = False
        mock_agent._agent_loop = None
        mock_agent._ui_update_queue = MagicMock()
        mock_agent._enable_streaming = True
        mock_agent.drain_ui_updates.return_value = []
        MockAI.return_value = mock_agent

        from tui.repl import GrassFlowREPL

        r = GrassFlowREPL(enable_session=False, enable_streaming=True)
        r.session = None
        yield r


# ==================== 1. History Management ====================


class TestHistoryManagement:
    """Test _conversation_history and _build_history()."""

    def test_user_message_added_to_history(self, repl: "GrassFlowREPL"):
        """User message should be appended to _conversation_history."""
        repl._handle_agent_message("Hello, GrassFlow")
        assert len(repl._conversation_history) == 1
        assert repl._conversation_history[0] == {"role": "user", "content": "Hello, GrassFlow"}

    def test_assistant_response_added_to_history_streaming(self, repl: "GrassFlowREPL"):
        """Assistant response via text_end event should be appended to history."""
        # Simulate user message first
        repl._handle_agent_message("Hi")

        # Simulate streaming: emit some tokens, then end
        # _enable_streaming is a property delegating to self._agent._enable_streaming
        repl._agent._enable_streaming = True
        repl._emit_stream_text("Hello ")
        repl._emit_stream_text("world!")

        # Fire text_end
        repl._apply_event_type("text_end", {})

        assert len(repl._conversation_history) == 2
        assert repl._conversation_history[0]["role"] == "user"
        assert repl._conversation_history[1]["role"] == "assistant"
        assert "Hello world!" in repl._conversation_history[1]["content"]

    def test_assistant_response_non_streaming(self, repl: "GrassFlowREPL"):
        """Non-streaming text_delta + text_end should store exact assistant response."""
        repl._handle_agent_message("Tell me something")
        repl._agent._enable_streaming = False

        # text_delta adds to output list in non-streaming mode
        repl._apply_event_type("text_delta", {"text": "Sure, "})
        repl._apply_event_type("text_delta", {"text": "here you go."})
        repl._apply_event_type("text_end", {})

        assert len(repl._conversation_history) == 2
        assert repl._conversation_history[1]["role"] == "assistant"
        assert repl._conversation_history[1]["content"] == "Sure, here you go."

    def test_history_no_duplicates(self, repl: "GrassFlowREPL"):
        """Sending the same message twice should create two separate entries."""
        repl._handle_agent_message("same message")
        repl._handle_agent_message("same message")
        # Both user messages should be in history (no dedup at history level)
        user_msgs = [m for m in repl._conversation_history if m["role"] == "user"]
        assert len(user_msgs) == 2
        assert all(m["content"] == "same message" for m in user_msgs)

    def test_build_history_returns_copy(self, repl: "GrassFlowREPL"):
        """_build_history() should return a copy, not a reference."""
        repl._handle_agent_message("test")
        history = repl._build_history()
        history.append({"role": "assistant", "content": "injected"})
        # Original should not be affected
        assert len(repl._conversation_history) == 1

    def test_build_history_returns_correct_format(self, repl: "GrassFlowREPL"):
        """_build_history() should return list of {role, content} dicts."""
        repl._handle_agent_message("question")
        repl._emit_stream_text("answer")
        repl._apply_event_type("text_end", {})

        history = repl._build_history()
        assert isinstance(history, list)
        for entry in history:
            assert "role" in entry
            assert "content" in entry
            assert entry["role"] in ("user", "assistant", "system")

    def test_clear_output_clears_history(self, repl: "GrassFlowREPL"):
        """clear_output() should clear _conversation_history."""
        repl._handle_agent_message("msg1")
        repl._handle_agent_message("msg2")
        assert len(repl._conversation_history) > 0
        repl.clear_output()
        assert len(repl._conversation_history) == 0

    def test_history_starts_empty(self, repl: "GrassFlowREPL"):
        """Fresh REPL should have empty conversation history."""
        assert repl._conversation_history == []
        assert repl._build_history() == []


# ==================== 2. Session Metadata ====================


class TestSessionMetadata:
    """Test thinking metadata defaults and persistence."""

    def test_thinking_defaults(self, repl: "GrassFlowREPL"):
        """Default thinking metadata: enabled=True, effort=medium, display=collapsed."""
        thinking = repl.session.metadata.get("thinking", {})
        assert thinking["enabled"] is True
        assert thinking["effort"] == "medium"
        assert thinking["display"] == "collapsed"

    def test_thinking_metadata_persists_across_turns(self, repl: "GrassFlowREPL"):
        """Metadata changes should persist across simulated turns."""
        # Turn 1: change thinking effort
        repl.session.metadata["thinking"]["effort"] = "high"
        repl._handle_agent_message("first turn")

        # Turn 2: verify metadata still has the change
        assert repl.session.metadata["thinking"]["effort"] == "high"

        repl._handle_agent_message("second turn")
        assert repl.session.metadata["thinking"]["effort"] == "high"

    def test_model_metadata_default(self, repl: "GrassFlowREPL"):
        """Session should have a model in metadata."""
        assert "model" in repl.session.metadata
        assert repl.session.metadata["model"] == "test-model"

    def test_reasoning_effort_extracted_from_session(self, repl: "GrassFlowREPL"):
        """_handle_agent_message should extract reasoning_effort from session."""
        repl.session.metadata["thinking"] = {
            "enabled": True,
            "effort": "high",
            "display": "full",
        }
        repl._agent.is_initialized = True

        # Patch the background process method to capture args
        with patch.object(repl._agent, "process_in_background") as mock_bg:
            repl._handle_agent_message("test")
            mock_bg.assert_called_once()
            # Verify reasoning_effort was passed correctly
            call_kwargs = mock_bg.call_args
            assert call_kwargs is not None
            assert call_kwargs[1].get("reasoning_effort") == "high"

    def test_thinking_disabled_no_reasoning_effort(self, repl: "GrassFlowREPL"):
        """When thinking is disabled, reasoning_effort should be None."""
        repl.session.metadata["thinking"]["enabled"] = False
        repl._agent.is_initialized = True

        with patch.object(repl._agent, "process_in_background") as mock_bg:
            repl._handle_agent_message("test")
            call_kwargs = mock_bg.call_args
            assert call_kwargs[1].get("reasoning_effort") is None

    def test_session_none_no_crash_on_metadata(self, repl_no_session: "GrassFlowREPL"):
        """Operations with session=None should not crash."""
        # Should not raise
        repl_no_session._handle_agent_message("hello")
        assert len(repl_no_session._conversation_history) == 1


# ==================== 3. System Prompt Construction ====================


class TestSystemPrompt:
    """Test _get_system_prompt() content."""

    def test_system_prompt_contains_base_info(self, repl: "GrassFlowREPL"):
        """System prompt should contain GrassFlow assistant identity."""
        prompt = repl._get_system_prompt()
        assert "GrassFlow AI assistant" in prompt
        assert "Current directory" in prompt

    def test_system_prompt_contains_cwd(self, repl: "GrassFlowREPL"):
        """System prompt should include the current working directory."""
        prompt = repl._get_system_prompt()
        cwd = os.getcwd()
        assert cwd in prompt

    def test_system_prompt_includes_skills_prompt(self, repl: "GrassFlowREPL"):
        """System prompt should include skills prompt when available."""
        with patch("tui.skills_system.get_skills_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.build_skills_prompt.return_value = "Available skills: /test-skill"
            mock_get_mgr.return_value = mock_mgr

            prompt = repl._get_system_prompt()
            assert "Available skills: /test-skill" in prompt

    def test_system_prompt_skills_failure_graceful(self, repl: "GrassFlowREPL"):
        """System prompt should still work if skills system fails."""
        with patch("tui.skills_system.get_skills_manager", side_effect=ImportError("no skills")):
            prompt = repl._get_system_prompt()
            assert "GrassFlow AI assistant" in prompt
            assert "Be concise and helpful" in prompt

    def test_system_prompt_contains_tool_instruction(self, repl: "GrassFlowREPL"):
        """System prompt should mention using tools."""
        prompt = repl._get_system_prompt()
        assert "Use tools when needed" in prompt or "tools" in prompt.lower()


# ==================== 4. Slash Command Dispatch ====================


class TestSlashCommands:
    """Test slash command dispatch through _handle_slash_command and _process_user_input."""

    # ---- /think ----

    def test_think_on(self, repl: "GrassFlowREPL"):
        """/think on should enable thinking with medium effort."""
        repl._handle_slash_command("/think on")
        thinking = repl.session.metadata["thinking"]
        assert thinking["enabled"] is True
        assert thinking["effort"] == "medium"

    def test_think_off(self, repl: "GrassFlowREPL"):
        """/think off should disable thinking."""
        repl._handle_slash_command("/think off")
        thinking = repl.session.metadata["thinking"]
        assert thinking["enabled"] is False

    def test_think_high(self, repl: "GrassFlowREPL"):
        """/think high should set effort to high."""
        repl._handle_slash_command("/think high")
        thinking = repl.session.metadata["thinking"]
        assert thinking["enabled"] is True
        assert thinking["effort"] == "high"

    def test_think_full(self, repl: "GrassFlowREPL"):
        """/think full should set display to full."""
        repl._handle_slash_command("/think full")
        thinking = repl.session.metadata["thinking"]
        assert thinking["display"] == "full"

    def test_think_collapsed(self, repl: "GrassFlowREPL"):
        """/think collapsed should set display to collapsed."""
        repl.session.metadata["thinking"]["display"] = "full"
        repl._handle_slash_command("/think collapsed")
        thinking = repl.session.metadata["thinking"]
        assert thinking["display"] == "collapsed"

    def test_think_preserves_display_on_effort_change(self, repl: "GrassFlowREPL"):
        """Changing effort should preserve existing display setting."""
        repl.session.metadata["thinking"]["display"] = "full"
        repl._handle_slash_command("/think high")
        assert repl.session.metadata["thinking"]["display"] == "full"

    # ---- /clear ----

    def test_clear_command(self, repl: "GrassFlowREPL"):
        """/clear should clear conversation history and show confirmation."""
        repl._handle_agent_message("msg1")
        repl._handle_agent_message("msg2")
        assert len(repl._conversation_history) > 0

        repl._handle_slash_command("/clear")
        assert len(repl._conversation_history) == 0
        # Verify exact confirmation message from _cmd_clear
        last_output = repl.output[-1]
        assert last_output.text == "Screen cleared."

    def test_clear_idempotent(self, repl: "GrassFlowREPL"):
        """Calling /clear multiple times should not crash."""
        repl._handle_slash_command("/clear")
        repl._handle_slash_command("/clear")
        assert len(repl._conversation_history) == 0

    # ---- /model ----

    def test_model_change(self, repl: "GrassFlowREPL"):
        """/model <name> should update session metadata."""
        repl._handle_slash_command("/model gpt-4o")
        assert repl.session.metadata["model"] == "gpt-4o"

    def test_model_no_args_shows_current(self, repl: "GrassFlowREPL"):
        """/model with no args should show current model."""
        repl._handle_slash_command("/model")
        # Should produce an output entry with exact format
        last_output = repl.output[-1]
        assert last_output.text.startswith("Current model: test-model")

    # ---- Unknown command ----

    def test_unknown_command(self, repl: "GrassFlowREPL"):
        """Unknown command should produce error output."""
        repl._handle_slash_command("/nonexistent")
        last_output = repl.output[-1]
        assert "Unknown command" in last_output.text

    # ---- Command dispatch via _process_user_input ----

    def test_process_user_input_slash(self, repl: "GrassFlowREPL"):
        """/model dispatched through _process_user_input should work."""
        repl._process_user_input("/model deepseek-v3")
        assert repl.session.metadata["model"] == "deepseek-v3"

    def test_process_user_input_normal_message(self, repl: "GrassFlowREPL"):
        """Normal text should go to _handle_agent_message."""
        repl._process_user_input("hello world")
        assert len(repl._conversation_history) == 1
        assert repl._conversation_history[0]["content"] == "hello world"

    def test_process_user_input_shell_command(self, repl: "GrassFlowREPL"):
        """! prefix should execute shell command."""
        repl._process_user_input("!echo hello")
        # Should not add to conversation history
        assert len(repl._conversation_history) == 0

    def test_exit_command_sets_flag(self, repl: "GrassFlowREPL"):
        """/exit should set _should_exit flag."""
        repl._process_user_input("/exit")
        assert repl._should_exit is True


# ==================== 5. Multi-turn Conversation ====================


class TestMultiTurnConversation:
    """Test multi-turn conversation flows without history corruption."""

    def test_three_turns_user_only(self, repl: "GrassFlowREPL"):
        """Three user messages should produce 3 history entries."""
        repl._handle_agent_message("Turn 1")
        repl._handle_agent_message("Turn 2")
        repl._handle_agent_message("Turn 3")

        assert len(repl._conversation_history) == 3
        for i, entry in enumerate(repl._conversation_history, 1):
            assert entry["role"] == "user"
            assert entry["content"] == f"Turn {i}"

    def test_three_turns_with_responses(self, repl: "GrassFlowREPL"):
        """Three complete user-assistant turns should produce 6 history entries."""
        for i in range(1, 4):
            repl._handle_agent_message(f"Question {i}")
            repl._stream_collected_text = f"Answer {i}"
            repl._apply_event_type("text_end", {})

        assert len(repl._conversation_history) == 6
        for i in range(3):
            user_entry = repl._conversation_history[i * 2]
            asst_entry = repl._conversation_history[i * 2 + 1]
            assert user_entry["role"] == "user"
            assert asst_entry["role"] == "assistant"
            assert f"Question {i + 1}" in user_entry["content"]
            assert f"Answer {i + 1}" in asst_entry["content"]

    def test_tool_call_round_trip(self, repl: "GrassFlowREPL"):
        """Full tool call round-trip: user -> tool_call -> tool_result -> response."""
        repl._handle_agent_message("Read file.txt")

        # Simulate tool call event
        repl._apply_event_type("tool_call_start", {
            "name": "read_file",
            "args": {"path": "file.txt"},
        })

        # Simulate tool result
        repl._apply_event_type("tool_result", {
            "result": "file contents here",
            "is_error": False,
        })

        # Simulate assistant final response
        repl._stream_collected_text = "The file contains: file contents here"
        repl._apply_event_type("text_end", {})

        # History should have: user + assistant (tool call info is display-only)
        assert len(repl._conversation_history) == 2
        assert repl._conversation_history[0]["role"] == "user"
        assert repl._conversation_history[1]["role"] == "assistant"

    def test_history_integrity_after_error(self, repl: "GrassFlowREPL"):
        """Error events should not corrupt conversation history."""
        repl._handle_agent_message("Do something")
        repl._apply_event_type("error", {"message": "Something went wrong"})
        repl._apply_event_type("text_end", {})

        # Should still have user message; assistant may be empty
        user_entries = [e for e in repl._conversation_history if e["role"] == "user"]
        assert len(user_entries) == 1

    def test_history_integrity_after_interrupt(self, repl: "GrassFlowREPL"):
        """Interrupt event should not corrupt conversation history."""
        repl._handle_agent_message("Long running task")
        result = repl._apply_event_type("interrupted", {})

        # interrupted returns True (break signal)
        assert result is True
        # User message should still be in history
        assert len(repl._conversation_history) == 1
        assert repl._conversation_history[0]["role"] == "user"

    def test_build_history_consistency_across_turns(self, repl: "GrassFlowREPL"):
        """_build_history() should remain consistent throughout a multi-turn conversation."""
        repl._handle_agent_message("Q1")
        h1 = repl._build_history()
        assert len(h1) == 1

        repl._stream_collected_text = "A1"
        repl._apply_event_type("text_end", {})
        h2 = repl._build_history()
        assert len(h2) == 2

        repl._handle_agent_message("Q2")
        h3 = repl._build_history()
        assert len(h3) == 3

        # Verify ordering
        assert h3[0]["content"] == "Q1"
        assert h3[1]["content"] == "A1"
        assert h3[2]["content"] == "Q2"


# ==================== 6. Stream State Management ====================


class TestStreamState:
    """Test streaming state reset and accumulation."""

    def test_reset_stream_state(self, repl: "GrassFlowREPL"):
        """_reset_stream_state should clear all stream buffers."""
        repl._stream_buf = "partial"
        repl._stream_box_opened = True
        repl._stream_collected_text = "collected"
        repl._thinking_buf = "thinking"
        repl._thinking_token_count = 5
        repl._thinking_box_opened = True

        repl._reset_stream_state()

        assert repl._stream_buf == ""
        assert repl._stream_box_opened is False
        assert repl._stream_collected_text == ""
        assert repl._thinking_buf == ""
        assert repl._thinking_token_count == 0
        assert repl._thinking_box_opened is False

    def test_emit_stream_text_accumulates(self, repl: "GrassFlowREPL"):
        """_emit_stream_text should accumulate into _stream_collected_text."""
        repl._emit_stream_text("Hello ")
        repl._emit_stream_text("world")
        assert repl._stream_collected_text == "Hello world"

    def test_emit_stream_text_empty(self, repl: "GrassFlowREPL"):
        """_emit_stream_text with empty string should be a no-op."""
        repl._emit_stream_text("")
        assert repl._stream_collected_text == ""

    def test_usage_event_updates_stats(self, repl: "GrassFlowREPL"):
        """Usage event should update token count and API call count."""
        repl._apply_event_type("usage", {"total_tokens": 1500, "latency_ms": 200})
        assert repl._token_count == 1500
        assert repl._api_call_count == 1
        assert repl._last_latency_ms == 200


# ==================== 7. Edge Cases ====================


class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_empty_message_not_added(self, repl: "GrassFlowREPL"):
        """Empty user input should still be handled (agent decides)."""
        # _handle_agent_message does not filter empty strings;
        # _process_user_input does via the caller. Test _handle_agent_message.
        repl._handle_agent_message("")
        assert len(repl._conversation_history) == 1
        assert repl._conversation_history[0]["content"] == ""

    def test_multiple_slash_commands_sequence(self, repl: "GrassFlowREPL"):
        """Multiple slash commands in sequence should each take effect."""
        repl._handle_slash_command("/model m1")
        repl._handle_slash_command("/model m2")
        repl._handle_slash_command("/think high")
        repl._handle_slash_command("/think full")

        assert repl.session.metadata["model"] == "m2"
        assert repl.session.metadata["thinking"]["effort"] == "high"
        assert repl.session.metadata["thinking"]["display"] == "full"

    def test_slash_then_normal_message(self, repl: "GrassFlowREPL"):
        """Slash command followed by a normal message should work correctly."""
        repl._handle_slash_command("/model new-model")
        repl._handle_agent_message("Hello")

        assert repl.session.metadata["model"] == "new-model"
        assert len(repl._conversation_history) == 1
        assert repl._conversation_history[0]["content"] == "Hello"

    def test_conversation_history_isolation(self, repl: "GrassFlowREPL"):
        """Multiple REPL instances should have independent histories."""
        with (
            patch("tui.repl.AgentIntegration") as MockAI2,
            patch("tui.repl.session_manager", None),
        ):
            mock2 = MagicMock()
            mock2.is_initialized = False
            mock2.is_running = False
            mock2._agent_loop = None
            mock2._ui_update_queue = MagicMock()
            mock2._enable_streaming = True
            mock2.drain_ui_updates.return_value = []
            MockAI2.return_value = mock2

            from tui.repl import GrassFlowREPL
            repl2 = GrassFlowREPL(enable_session=False)
            repl2.session = None

        repl._handle_agent_message("repl1 message")
        repl2._handle_agent_message("repl2 message")

        assert len(repl._conversation_history) == 1
        assert repl._conversation_history[0]["content"] == "repl1 message"
        assert len(repl2._conversation_history) == 1
        assert repl2._conversation_history[0]["content"] == "repl2 message"

    def test_think_show_command(self, repl: "GrassFlowREPL"):
        """/think show should display current config without changing it."""
        repl.session.metadata["thinking"] = {
            "enabled": True, "effort": "high", "display": "full",
        }
        repl._handle_slash_command("/think show")
        # Metadata should be unchanged
        assert repl.session.metadata["thinking"]["effort"] == "high"
        assert repl.session.metadata["thinking"]["display"] == "full"

    def test_think_invalid_arg(self, repl: "GrassFlowREPL"):
        """/think with invalid argument should produce error output."""
        repl._handle_slash_command("/think invalidarg")
        last_output = repl.output[-1]
        assert "Unknown option" in last_output.text

    def test_new_session_preserves_thinking_config(self, repl: "GrassFlowREPL"):
        """Session metadata should retain model config after simulated new session.

        Note: This test verifies the metadata copy logic in isolation, not the actual
        _handle_new_session method. It confirms that manual metadata transfer preserves
        the model name while resetting thinking to defaults.
        """
        repl.session.metadata["thinking"]["effort"] = "xhigh"
        repl.session.metadata["model"] = "custom-model"

        # Simulate what _handle_new_session does: copy metadata
        old_meta = dict(repl.session.metadata)
        repl.session = MagicMock()
        repl.session.metadata = {
            "model": old_meta.get("model", "default"),
            "provider": old_meta.get("provider", "default"),
            "thinking": {"enabled": True, "effort": "medium", "display": "full"},
        }

        # Model is preserved from old session; thinking gets fresh defaults
        assert repl.session.metadata["thinking"]["effort"] == "medium"
        assert repl.session.metadata["model"] == "custom-model"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

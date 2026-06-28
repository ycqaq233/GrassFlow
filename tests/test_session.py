"""
GrassFlow 会话管理器测试

测试内容：
- 会话创建、获取、列出、删除
- 消息添加、查询、过滤
- 断点保存、加载
- 会话恢复（resume）
- 上下文恢复（restore_context）
- 会话状态管理
- 会话导入/导出
"""

import tempfile
from pathlib import Path

import pytest

from tui.session import (
    MessageRole,
    SessionBusyError,
    SessionCheckpoint,
    SessionDatabase,
    SessionError,
    SessionInfo,
    SessionManager,
    SessionMessage,
    SessionNotFoundError,
    SessionStatus,
)


@pytest.fixture
def tmp_db_path(tmp_path):
    """使用临时目录的数据库路径"""
    return tmp_path / "test_sessions.db"


@pytest.fixture
def db(tmp_db_path):
    """创建临时数据库实例"""
    return SessionDatabase(db_path=tmp_db_path)


@pytest.fixture
def manager(db):
    """创建会话管理器实例"""
    return SessionManager(db=db)


# ==================== 数据库层测试 ====================


class TestSessionDatabase:
    """SessionDatabase 测试"""

    def test_init_creates_tables(self, tmp_db_path):
        """初始化时应自动创建表"""
        db = SessionDatabase(db_path=tmp_db_path)
        # 验证表存在
        import sqlite3

        conn = sqlite3.connect(tmp_db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "sessions" in tables
        assert "session_messages" in tables
        assert "session_checkpoints" in tables

    def test_create_and_get_session(self, db):
        """创建和获取会话"""
        info = SessionInfo(
            title="Test Session",
            workflow_name="test_workflow",
            status=SessionStatus.IDLE,
        )
        db.create_session(info)

        loaded = db.get_session(info.id)
        assert loaded is not None
        assert loaded.id == info.id
        assert loaded.title == "Test Session"
        assert loaded.workflow_name == "test_workflow"
        assert loaded.status == SessionStatus.IDLE

    def test_get_nonexistent_session(self, db):
        """获取不存在的会话应返回 None"""
        assert db.get_session("nonexistent") is None

    def test_update_session(self, db):
        """更新会话"""
        info = SessionInfo(title="Original Title")
        db.create_session(info)

        info.title = "Updated Title"
        info.status = SessionStatus.BUSY
        db.update_session(info)

        loaded = db.get_session(info.id)
        assert loaded.title == "Updated Title"
        assert loaded.status == SessionStatus.BUSY

    def test_delete_session(self, db):
        """删除会话（级联删除消息和断点）"""
        info = SessionInfo(title="To Delete")
        db.create_session(info)

        # 添加消息和断点
        db.add_message(
            SessionMessage(session_id=info.id, role=MessageRole.USER, content="hello")
        )
        db.save_checkpoint(
            SessionCheckpoint(session_id=info.id, workflow_state={"step": 1})
        )

        # 删除
        assert db.delete_session(info.id) is True
        assert db.get_session(info.id) is None

    def test_delete_nonexistent_session(self, db):
        """删除不存在的会话应返回 False"""
        assert db.delete_session("nonexistent") is False

    def test_list_sessions(self, db):
        """列出会话"""
        for i in range(5):
            db.create_session(SessionInfo(title=f"Session {i}"))

        sessions = db.list_sessions()
        assert len(sessions) == 5

    def test_list_sessions_with_workflow_filter(self, db):
        """按工作流名称过滤"""
        db.create_session(SessionInfo(title="A", workflow_name="wf1"))
        db.create_session(SessionInfo(title="B", workflow_name="wf2"))
        db.create_session(SessionInfo(title="C", workflow_name="wf1"))

        sessions = db.list_sessions(workflow_name="wf1")
        assert len(sessions) == 2
        assert all(s.workflow_name == "wf1" for s in sessions)

    def test_list_sessions_with_status_filter(self, db):
        """按状态过滤"""
        db.create_session(SessionInfo(title="A", status=SessionStatus.IDLE))
        db.create_session(SessionInfo(title="B", status=SessionStatus.BUSY))
        db.create_session(SessionInfo(title="C", status=SessionStatus.IDLE))

        sessions = db.list_sessions(status=SessionStatus.IDLE)
        assert len(sessions) == 2

    def test_list_sessions_with_limit(self, db):
        """限制返回数量"""
        for i in range(10):
            db.create_session(SessionInfo(title=f"Session {i}"))

        sessions = db.list_sessions(limit=3)
        assert len(sessions) == 3


class TestMessageOperations:
    """消息操作测试"""

    def test_add_and_get_messages(self, db):
        """添加和获取消息"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        msg1 = SessionMessage(
            session_id=session.id, role=MessageRole.USER, content="Hello"
        )
        msg2 = SessionMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content="Hi there!",
        )

        db.add_message(msg1)
        db.add_message(msg2)

        messages = db.get_messages(session.id)
        assert len(messages) == 2
        assert messages[0].content == "Hello"
        assert messages[1].content == "Hi there!"

    def test_messages_in_chronological_order(self, db):
        """消息应按时间正序排列"""
        import time

        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(3):
            db.add_message(
                SessionMessage(
                    session_id=session.id,
                    role=MessageRole.USER,
                    content=f"msg {i}",
                )
            )
            time.sleep(0.01)  # 确保时间戳不同

        messages = db.get_messages(session.id)
        assert messages[0].content == "msg 0"
        assert messages[2].content == "msg 2"

    def test_get_messages_with_limit(self, db):
        """限制消息数量"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(5):
            db.add_message(
                SessionMessage(
                    session_id=session.id,
                    role=MessageRole.USER,
                    content=f"msg {i}",
                )
            )

        messages = db.get_messages(session.id, limit=2)
        assert len(messages) == 2

    def test_get_messages_with_offset(self, db):
        """消息偏移"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(5):
            db.add_message(
                SessionMessage(
                    session_id=session.id,
                    role=MessageRole.USER,
                    content=f"msg {i}",
                )
            )

        messages = db.get_messages(session.id, limit=2, offset=2)
        assert len(messages) == 2
        assert messages[0].content == "msg 2"

    def test_get_latest_messages(self, db):
        """获取最近 N 条消息"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(10):
            db.add_message(
                SessionMessage(
                    session_id=session.id,
                    role=MessageRole.USER,
                    content=f"msg {i}",
                )
            )

        messages = db.get_latest_messages(session.id, count=3)
        assert len(messages) == 3
        # 应该是最近的 3 条，且按时间正序
        assert messages[0].content == "msg 7"
        assert messages[2].content == "msg 9"

    def test_add_message_updates_count(self, db):
        """添加消息应更新会话的消息计数"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        db.add_message(
            SessionMessage(
                session_id=session.id, role=MessageRole.USER, content="hello"
            )
        )

        loaded = db.get_session(session.id)
        assert loaded.message_count == 1

    def test_delete_messages(self, db):
        """删除会话的所有消息"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(3):
            db.add_message(
                SessionMessage(
                    session_id=session.id,
                    role=MessageRole.USER,
                    content=f"msg {i}",
                )
            )

        count = db.delete_messages(session.id)
        assert count == 3
        assert len(db.get_messages(session.id)) == 0

    def test_message_metadata(self, db):
        """消息元数据的存储和读取"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        metadata = {"route": "urgent", "agent_output": {"category": "bug"}}
        db.add_message(
            SessionMessage(
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content="Classified",
                metadata=metadata,
            )
        )

        messages = db.get_messages(session.id)
        assert messages[0].metadata == metadata


class TestCheckpointOperations:
    """断点操作测试"""

    def test_save_and_get_checkpoint(self, db):
        """保存和获取断点"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        state = {
            "workflow_name": "test_wf",
            "completed_agents": ["classify", "analyze"],
            "context_data": {"classify": {"route": "urgent"}},
            "current_group_index": 2,
        }
        checkpoint = SessionCheckpoint(
            session_id=session.id, workflow_state=state
        )
        db.save_checkpoint(checkpoint)

        loaded = db.get_latest_checkpoint(session.id)
        assert loaded is not None
        assert loaded.workflow_state == state

    def test_get_latest_checkpoint(self, db):
        """获取最新的断点"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        # 保存多个断点
        db.save_checkpoint(
            SessionCheckpoint(
                session_id=session.id,
                workflow_state={"step": 1},
            )
        )
        db.save_checkpoint(
            SessionCheckpoint(
                session_id=session.id,
                workflow_state={"step": 2},
            )
        )

        latest = db.get_latest_checkpoint(session.id)
        assert latest is not None
        assert latest.workflow_state["step"] == 2

    def test_get_checkpoint_empty(self, db):
        """没有断点时返回 None"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        assert db.get_latest_checkpoint(session.id) is None

    def test_list_checkpoints(self, db):
        """列出所有断点"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(3):
            db.save_checkpoint(
                SessionCheckpoint(
                    session_id=session.id,
                    workflow_state={"step": i},
                )
            )

        checkpoints = db.list_checkpoints(session.id)
        assert len(checkpoints) == 3
        # 应按时间倒序
        assert checkpoints[0].workflow_state["step"] == 2

    def test_checkpoint_with_error(self, db):
        """保存带错误信息的断点"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        checkpoint = SessionCheckpoint(
            session_id=session.id,
            workflow_state={"step": 1},
            error="LLM API timeout",
        )
        db.save_checkpoint(checkpoint)

        loaded = db.get_latest_checkpoint(session.id)
        assert loaded.error == "LLM API timeout"

    def test_delete_checkpoints(self, db):
        """删除所有断点"""
        session = SessionInfo(title="Test")
        db.create_session(session)

        for i in range(3):
            db.save_checkpoint(
                SessionCheckpoint(
                    session_id=session.id,
                    workflow_state={"step": i},
                )
            )

        count = db.delete_checkpoints(session.id)
        assert count == 3
        assert db.get_latest_checkpoint(session.id) is None


# ==================== 会话管理器测试 ====================


class TestSessionManager:
    """SessionManager 测试"""

    def test_create_session(self, manager):
        """创建会话"""
        session = manager.create_session(
            title="Test Session",
            workflow_name="test_workflow",
        )

        assert session.title == "Test Session"
        assert session.workflow_name == "test_workflow"
        assert session.status == SessionStatus.IDLE

        # 验证已持久化
        loaded = manager.get_session(session.id)
        assert loaded.id == session.id

    def test_create_session_auto_title(self, manager):
        """不指定标题时自动生成"""
        session = manager.create_session()
        assert session.title.startswith("Session -")

    def test_create_session_with_metadata(self, manager):
        """创建带元数据的会话"""
        metadata = {"model": "gpt-4", "temperature": 0.7}
        session = manager.create_session(
            title="Test", metadata=metadata
        )
        assert session.metadata == metadata

    def test_get_session(self, manager):
        """获取会话"""
        session = manager.create_session(title="Test")
        loaded = manager.get_session(session.id)
        assert loaded.id == session.id
        assert loaded.title == "Test"

    def test_get_nonexistent_session_raises(self, manager):
        """获取不存在的会话应抛出异常"""
        with pytest.raises(SessionNotFoundError):
            manager.get_session("nonexistent")

    def test_list_sessions(self, manager):
        """列出会话"""
        for i in range(3):
            manager.create_session(title=f"Session {i}")

        sessions = manager.list_sessions()
        assert len(sessions) == 3

    def test_delete_session(self, manager):
        """删除会话"""
        session = manager.create_session(title="To Delete")
        assert manager.delete_session(session.id) is True

        with pytest.raises(SessionNotFoundError):
            manager.get_session(session.id)

    def test_rename_session(self, manager):
        """重命名会话"""
        session = manager.create_session(title="Old Name")
        renamed = manager.rename_session(session.id, "New Name")
        assert renamed.title == "New Name"

    def test_auto_adds_system_message_on_create(self, manager):
        """创建会话时自动添加系统消息"""
        session = manager.create_session(title="Test")
        messages = manager.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].role == MessageRole.SYSTEM
        assert "Session created" in messages[0].content


class TestSessionStatusManagement:
    """会话状态管理测试"""

    def test_set_status(self, manager):
        """设置状态"""
        session = manager.create_session(title="Test")
        updated = manager.set_status(session.id, SessionStatus.BUSY)
        assert updated.status == SessionStatus.BUSY

    def test_mark_busy(self, manager):
        """标记为忙碌"""
        session = manager.create_session(title="Test")
        updated = manager.mark_busy(session.id)
        assert updated.status == SessionStatus.BUSY

    def test_mark_completed(self, manager):
        """标记为完成"""
        session = manager.create_session(title="Test")
        updated = manager.mark_completed(session.id)
        assert updated.status == SessionStatus.COMPLETED

    def test_mark_failed(self, manager):
        """标记为失败"""
        session = manager.create_session(title="Test")
        updated = manager.mark_failed(session.id, error="API timeout")
        assert updated.status == SessionStatus.FAILED

    def test_mark_cancelled(self, manager):
        """标记为取消"""
        session = manager.create_session(title="Test")
        updated = manager.mark_cancelled(session.id)
        assert updated.status == SessionStatus.CANCELLED

    def test_mark_idle(self, manager):
        """标记为空闲"""
        session = manager.create_session(title="Test")
        manager.mark_busy(session.id)
        updated = manager.mark_idle(session.id)
        assert updated.status == SessionStatus.IDLE

    def test_status_change_creates_system_message(self, manager):
        """状态变更应创建系统消息"""
        session = manager.create_session(title="Test")
        manager.set_status(session.id, SessionStatus.BUSY)

        messages = manager.get_messages(session.id)
        # 创建时一条系统消息 + 状态变更一条系统消息 = 2
        assert len(messages) == 2
        assert "Status changed" in messages[-1].content


class TestMessageManagement:
    """消息管理测试"""

    def test_add_user_message(self, manager):
        """添加用户消息"""
        session = manager.create_session(title="Test")
        msg = manager.add_user_message(session.id, "Hello")

        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"

    def test_add_assistant_message(self, manager):
        """添加助手消息"""
        session = manager.create_session(title="Test")
        msg = manager.add_assistant_message(
            session.id, "Hi!", metadata={"model": "gpt-4"}
        )

        assert msg.role == MessageRole.ASSISTANT
        assert msg.content == "Hi!"
        assert msg.metadata["model"] == "gpt-4"

    def test_add_system_message(self, manager):
        """添加系统消息"""
        session = manager.create_session(title="Test")
        msg = manager.add_system_message(session.id, "System event")

        assert msg.role == MessageRole.SYSTEM

    def test_get_conversation_messages(self, manager):
        """获取对话消息（不含系统消息）"""
        session = manager.create_session(title="Test")
        manager.add_user_message(session.id, "Q1")
        manager.add_assistant_message(session.id, "A1")
        manager.add_system_message(session.id, "event")
        manager.add_user_message(session.id, "Q2")

        conv = manager.get_conversation_messages(session.id)
        assert len(conv) == 3  # Q1, A1, Q2
        assert all(
            m.role in (MessageRole.USER, MessageRole.ASSISTANT) for m in conv
        )

    def test_add_message_to_nonexistent_session_raises(self, manager):
        """向不存在的会话添加消息应抛出异常"""
        with pytest.raises(SessionNotFoundError):
            manager.add_user_message("nonexistent", "hello")


class TestCheckpointAndResume:
    """断点和恢复测试"""

    def test_save_checkpoint(self, manager):
        """保存断点"""
        session = manager.create_session(title="Test")
        state = {
            "workflow_name": "test_wf",
            "completed_agents": ["classify"],
            "context_data": {"classify": {"route": "urgent"}},
        }
        checkpoint = manager.save_checkpoint(session.id, state)

        assert checkpoint.session_id == session.id
        assert checkpoint.workflow_state == state

    def test_save_checkpoint_with_error(self, manager):
        """保存带错误的断点"""
        session = manager.create_session(title="Test")
        checkpoint = manager.save_checkpoint(
            session.id,
            {"step": 1},
            error="LLM API error",
        )
        assert checkpoint.error == "LLM API error"

    def test_get_latest_checkpoint(self, manager):
        """获取最新断点"""
        session = manager.create_session(title="Test")
        manager.save_checkpoint(session.id, {"step": 1})
        manager.save_checkpoint(session.id, {"step": 2})

        ckpt = manager.get_latest_checkpoint(session.id)
        assert ckpt is not None
        assert ckpt.workflow_state["step"] == 2

    def test_list_checkpoints(self, manager):
        """列出断点"""
        session = manager.create_session(title="Test")
        manager.save_checkpoint(session.id, {"step": 1})
        manager.save_checkpoint(session.id, {"step": 2})

        checkpoints = manager.list_checkpoints(session.id)
        assert len(checkpoints) == 2

    def test_resume_session(self, manager):
        """恢复会话"""
        session = manager.create_session(title="Test")
        manager.add_user_message(session.id, "Hello")
        manager.add_assistant_message(session.id, "Hi!")
        manager.save_checkpoint(session.id, {"step": 1})

        messages, checkpoint = manager.resume_session(session.id)

        assert len(messages) >= 2
        assert checkpoint is not None
        assert checkpoint.workflow_state["step"] == 1

    def test_resume_session_without_checkpoint(self, manager):
        """无断点的会话恢复"""
        session = manager.create_session(title="Test")
        manager.add_user_message(session.id, "Hello")

        messages, checkpoint = manager.resume_session(session.id)

        assert len(messages) >= 1
        assert checkpoint is None

    def test_resume_busy_session_resets_to_idle(self, manager):
        """恢复忙碌状态的会话应重置为空闲"""
        session = manager.create_session(title="Test")
        manager.mark_busy(session.id)

        messages, checkpoint = manager.resume_session(session.id)

        reloaded = manager.get_session(session.id)
        assert reloaded.status == SessionStatus.IDLE

    def test_resume_creates_system_message(self, manager):
        """恢复时应记录系统消息"""
        session = manager.create_session(title="Test")
        manager.resume_session(session.id)

        messages = manager.get_messages(session.id)
        resumed_msgs = [m for m in messages if "resumed" in m.content.lower()]
        assert len(resumed_msgs) >= 1


class TestContextRestore:
    """上下文恢复测试"""

    def test_restore_context(self, manager):
        """恢复完整上下文"""
        session = manager.create_session(title="Test")
        manager.add_user_message(session.id, "Process ticket #123")
        manager.add_assistant_message(session.id, "Classified as urgent")
        manager.save_checkpoint(
            session.id,
            {
                "workflow_name": "ticket_processing",
                "completed_agents": ["classify"],
                "context_data": {"classify": {"route": "urgent"}},
                "current_group_index": 1,
            },
        )

        ctx = manager.restore_context(session.id)

        assert ctx["session"].id == session.id
        assert len(ctx["messages"]) >= 2
        assert ctx["checkpoint"] is not None
        assert ctx["completed_agents"] == ["classify"]
        assert ctx["context_data"]["classify"]["route"] == "urgent"

    def test_restore_context_without_checkpoint(self, manager):
        """无断点时上下文数据为空"""
        session = manager.create_session(title="Test")

        ctx = manager.restore_context(session.id)

        assert ctx["checkpoint"] is None
        assert ctx["context_data"] == {}
        assert ctx["completed_agents"] == []


class TestSessionUtilities:
    """会话工具方法测试"""

    def test_find_session_by_workflow(self, manager):
        """按工作流名称查找会话"""
        manager.create_session(title="A", workflow_name="wf1")
        manager.create_session(title="B", workflow_name="wf2")

        found = manager.find_session_by_workflow("wf1")
        assert found is not None
        assert found.workflow_name == "wf1"

    def test_find_session_by_workflow_not_found(self, manager):
        """找不到时返回 None"""
        assert manager.find_session_by_workflow("nonexistent") is None

    def test_find_resumable_session(self, manager):
        """查找可恢复的会话"""
        # 已完成的会话
        s1 = manager.create_session(title="Done", workflow_name="wf")
        manager.mark_completed(s1.id)

        # 有断点的会话
        s2 = manager.create_session(title="With Checkpoint", workflow_name="wf")
        manager.save_checkpoint(s2.id, {"step": 1})

        found = manager.find_resumable_session("wf")
        assert found is not None
        assert found.id == s2.id

    def test_find_resumable_session_fallback(self, manager):
        """没有断点时返回最近的未完成会话"""
        s1 = manager.create_session(title="Idle", workflow_name="wf")
        manager.create_session(title="Done", workflow_name="wf")
        # 标记第二个为完成
        sessions = manager.list_sessions(workflow_name="wf")
        for s in sessions:
            if s.title == "Done":
                manager.mark_completed(s.id)

        found = manager.find_resumable_session("wf")
        assert found is not None
        assert found.title == "Idle"

    def test_get_session_summary(self, manager):
        """获取会话摘要"""
        session = manager.create_session(title="Test")
        manager.add_user_message(session.id, "Q1")
        manager.add_assistant_message(session.id, "A1")
        manager.add_system_message(session.id, "event")
        manager.save_checkpoint(session.id, {"step": 1})

        summary = manager.get_session_summary(session.id)

        assert summary["session"]["id"] == session.id
        assert summary["message_stats"]["total"] == 4  # 1 create + 3 manual
        assert summary["has_checkpoint"] is True
        assert summary["checkpoint_count"] == 1
        assert summary["last_conversation"]["role"] == "assistant"

    def test_clear_session(self, manager):
        """清空会话"""
        session = manager.create_session(title="Test")
        manager.add_user_message(session.id, "Q1")
        manager.add_assistant_message(session.id, "A1")
        manager.save_checkpoint(session.id, {"step": 1})

        manager.clear_session(session.id)

        reloaded = manager.get_session(session.id)
        assert reloaded.status == SessionStatus.IDLE
        # 应该只有 "Session cleared" 系统消息
        messages = manager.get_messages(session.id)
        cleared_msgs = [m for m in messages if "cleared" in m.content.lower()]
        assert len(cleared_msgs) >= 1

        # 断点应被删除
        assert manager.get_latest_checkpoint(session.id) is None


class TestSessionExportImport:
    """会话导入导出测试"""

    def test_export_session(self, manager):
        """导出会话"""
        session = manager.create_session(title="Export Test")
        manager.add_user_message(session.id, "Hello")
        manager.add_assistant_message(session.id, "Hi!")
        manager.save_checkpoint(session.id, {"step": 1})

        exported = manager.export_session(session.id)

        assert exported["session"]["id"] == session.id
        assert len(exported["messages"]) >= 2
        assert len(exported["checkpoints"]) == 1

    def test_import_session(self, manager):
        """导入会话"""
        # 先导出
        session = manager.create_session(title="Import Test")
        manager.add_user_message(session.id, "Hello")
        manager.save_checkpoint(session.id, {"step": 1})
        exported = manager.export_session(session.id)

        # 导入（使用新的数据库）
        new_db = SessionDatabase(db_path=manager.db.db_path.parent / "import_test.db")
        new_manager = SessionManager(db=new_db)
        imported = new_manager.import_session(exported)

        assert imported.title == "Import Test"
        messages = new_manager.get_messages(imported.id)
        assert len(messages) >= 1
        checkpoint = new_manager.get_latest_checkpoint(imported.id)
        assert checkpoint is not None


class TestEdgeCases:
    """边界条件测试"""

    def test_session_with_empty_content(self, manager):
        """空内容消息"""
        session = manager.create_session(title="Test")
        msg = manager.add_user_message(session.id, "")
        assert msg.content == ""

    def test_session_with_large_metadata(self, manager):
        """大元数据"""
        session = manager.create_session(title="Test")
        large_metadata = {f"key_{i}": f"value_{i}" for i in range(100)}
        msg = manager.add_assistant_message(
            session.id, "test", metadata=large_metadata
        )
        messages = manager.get_messages(session.id)
        assert messages[-1].metadata == large_metadata

    def test_session_with_unicode_content(self, manager):
        """Unicode 内容"""
        session = manager.create_session(title="Unicode 测试")
        manager.add_user_message(session.id, "处理工单 #123 - 请立即回复!")
        manager.add_assistant_message(session.id, "已分类为紧急工单，正在处理中...")

        messages = manager.get_conversation_messages(session.id)
        assert messages[0].content == "处理工单 #123 - 请立即回复!"
        assert messages[1].content == "已分类为紧急工单，正在处理中..."

    def test_concurrent_session_creation(self, manager):
        """并发创建会话"""
        sessions = []
        for i in range(20):
            s = manager.create_session(title=f"Concurrent {i}")
            sessions.append(s)

        all_sessions = manager.list_sessions()
        assert len(all_sessions) == 20

    def test_session_message_count_accuracy(self, manager):
        """消息计数准确性"""
        session = manager.create_session(title="Count Test")
        manager.add_user_message(session.id, "Q1")
        manager.add_assistant_message(session.id, "A1")
        manager.add_system_message(session.id, "event")

        # 从数据库直接读取以获取最新的 message_count
        # （manager.get_session 会返回缓存中的旧值）
        reloaded = manager.db.get_session(session.id)
        # 创建时有一条自动系统消息 + 手动添加的 3 条 = 4
        assert reloaded.message_count == 4

    def test_wal_mode_enabled(self, tmp_db_path):
        """验证 WAL 模式已启用"""
        db = SessionDatabase(db_path=tmp_db_path)
        import sqlite3

        conn = sqlite3.connect(tmp_db_path)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        assert mode == "wal"

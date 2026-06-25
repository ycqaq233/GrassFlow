"""
GrassFlow REPL 会话管理器

参考 opencode 的会话管理设计，为 GrassFlow REPL 提供：
- 会话创建、恢复、持久化
- SQLite 存储会话历史和消息
- 断点恢复（Checkpoint / Resume）
- 会话状态管理（idle / busy / completed / failed / cancelled）

设计要点：
- 复用 core/db.py 的 SQLite 连接模式和数据库路径
- 使用 Pydantic 数据模型，与 core/models.py 风格一致
- 每条消息支持 metadata（存储工作流状态、Agent 输出等）
"""

import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ==================== 数据模型 ====================


class SessionStatus(str, Enum):
    """会话状态"""
    IDLE = "idle"              # 空闲，未在执行
    BUSY = "busy"              # 正在执行工作流
    COMPLETED = "completed"    # 执行完成
    FAILED = "failed"          # 执行失败
    CANCELLED = "cancelled"    # 用户取消


class MessageRole(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SessionMessage(BaseModel):
    """会话中的单条消息"""

    model_config = ConfigDict()

    id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    session_id: str
    role: MessageRole
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class SessionInfo(BaseModel):
    """会话元信息"""

    model_config = ConfigDict()

    id: str = Field(default_factory=lambda: f"ses_{uuid.uuid4().hex[:12]}")
    title: str = ""
    workflow_name: Optional[str] = None
    status: SessionStatus = SessionStatus.IDLE
    directory: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class SessionCheckpoint(BaseModel):
    """会话断点，用于恢复执行"""

    model_config = ConfigDict()

    id: str = Field(default_factory=lambda: f"ckpt_{uuid.uuid4().hex[:12]}")
    session_id: str
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
    # workflow_state 示例:
    # {
    #     "workflow_name": "...",
    #     "completed_agents": ["agent_a", "agent_b"],
    #     "context_data": {"agent_a": {...}, "agent_b": {...}},
    #     "current_group_index": 2,
    #     "agent_configs": [...],
    #     "dsl_source": "...",
    # }
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


# ==================== 异常类 ====================


class SessionError(Exception):
    """会话管理相关错误"""
    pass


class SessionNotFoundError(SessionError):
    """会话不存在"""
    pass


class SessionBusyError(SessionError):
    """会话正在执行中，无法操作"""
    pass


# ==================== 数据库层 ====================


class SessionDatabase:
    """
    会话数据库

    使用 SQLite 持久化会话、消息和断点。
    复用 core/db.py 的数据库路径和连接模式。
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化会话数据库

        Args:
            db_path: 数据库文件路径，默认与 core/db.py 共用 ~/.Grass/grassflow.db
        """
        if db_path is None:
            from core.config import config_manager
            db_path = Path(
                config_manager.get("db_path", "~/.Grass/grassflow.db")
            ).expanduser()

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_tables(self) -> None:
        """创建会话相关表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    workflow_name TEXT,
                    status TEXT NOT NULL DEFAULT 'idle',
                    directory TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    message_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_checkpoints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workflow_state TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """)

            # 为消息查询创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON session_messages(session_id, created_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                ON session_checkpoints(session_id, created_at)
            """)

            conn.commit()

    # ---------- Session CRUD ----------

    def create_session(self, info: SessionInfo) -> SessionInfo:
        """创建新会话"""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, title, workflow_name, status, directory,
                                      metadata, message_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    info.id,
                    info.title,
                    info.workflow_name,
                    info.status.value,
                    info.directory,
                    json.dumps(info.metadata, ensure_ascii=False),
                    info.message_count,
                    info.created_at.isoformat() if info.created_at else now,
                    info.updated_at.isoformat() if info.updated_at else now,
                ),
            )
            conn.commit()
        return info

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """根据 ID 获取会话"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, title, workflow_name, status, directory,
                       metadata, message_count, created_at, updated_at
                FROM sessions WHERE id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return SessionInfo(
            id=row[0],
            title=row[1],
            workflow_name=row[2],
            status=SessionStatus(row[3]),
            directory=row[4],
            metadata=json.loads(row[5]) if row[5] else {},
            message_count=row[6],
            created_at=datetime.fromisoformat(row[7]),
            updated_at=datetime.fromisoformat(row[8]),
        )

    def update_session(self, info: SessionInfo) -> None:
        """更新会话信息"""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET title = ?, workflow_name = ?, status = ?, directory = ?,
                    metadata = ?, message_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    info.title,
                    info.workflow_name,
                    info.status.value,
                    info.directory,
                    json.dumps(info.metadata, ensure_ascii=False),
                    info.message_count,
                    datetime.now().isoformat(),
                    info.id,
                ),
            )
            conn.commit()

    def delete_session(self, session_id: str) -> bool:
        """删除会话（级联删除消息和断点）"""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_sessions(
        self,
        workflow_name: Optional[str] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
    ) -> List[SessionInfo]:
        """列出会话"""
        conditions = []
        params: list = []

        if workflow_name:
            conditions.append("workflow_name = ?")
            params.append(workflow_name)
        if status:
            conditions.append("status = ?")
            params.append(status.value)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT id, title, workflow_name, status, directory,
                       metadata, message_count, created_at, updated_at
                FROM sessions
                {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = cursor.fetchall()

        return [
            SessionInfo(
                id=row[0],
                title=row[1],
                workflow_name=row[2],
                status=SessionStatus(row[3]),
                directory=row[4],
                metadata=json.loads(row[5]) if row[5] else {},
                message_count=row[6],
                created_at=datetime.fromisoformat(row[7]),
                updated_at=datetime.fromisoformat(row[8]),
            )
            for row in rows
        ]

    # ---------- Message CRUD ----------

    def add_message(self, message: SessionMessage) -> SessionMessage:
        """添加消息"""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_messages (id, session_id, role, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.session_id,
                    message.role.value,
                    message.content,
                    json.dumps(message.metadata, ensure_ascii=False),
                    message.created_at.isoformat(),
                ),
            )
            # 更新会话的消息计数和更新时间
            conn.execute(
                """
                UPDATE sessions
                SET message_count = message_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), message.session_id),
            )
            conn.commit()
        return message

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[SessionMessage]:
        """获取会话消息（按时间正序）"""
        query = """
            SELECT id, session_id, role, content, metadata, created_at
            FROM session_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
        """
        params: list = [session_id]

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            SessionMessage(
                id=row[0],
                session_id=row[1],
                role=MessageRole(row[2]),
                content=row[3],
                metadata=json.loads(row[4]) if row[4] else {},
                created_at=datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]

    def get_latest_messages(
        self, session_id: str, count: int = 20
    ) -> List[SessionMessage]:
        """获取最近 N 条消息（用于 REPL 上下文恢复）"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, role, content, metadata, created_at
                FROM session_messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, count),
            )
            rows = cursor.fetchall()

        # 反转为时间正序
        rows.reverse()

        return [
            SessionMessage(
                id=row[0],
                session_id=row[1],
                role=MessageRole(row[2]),
                content=row[3],
                metadata=json.loads(row[4]) if row[4] else {},
                created_at=datetime.fromisoformat(row[5]),
            )
            for row in rows
        ]

    def delete_messages(self, session_id: str) -> int:
        """删除会话的所有消息"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount

    # ---------- Checkpoint CRUD ----------

    def save_checkpoint(self, checkpoint: SessionCheckpoint) -> SessionCheckpoint:
        """保存断点"""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_checkpoints (id, session_id, workflow_state, error, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.id,
                    checkpoint.session_id,
                    json.dumps(checkpoint.workflow_state, ensure_ascii=False),
                    checkpoint.error,
                    checkpoint.created_at.isoformat(),
                ),
            )
            conn.commit()
        return checkpoint

    def get_latest_checkpoint(
        self, session_id: str
    ) -> Optional[SessionCheckpoint]:
        """获取最新的断点"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, workflow_state, error, created_at
                FROM session_checkpoints
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return SessionCheckpoint(
            id=row[0],
            session_id=row[1],
            workflow_state=json.loads(row[2]) if row[2] else {},
            error=row[3],
            created_at=datetime.fromisoformat(row[4]),
        )

    def list_checkpoints(self, session_id: str) -> List[SessionCheckpoint]:
        """列出会话的所有断点"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, workflow_state, error, created_at
                FROM session_checkpoints
                WHERE session_id = ?
                ORDER BY created_at DESC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()

        return [
            SessionCheckpoint(
                id=row[0],
                session_id=row[1],
                workflow_state=json.loads(row[2]) if row[2] else {},
                error=row[3],
                created_at=datetime.fromisoformat(row[4]),
            )
            for row in rows
        ]

    def delete_checkpoints(self, session_id: str) -> int:
        """删除会话的所有断点"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM session_checkpoints WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount


# ==================== 会话管理器 ====================


class SessionManager:
    """
    REPL 会话管理器

    提供会话的完整生命周期管理：
    - 创建 / 恢复 / 列出 / 删除会话
    - 添加 / 查询消息历史
    - 保存 / 加载断点（用于中断恢复）

    使用方式::

        manager = SessionManager()

        # 创建会话
        session = manager.create_session("ticket processing")

        # 添加消息
        manager.add_user_message(session.id, "处理工单 #123")
        manager.add_assistant_message(session.id, "已分类为紧急工单", metadata={"route": "urgent"})

        # 保存断点
        manager.save_checkpoint(session.id, {
            "workflow_name": "ticket_processing",
            "completed_agents": ["classify"],
            "context_data": {"classify": {"route": "urgent"}},
        })

        # 恢复会话
        messages, checkpoint = manager.resume_session(session.id)
    """

    def __init__(self, db: Optional[SessionDatabase] = None):
        """
        初始化会话管理器

        Args:
            db: 会话数据库实例，不传则使用默认路径
        """
        self._db = db or SessionDatabase()
        self._active_sessions: Dict[str, SessionInfo] = {}

    @property
    def db(self) -> SessionDatabase:
        """获取底层数据库实例"""
        return self._db

    # ==================== 会话生命周期 ====================

    def create_session(
        self,
        title: str = "",
        workflow_name: Optional[str] = None,
        directory: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionInfo:
        """
        创建新会话

        Args:
            title: 会话标题，默认自动生成
            workflow_name: 关联的工作流名称
            directory: 工作目录
            metadata: 自定义元数据

        Returns:
            创建的会话信息
        """
        now = datetime.now()
        if not title:
            title = f"Session - {now.strftime('%Y-%m-%d %H:%M:%S')}"

        session = SessionInfo(
            title=title,
            workflow_name=workflow_name,
            status=SessionStatus.IDLE,
            directory=directory,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

        self._db.create_session(session)
        self._active_sessions[session.id] = session

        # 自动添加系统消息记录会话创建
        self._db.add_message(
            SessionMessage(
                session_id=session.id,
                role=MessageRole.SYSTEM,
                content=f"Session created: {title}",
                metadata={"event": "session_created", "workflow": workflow_name},
            )
        )

        return session

    def get_session(self, session_id: str) -> SessionInfo:
        """
        获取会话信息

        Args:
            session_id: 会话 ID

        Returns:
            会话信息

        Raises:
            SessionNotFoundError: 会话不存在
        """
        # 先查缓存
        if session_id in self._active_sessions:
            session = self._db.get_session(session_id)
            if session:
                self._active_sessions[session_id] = session
                return session
            else:
                del self._active_sessions[session_id]

        session = self._db.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session '{session_id}' not found")

        self._active_sessions[session_id] = session
        return session

    def list_sessions(
        self,
        workflow_name: Optional[str] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
    ) -> List[SessionInfo]:
        """
        列出会话

        Args:
            workflow_name: 按工作流名称过滤
            status: 按状态过滤
            limit: 返回数量限制

        Returns:
            会话信息列表
        """
        return self._db.list_sessions(
            workflow_name=workflow_name,
            status=status,
            limit=limit,
        )

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功删除
        """
        self._active_sessions.pop(session_id, None)
        return self._db.delete_session(session_id)

    def rename_session(self, session_id: str, new_title: str) -> SessionInfo:
        """
        重命名会话

        Args:
            session_id: 会话 ID
            new_title: 新标题

        Returns:
            更新后的会话信息
        """
        session = self.get_session(session_id)
        session.title = new_title
        session.updated_at = datetime.now()
        self._db.update_session(session)
        return session

    # ==================== 会话状态管理 ====================

    def set_status(self, session_id: str, status: SessionStatus) -> SessionInfo:
        """
        设置会话状态

        Args:
            session_id: 会话 ID
            status: 新状态

        Returns:
            更新后的会话信息
        """
        session = self.get_session(session_id)
        old_status = session.status
        session.status = status
        session.updated_at = datetime.now()
        self._db.update_session(session)

        # 记录状态变更消息
        self._db.add_message(
            SessionMessage(
                session_id=session_id,
                role=MessageRole.SYSTEM,
                content=f"Status changed: {old_status.value} -> {status.value}",
                metadata={
                    "event": "status_changed",
                    "old_status": old_status.value,
                    "new_status": status.value,
                },
            )
        )

        return session

    def mark_busy(self, session_id: str) -> SessionInfo:
        """标记会话为执行中"""
        return self.set_status(session_id, SessionStatus.BUSY)

    def mark_completed(self, session_id: str) -> SessionInfo:
        """标记会话为已完成"""
        return self.set_status(session_id, SessionStatus.COMPLETED)

    def mark_failed(self, session_id: str, error: str = "") -> SessionInfo:
        """标记会话为失败"""
        session = self.set_status(session_id, SessionStatus.FAILED)
        if error:
            self._db.add_message(
                SessionMessage(
                    session_id=session_id,
                    role=MessageRole.SYSTEM,
                    content=f"Session failed: {error}",
                    metadata={"event": "session_failed", "error": error},
                )
            )
        return session

    def mark_cancelled(self, session_id: str) -> SessionInfo:
        """标记会话为已取消"""
        return self.set_status(session_id, SessionStatus.CANCELLED)

    def mark_idle(self, session_id: str) -> SessionInfo:
        """标记会话为空闲"""
        return self.set_status(session_id, SessionStatus.IDLE)

    # ==================== 消息管理 ====================

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        """
        添加消息

        Args:
            session_id: 会话 ID
            role: 消息角色
            content: 消息内容
            metadata: 元数据

        Returns:
            创建的消息
        """
        # 验证会话存在
        self.get_session(session_id)

        message = SessionMessage(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        return self._db.add_message(message)

    def add_user_message(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        """添加用户消息"""
        return self.add_message(session_id, MessageRole.USER, content, metadata)

    def add_assistant_message(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        """添加助手消息"""
        return self.add_message(session_id, MessageRole.ASSISTANT, content, metadata)

    def add_system_message(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        """添加系统消息"""
        return self.add_message(session_id, MessageRole.SYSTEM, content, metadata)

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[SessionMessage]:
        """
        获取会话消息

        Args:
            session_id: 会话 ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            消息列表（按时间正序）
        """
        return self._db.get_messages(session_id, limit=limit, offset=offset)

    def get_latest_messages(
        self, session_id: str, count: int = 20
    ) -> List[SessionMessage]:
        """获取最近 N 条消息"""
        return self._db.get_latest_messages(session_id, count=count)

    def get_conversation_messages(
        self, session_id: str
    ) -> List[SessionMessage]:
        """
        获取对话消息（仅 user 和 assistant，不含 system）

        用于 LLM 上下文恢复。
        """
        all_messages = self._db.get_messages(session_id)
        return [
            msg
            for msg in all_messages
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ]

    # ==================== 断点管理 ====================

    def save_checkpoint(
        self,
        session_id: str,
        workflow_state: Dict[str, Any],
        error: Optional[str] = None,
    ) -> SessionCheckpoint:
        """
        保存断点

        Args:
            session_id: 会话 ID
            workflow_state: 工作流执行状态快照，应包含：
                - workflow_name: 工作流名称
                - completed_agents: 已完成的 Agent 列表
                - context_data: 已有 Agent 输出数据
                - current_group_index: 当前执行到的并行组索引
                - dsl_source: DSL 源码（可选，用于恢复）
            error: 错误信息（中断/失败时）

        Returns:
            创建的断点
        """
        self.get_session(session_id)

        checkpoint = SessionCheckpoint(
            session_id=session_id,
            workflow_state=workflow_state,
            error=error,
        )
        return self._db.save_checkpoint(checkpoint)

    def get_latest_checkpoint(
        self, session_id: str
    ) -> Optional[SessionCheckpoint]:
        """获取最新的断点"""
        return self._db.get_latest_checkpoint(session_id)

    def list_checkpoints(self, session_id: str) -> List[SessionCheckpoint]:
        """列出所有断点"""
        return self._db.list_checkpoints(session_id)

    # ==================== 恢复（Resume）====================

    def resume_session(
        self, session_id: str
    ) -> tuple[List[SessionMessage], Optional[SessionCheckpoint]]:
        """
        恢复会话

        返回会话的消息历史和最新的断点，供 REPL 重建上下文。

        Args:
            session_id: 会话 ID

        Returns:
            (messages, checkpoint) 元组
            - messages: 完整的消息历史
            - checkpoint: 最新的断点（如果有）

        Raises:
            SessionNotFoundError: 会话不存在
        """
        session = self.get_session(session_id)

        # 获取完整消息历史
        messages = self.get_messages(session_id)

        # 获取最新断点
        checkpoint = self.get_latest_checkpoint(session_id)

        # 记录恢复事件
        self._db.add_message(
            SessionMessage(
                session_id=session_id,
                role=MessageRole.SYSTEM,
                content="Session resumed",
                metadata={
                    "event": "session_resumed",
                    "message_count": len(messages),
                    "has_checkpoint": checkpoint is not None,
                },
            )
        )

        # 如果会话之前是 BUSY 状态，重置为 IDLE
        if session.status == SessionStatus.BUSY:
            session.status = SessionStatus.IDLE
            session.updated_at = datetime.now()
            self._db.update_session(session)

        return messages, checkpoint

    def restore_context(
        self, session_id: str
    ) -> Dict[str, Any]:
        """
        恢复工作流执行上下文

        从断点中重建 WorkflowContext，供调度器继续执行。

        Args:
            session_id: 会话 ID

        Returns:
            包含恢复信息的字典:
            - session: 会话信息
            - messages: 消息历史
            - checkpoint: 最新断点
            - context_data: 已有的 Agent 输出数据
            - completed_agents: 已完成的 Agent 列表
        """
        session = self.get_session(session_id)
        messages = self.get_messages(session_id)
        checkpoint = self.get_latest_checkpoint(session_id)

        context_data = {}
        completed_agents: List[str] = []

        if checkpoint and checkpoint.workflow_state:
            ws = checkpoint.workflow_state
            context_data = ws.get("context_data", {})
            completed_agents = ws.get("completed_agents", [])

        return {
            "session": session,
            "messages": messages,
            "checkpoint": checkpoint,
            "context_data": context_data,
            "completed_agents": completed_agents,
        }

    # ==================== 辅助方法 ====================

    def find_session_by_workflow(
        self, workflow_name: str
    ) -> Optional[SessionInfo]:
        """查找指定工作流的最新会话"""
        sessions = self.list_sessions(
            workflow_name=workflow_name,
            limit=1,
        )
        return sessions[0] if sessions else None

    def find_resumable_session(
        self, workflow_name: str
    ) -> Optional[SessionInfo]:
        """
        查找可恢复的会话

        优先返回有断点的未完成会话，其次返回最近的未完成会话。
        """
        sessions = self.list_sessions(workflow_name=workflow_name)

        # 优先找有断点的会话
        for session in sessions:
            if session.status in (
                SessionStatus.BUSY,
                SessionStatus.IDLE,
                SessionStatus.FAILED,
            ):
                checkpoint = self._db.get_latest_checkpoint(session.id)
                if checkpoint:
                    return session

        # 其次找未完成的会话
        for session in sessions:
            if session.status in (
                SessionStatus.BUSY,
                SessionStatus.IDLE,
                SessionStatus.FAILED,
            ):
                return session

        return None

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """获取会话摘要"""
        session = self.get_session(session_id)
        messages = self.get_messages(session_id)
        checkpoints = self.list_checkpoints(session_id)

        # 统计消息
        user_count = sum(1 for m in messages if m.role == MessageRole.USER)
        assistant_count = sum(
            1 for m in messages if m.role == MessageRole.ASSISTANT
        )
        system_count = sum(1 for m in messages if m.role == MessageRole.SYSTEM)

        # 获取最后一条对话消息
        last_conversation = None
        for msg in reversed(messages):
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT):
                last_conversation = {
                    "role": msg.role.value,
                    "content": msg.content[:200],  # 截断
                    "created_at": msg.created_at.isoformat(),
                }
                break

        return {
            "session": session.model_dump(),
            "message_stats": {
                "total": len(messages),
                "user": user_count,
                "assistant": assistant_count,
                "system": system_count,
            },
            "checkpoint_count": len(checkpoints),
            "has_checkpoint": len(checkpoints) > 0,
            "last_conversation": last_conversation,
        }

    def clear_session(self, session_id: str) -> None:
        """
        清空会话（删除消息和断点，但保留会话本身）

        用于重新开始同一会话。
        """
        self.get_session(session_id)

        self._db.delete_messages(session_id)
        self._db.delete_checkpoints(session_id)

        session = self.get_session(session_id)
        session.status = SessionStatus.IDLE
        session.message_count = 0
        session.updated_at = datetime.now()
        self._db.update_session(session)

        self._db.add_message(
            SessionMessage(
                session_id=session_id,
                role=MessageRole.SYSTEM,
                content="Session cleared",
                metadata={"event": "session_cleared"},
            )
        )

    def export_session(self, session_id: str) -> Dict[str, Any]:
        """
        导出会话为可序列化的字典

        用于备份或迁移。
        """
        session = self.get_session(session_id)
        messages = self.get_messages(session_id)
        checkpoints = self.list_checkpoints(session_id)

        return {
            "session": session.model_dump(mode="json"),
            "messages": [m.model_dump(mode="json") for m in messages],
            "checkpoints": [c.model_dump(mode="json") for c in checkpoints],
        }

    def import_session(self, data: Dict[str, Any]) -> SessionInfo:
        """
        从导出的字典导入会话

        Args:
            data: export_session 导出的字典

        Returns:
            导入的会话信息
        """
        session = SessionInfo(**data["session"])
        self._db.create_session(session)

        for msg_data in data.get("messages", []):
            msg = SessionMessage(**msg_data)
            self._db.add_message(msg)

        for ckpt_data in data.get("checkpoints", []):
            ckpt = SessionCheckpoint(**ckpt_data)
            self._db.save_checkpoint(ckpt)

        return session


# ==================== 全局实例 ====================

session_manager = SessionManager()

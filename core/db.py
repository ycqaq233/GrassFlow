"""
GrassFlow 数据库模块

使用 SQLite 存储执行记录
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from core.models import ExecutionRecord, AgentExecutionRecord, ExecutionStatus


class DatabaseError(Exception):
    """数据库相关错误"""
    pass


class ExecutionDatabase:
    """执行记录数据库"""

    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径，默认为 ~/.Grass/grassflow.db
        """
        if db_path is None:
            # 延迟导入避免循环依赖
            from core.config import config_manager
            db_path = Path(config_manager.get("db_path", "~/.Grass/grassflow.db")).expanduser()

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 创建执行记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    total_duration_ms INTEGER,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建 Agent 执行记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_data TEXT,
                    output_data TEXT,
                    error TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms INTEGER,
                    FOREIGN KEY (execution_id) REFERENCES executions(id)
                )
            """)

            conn.commit()

    def save_execution(self, record: ExecutionRecord) -> int:
        """
        保存执行记录

        Args:
            record: 执行记录

        Returns:
            执行记录 ID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 插入执行记录
            cursor.execute("""
                INSERT INTO executions (workflow_name, status, started_at, completed_at, total_duration_ms, error)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                record.workflow_name,
                record.status.value,
                record.started_at.isoformat() if record.started_at else None,
                record.completed_at.isoformat() if record.completed_at else None,
                record.total_duration_ms,
                record.error,
            ))

            execution_id = cursor.lastrowid

            # 插入 Agent 执行记录
            for agent_name, agent_record in record.agent_records.items():
                cursor.execute("""
                    INSERT INTO agent_executions (execution_id, agent_name, status, input_data, output_data, error, started_at, completed_at, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    execution_id,
                    agent_name,
                    agent_record.status.value,
                    json.dumps(agent_record.input_data, ensure_ascii=False) if agent_record.input_data else None,
                    json.dumps(agent_record.output_data, ensure_ascii=False) if agent_record.output_data else None,
                    agent_record.error,
                    agent_record.started_at.isoformat() if agent_record.started_at else None,
                    agent_record.completed_at.isoformat() if agent_record.completed_at else None,
                    agent_record.duration_ms,
                ))

            conn.commit()

            return execution_id

    def get_execution(self, execution_id: int) -> Optional[ExecutionRecord]:
        """
        获取执行记录

        Args:
            execution_id: 执行记录 ID

        Returns:
            执行记录，如果不存在返回 None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 查询执行记录
            cursor.execute("""
                SELECT workflow_name, status, started_at, completed_at, total_duration_ms, error
                FROM executions
                WHERE id = ?
            """, (execution_id,))

            row = cursor.fetchone()
            if not row:
                return None

            record = ExecutionRecord(
                workflow_name=row[0],
                status=ExecutionStatus(row[1]),
                started_at=datetime.fromisoformat(row[2]) if row[2] else None,
                completed_at=datetime.fromisoformat(row[3]) if row[3] else None,
                total_duration_ms=row[4],
                error=row[5],
            )

            # 查询 Agent 执行记录
            cursor.execute("""
                SELECT agent_name, status, input_data, output_data, error, started_at, completed_at, duration_ms
                FROM agent_executions
                WHERE execution_id = ?
            """, (execution_id,))

            for agent_row in cursor.fetchall():
                agent_record = AgentExecutionRecord(
                    agent_name=agent_row[0],
                    status=ExecutionStatus(agent_row[1]),
                    input_data=json.loads(agent_row[2]) if agent_row[2] else {},
                    output_data=json.loads(agent_row[3]) if agent_row[3] else {},
                    error=agent_row[4],
                    started_at=datetime.fromisoformat(agent_row[5]) if agent_row[5] else None,
                    completed_at=datetime.fromisoformat(agent_row[6]) if agent_row[6] else None,
                    duration_ms=agent_row[7],
                )
                record.agent_records[agent_record.agent_name] = agent_record

            return record

    def list_executions(self, workflow_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        列出执行记录

        Args:
            workflow_name: 工作流名称（可选，用于过滤）
            limit: 返回数量限制

        Returns:
            执行记录摘要列表
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if workflow_name:
                cursor.execute("""
                    SELECT id, workflow_name, status, started_at, completed_at, total_duration_ms
                    FROM executions
                    WHERE workflow_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (workflow_name, limit))
            else:
                cursor.execute("""
                    SELECT id, workflow_name, status, started_at, completed_at, total_duration_ms
                    FROM executions
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "id": row[0],
                    "workflow_name": row[1],
                    "status": row[2],
                    "started_at": row[3],
                    "completed_at": row[4],
                    "total_duration_ms": row[5],
                })

            return results

    def delete_execution(self, execution_id: int) -> None:
        """
        删除执行记录

        Args:
            execution_id: 执行记录 ID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 删除 Agent 执行记录
            cursor.execute("DELETE FROM agent_executions WHERE execution_id = ?", (execution_id,))

            # 删除执行记录
            cursor.execute("DELETE FROM executions WHERE id = ?", (execution_id,))

            conn.commit()


# 全局数据库实例
execution_db = ExecutionDatabase()

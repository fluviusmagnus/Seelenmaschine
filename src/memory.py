import sqlite3
import lancedb
import uuid
import os
import pyarrow as pa
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from config import Config
from llm import LLMClient
from prompts import PromptBuilder
from utils import remove_blockquote_tags

llm_client = LLMClient()
prompt_builder = PromptBuilder()


class MemoryManager:
    def __init__(self):
        os.makedirs(os.path.dirname(Config.SQLITE_DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(Config.SQLITE_DB_PATH)
        self._init_db()
        self.vector_db = lancedb.connect(Config.LANCEDB_PATH)
        self._init_vector_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        # 创建session表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session (
                session_id TEXT PRIMARY KEY,
                start_timestamp DATETIME NOT NULL,
                end_timestamp DATETIME,
                status TEXT CHECK(status IN ('active', 'archived')),
                current_conv_count INTEGER DEFAULT 0
            )
        """
        )
        # 创建summary表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS summary (
                summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                text_id TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES session(session_id)
            )
        """
        )
        # 创建conversation表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation (
                conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                text_id TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES session(session_id)
            )
        """
        )
        self.conn.commit()

    def _init_vector_db(self):
        schema = pa.schema(
            [
                ("text_id", pa.string()),
                ("type", pa.string()),
                ("session_id", pa.string()),
                ("vector", pa.list_(pa.float32(), Config.EMBEDDING_DIMENSION)),
            ]
        )
        if "conversations" not in self.vector_db.table_names():
            self.vector_db.create_table("conversations", schema=schema)
        if "summaries" not in self.vector_db.table_names():
            self.vector_db.create_table("summaries", schema=schema)

    def get_or_create_session(self) -> Tuple[str, datetime, int]:
        cursor = self.conn.cursor()
        # 查找未完成的session
        cursor.execute(
            """
            SELECT session_id FROM session 
            WHERE status = 'active' 
            ORDER BY start_timestamp DESC 
            LIMIT 1
        """
        )
        result = cursor.fetchone()

        if result:
            session_id = result[0]
            # 检查是否有任何对话记录
            cursor.execute(
                "SELECT COUNT(*) FROM conversation WHERE session_id = ?", (session_id,)
            )
            conversation_count = cursor.fetchone()[0]

            if conversation_count == 0:
                # 如果没有对话记录,更新开始时间为现在
                current_time = datetime.now()
                cursor.execute(
                    """
                    UPDATE session 
                    SET start_timestamp = ? 
                    WHERE session_id = ?
                    """,
                    (current_time, session_id),
                )
                self.conn.commit()
                return session_id, current_time, 0
            else:
                cursor.execute(
                    """
                    SELECT session_id, start_timestamp, current_conv_count 
                    FROM session 
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                session_id, start_time, conv_count = cursor.fetchone()
                return session_id, datetime.fromisoformat(start_time), conv_count
        else:
            new_session_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO session (session_id, start_timestamp, status, current_conv_count)
                VALUES (?, ?, ?, ?)
            """,
                (new_session_id, datetime.now(), "active", 0),
            )
            self.conn.commit()
            start_time = datetime.now()
            return new_session_id, start_time, 0

    def add_conversation(self, session_id: str, role: str, text: str) -> None:
        text_id = str(uuid.uuid4())
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversation 
            (session_id, timestamp, role, text, text_id)
            VALUES (?, ?, ?, ?, ?)
        """,
            (session_id, datetime.now(), role, text, text_id),
        )

        # 更新session的current_conv_count
        cursor.execute(
            """
            UPDATE session 
            SET current_conv_count = current_conv_count + 1
            WHERE session_id = ?
            """,
            (session_id,),
        )
        self.conn.commit()

        # 如果是assistant的回复,移除blockquote标签后再生成向量
        text_for_embedding = (
            remove_blockquote_tags(text) if role == "assistant" else text
        )
        # 保存到向量数据库
        embedding = llm_client.get_embedding(text_for_embedding)
        table = self.vector_db.open_table("conversations")
        table.add(
            [
                {
                    "text_id": text_id,
                    "type": "conversation",
                    "session_id": session_id,
                    "vector": embedding,
                }
            ]
        )

    def update_summary(self, session_id: str, summary: str) -> None:
        """更新会话摘要

        如果会话已有摘要,则更新现有记录;
        如果没有摘要,则创建新记录。

        Args:
            session_id: 会话ID
            summary: 新的摘要内容
        """
        cursor = self.conn.cursor()

        # 查找现有摘要
        cursor.execute(
            """
            SELECT summary_id, text_id FROM summary 
            WHERE session_id = ? 
            ORDER BY summary_id DESC 
            LIMIT 1
            """,
            (session_id,),
        )
        result = cursor.fetchone()

        if result:
            # 更新现有摘要
            summary_id, old_text_id = result
            new_text_id = str(uuid.uuid4())
            cursor.execute(
                """
                UPDATE summary 
                SET summary = ?, text_id = ?
                WHERE summary_id = ?
                """,
                (summary, new_text_id, summary_id),
            )

            # 更新向量数据库
            embedding = llm_client.get_embedding(summary)
            table = self.vector_db.open_table("summaries")
            # 删除旧的向量
            table.delete(f"text_id = '{old_text_id}'")
            # 添加新的向量
            table.add(
                [
                    {
                        "text_id": new_text_id,
                        "type": "summary",
                        "session_id": session_id,
                        "vector": embedding,
                    }
                ]
            )
        else:
            # 创建新摘要
            text_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO summary (session_id, summary, text_id)
                VALUES (?, ?, ?)
                """,
                (session_id, summary, text_id),
            )

            # 保存到向量数据库
            embedding = llm_client.get_embedding(summary)
            table = self.vector_db.open_table("summaries")
            table.add(
                [
                    {
                        "text_id": text_id,
                        "type": "summary",
                        "session_id": session_id,
                        "vector": embedding,
                    }
                ]
            )

        self.conn.commit()

    def get_recent_conversations(
        self, session_id: str, limit: int, reverse: bool = False
    ) -> List[Tuple[str, str]]:
        """获取最近的对话记录

        Args:
            session_id: 会话ID
            limit: 获取的对话数量
            reverse: 是否反转顺序。True表示按时间从新到旧排序,False表示从旧到新排序

        Returns:
            对话记录列表,每条记录包含(role, text)
        """
        cursor = self.conn.cursor()
        # 先按时间倒序获取对话
        cursor.execute(
            """
            SELECT role, text FROM conversation 
            WHERE session_id = ? 
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (session_id, limit),
        )
        conversations = cursor.fetchall()

        # 如果需要按时间从旧到新排序,则反转列表
        if not reverse:
            conversations = list(reversed(conversations))

        return conversations

    def search_related_memories(
        self, query: str, current_session_id: str
    ) -> Tuple[List[str], List[str]]:
        query_embedding = llm_client.get_embedding(query)

        # 搜索相关摘要(排除当前会话)
        summary_table = self.vector_db.open_table("summaries")
        summary_results = (
            summary_table.search(query_embedding)
            .where(f"type = 'summary' AND session_id != '{current_session_id}'")
            .limit(Config.RECALL_SESSION_NUM)
            .to_list()
        )

        related_summaries = []
        related_session_ids = []
        if summary_results:
            # 获取摘要和对应session的时间信息
            cursor = self.conn.cursor()
            text_ids = [r["text_id"] for r in summary_results]
            session_ids = [r["session_id"] for r in summary_results]

            # 获取session时间信息
            placeholders = ",".join(["?"] * len(session_ids))
            cursor.execute(
                f"""
                SELECT session_id, start_timestamp, end_timestamp 
                FROM session 
                WHERE session_id IN ({placeholders})
                """,
                session_ids,
            )
            session_times = {sid: (start, end) for sid, start, end in cursor.fetchall()}

            # 获取摘要内容
            summaries = self._get_summary_texts(text_ids)
            related_summaries = []
            related_session_ids = []

            for r, summary in zip(summary_results, summaries):
                sid = r["session_id"]
                start_time, end_time = session_times[sid]
                related_summaries.append(
                    f"[会话时间: {start_time} - {end_time or '进行中'}]\n{summary['summary']}"
                )
                related_session_ids.append(sid)

        # 在相关session中搜索对话
        related_conversations = []
        if related_session_ids:
            conv_table = self.vector_db.open_table("conversations")
            session_filter = " OR ".join(
                [f"session_id = '{sid}'" for sid in related_session_ids]
            )
            conv_results = (
                conv_table.search(query_embedding)
                .where(f"type = 'conversation' AND ({session_filter})")
                .limit(Config.RECALL_CONV_NUM)
                .to_list()
            )

            if conv_results:
                # 获取对话内容和时间戳
                text_ids = [r["text_id"] for r in conv_results]
                placeholders = ",".join(["?"] * len(text_ids))
                cursor.execute(
                    f"""
                    SELECT role, text, timestamp
                    FROM conversation
                    WHERE text_id IN ({placeholders})
                    ORDER BY timestamp
                    """,
                    text_ids,
                )
                conv_data = cursor.fetchall()

                related_conversations = []
                for role, text, timestamp in conv_data:
                    related_conversations.append(f"[{timestamp}] {role}: {text}")

        return related_summaries, related_conversations

    def _get_summary_texts(self, text_ids: List[str]) -> List[Dict]:
        cursor = self.conn.cursor()
        placeholders = ",".join(["?"] * len(text_ids))
        cursor.execute(
            f"""
            SELECT summary FROM summary 
            WHERE text_id IN ({placeholders})
        """,
            text_ids,
        )
        return [{"summary": row[0]} for row in cursor.fetchall()]

    def _get_conversation_texts(self, text_ids: List[str]) -> List[Dict]:
        cursor = self.conn.cursor()
        placeholders = ",".join(["?"] * len(text_ids))
        cursor.execute(
            f"""
            SELECT role, text FROM conversation 
            WHERE text_id IN ({placeholders})
        """,
            text_ids,
        )
        return [{"role": row[0], "text": row[1]} for row in cursor.fetchall()]

    def close_session(self, session_id: str) -> None:
        cursor = self.conn.cursor()

        # 清理assistant回复中的cite标签
        cursor.execute(
            """
            SELECT conversation_id, text 
            FROM conversation 
            WHERE session_id = ? AND role = 'assistant'
            """,
            (session_id,),
        )
        for conv_id, text in cursor.fetchall():
            cleaned_text = remove_blockquote_tags(text)
            cursor.execute(
                """
                UPDATE conversation 
                SET text = ? 
                WHERE conversation_id = ?
                """,
                (cleaned_text, conv_id),
            )

        # 更新session状态
        cursor.execute(
            """
            UPDATE session 
            SET end_timestamp = ?, status = 'archived'
            WHERE session_id = ?
            """,
            (datetime.now(), session_id),
        )
        self.conn.commit()

    def reset_session(self, session_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM conversation WHERE session_id = ?
        """,
            (session_id,),
        )
        cursor.execute(
            """
            DELETE FROM summary WHERE session_id = ?
        """,
            (session_id,),
        )
        cursor.execute(
            """
            UPDATE session 
            SET current_conv_count = 0
            WHERE session_id = ?
        """,
            (session_id,),
        )
        self.conn.commit()

    def get_current_summary(self, session_id: str) -> Optional[str]:
        """获取当前会话的最新摘要"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT summary FROM summary 
            WHERE session_id = ? 
            ORDER BY summary_id DESC 
            LIMIT 1
        """,
            (session_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else None

    def update_persona_memory(self, new_content: str) -> None:
        """更新AI助手的人格记忆"""
        os.makedirs(os.path.dirname(Config.PERSONA_MEMORY_PATH), exist_ok=True)
        with open(Config.PERSONA_MEMORY_PATH, "w", encoding="utf-8") as f:
            f.write(new_content)

    def update_user_profile(self, new_content: str) -> None:
        """更新用户档案"""
        os.makedirs(os.path.dirname(Config.USER_PROFILE_PATH), exist_ok=True)
        with open(Config.USER_PROFILE_PATH, "w", encoding="utf-8") as f:
            f.write(new_content)

    def get_conv_count(self, session_id: str) -> int:
        """获取当前会话的对话计数"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT current_conv_count FROM session 
            WHERE session_id = ?
            """,
            (session_id,),
        )
        result = cursor.fetchone()
        return result[0] if result else 0

    def update_conv_count(self, session_id: str, delta: int) -> int:
        """更新当前会话的对话计数

        Args:
            session_id: 会话ID
            delta: 计数的变化值,可以是正数或负数

        Returns:
            更新后的对话计数
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE session 
            SET current_conv_count = current_conv_count + ?
            WHERE session_id = ?
            """,
            (delta, session_id),
        )
        self.conn.commit()
        return self.get_conv_count(session_id)

    def clean_vector_db(self) -> None:
        """清理向量数据库中的孤立数据"""
        # 获取所有有效的text_id
        cursor = self.conn.cursor()
        cursor.execute("SELECT text_id FROM conversation")
        valid_conv_ids = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT text_id FROM summary")
        valid_summary_ids = {row[0] for row in cursor.fetchall()}

        # 清理对话向量表
        conv_table = self.vector_db.open_table("conversations")
        conv_data = conv_table.to_pandas()
        invalid_conv_ids = conv_data[~conv_data["text_id"].isin(valid_conv_ids)][
            "text_id"
        ].tolist()
        if invalid_conv_ids:
            delete_condition = " OR ".join(
                [f"text_id = '{text_id}'" for text_id in invalid_conv_ids]
            )
            conv_table.delete(delete_condition)

        # 清理摘要向量表
        summary_table = self.vector_db.open_table("summaries")
        summary_data = summary_table.to_pandas()
        invalid_summary_ids = summary_data[
            ~summary_data["text_id"].isin(valid_summary_ids)
        ]["text_id"].tolist()
        if invalid_summary_ids:
            delete_condition = " OR ".join(
                [f"text_id = '{text_id}'" for text_id in invalid_summary_ids]
            )
            summary_table.delete(delete_condition)

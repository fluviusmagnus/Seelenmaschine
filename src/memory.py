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
import utils
import logging
import threading
from collections import OrderedDict
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor

llm_client = LLMClient()
prompt_builder = PromptBuilder()


class LRUCache:
    """LRU缓存实现，用于embedding缓存"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache = OrderedDict()
        self.lock = threading.RLock()

    def get(self, key: str) -> Optional[List[float]]:
        with self.lock:
            if key in self.cache:
                # 移动到末尾（最近使用）
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def put(self, key: str, value: List[float]) -> None:
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.max_size:
                    # 删除最久未使用的项
                    self.cache.popitem(last=False)
                self.cache[key] = value

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()

    def size(self) -> int:
        with self.lock:
            return len(self.cache)


class DatabaseConnectionPool:
    """SQLite连接池"""

    def __init__(self, db_path: str, max_connections: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self.connections = []
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_connections)

    def get_connection(self):
        with self.lock:
            if self.connections:
                return self.connections.pop()
            else:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")  # 启用WAL模式提升并发性能
                conn.execute("PRAGMA synchronous=NORMAL")  # 平衡安全性和性能
                conn.execute("PRAGMA cache_size=10000")  # 增加缓存大小
                conn.execute("PRAGMA temp_store=MEMORY")  # 临时表存储在内存中
                return conn

    def return_connection(self, conn):
        with self.lock:
            if len(self.connections) < self.max_connections:
                self.connections.append(conn)
            else:
                conn.close()

    def close_all(self):
        with self.lock:
            for conn in self.connections:
                conn.close()
            self.connections.clear()


class MemoryManager:
    def __init__(self):
        os.makedirs(os.path.dirname(Config.SQLITE_DB_PATH), exist_ok=True)
        self.db_pool = DatabaseConnectionPool(
            str(Config.SQLITE_DB_PATH), max_connections=Config.DB_CONNECTION_POOL_SIZE
        )
        self._init_db()
        self.vector_db = lancedb.connect(Config.LANCEDB_PATH)
        self._init_vector_db()
        # 使用LRU缓存替代简单字典
        self.embedding_cache = LRUCache(max_size=Config.EMBEDDING_CACHE_SIZE)

    def _get_db(self):
        """获取线程安全的数据库连接"""
        return self.db_pool.get_connection()

    def _return_db(self, conn):
        """归还数据库连接到连接池"""
        self.db_pool.return_connection(conn)

    def _init_db(self):
        conn = sqlite3.connect(Config.SQLITE_DB_PATH)
        cursor = conn.cursor()
        # 使用INTEGER存储UNIX时间戳
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session (
                session_id TEXT PRIMARY KEY,
                start_timestamp INTEGER NOT NULL,
                end_timestamp INTEGER,
                status TEXT CHECK(status IN ('active', 'archived')),
                current_conv_count INTEGER DEFAULT 0
            )
        """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation (
                conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                text_id TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES session(session_id)
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

        # 创建性能优化索引
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_status_timestamp ON session(status, start_timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_session_timestamp ON conversation(session_id, timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_text_id ON conversation(text_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_session_id ON summary(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_text_id ON summary(text_id)"
        )

        conn.commit()
        conn.close()

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

    def _get_embedding_with_cache(self, text: str) -> List[float]:
        """使用缓存获取文本的embedding向量"""
        # 生成缓存键（使用文本的hash以节省内存）
        cache_key = hashlib.md5(text.encode("utf-8")).hexdigest()

        cached_embedding = self.embedding_cache.get(cache_key)
        if cached_embedding is not None:
            return cached_embedding

        embedding = llm_client.get_embedding(text)
        self.embedding_cache.put(cache_key, embedding)
        return embedding

    def get_or_create_session(self) -> Tuple[str, datetime, int]:
        conn = self._get_db()
        try:
            cursor = conn.cursor()
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
                    "SELECT COUNT(*) FROM conversation WHERE session_id = ?",
                    (session_id,),
                )
                conversation_count = cursor.fetchone()[0]

                if conversation_count == 0:
                    # 如果没有对话记录,更新开始时间为现在
                    current_time = utils.now_tz()
                    cursor.execute(
                        """
                        UPDATE session 
                        SET start_timestamp = ? 
                        WHERE session_id = ?
                        """,
                        (utils.datetime_to_timestamp(current_time), session_id),
                    )
                    conn.commit()
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
                    return (
                        session_id,
                        utils.timestamp_to_datetime(start_time),
                        conv_count,
                    )
            else:
                new_session_id = str(uuid.uuid4())
                current_time = utils.now_tz()
                cursor.execute(
                    """
                    INSERT INTO session (session_id, start_timestamp, status, current_conv_count)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        new_session_id,
                        utils.datetime_to_timestamp(current_time),
                        "active",
                        0,
                    ),
                )
                conn.commit()
                start_time = utils.now_tz()
                return new_session_id, start_time, 0
        finally:
            self._return_db(conn)

    def add_conversation(self, session_id: str, role: str, text: str) -> None:
        text_id = str(uuid.uuid4())
        current_time = utils.now_tz()
        conn = self._get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversation 
                (session_id, timestamp, role, text, text_id)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    session_id,
                    utils.datetime_to_timestamp(current_time),
                    role,
                    text,
                    text_id,
                ),
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
            conn.commit()
        finally:
            self._return_db(conn)

        # 如果是assistant的回复,移除blockquote标签后再生成向量
        text_for_embedding = (
            utils.remove_blockquote_tags(text) if role == "assistant" else text
        )
        # 保存到向量数据库
        embedding = self._get_embedding_with_cache(text_for_embedding)
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
        conn = self._get_db()
        try:
            cursor = conn.cursor()

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
                embedding = self._get_embedding_with_cache(summary)
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
                embedding = self._get_embedding_with_cache(summary)
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

            conn.commit()
        finally:
            self._return_db(conn)

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
        conn = self._get_db()
        try:
            cursor = conn.cursor()
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
        finally:
            self._return_db(conn)

    def search_related_memories(
        self, query: str, current_session_id: str
    ) -> Tuple[List[str], List[str]]:
        query_embedding = self._get_embedding_with_cache(query)

        # 一次性查询所有相关数据，减少数据库往返
        conn = self._get_db()
        try:
            cursor = conn.cursor()

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
                # 批量获取所有需要的数据，减少查询次数
                text_ids = [r["text_id"] for r in summary_results]
                session_ids = [r["session_id"] for r in summary_results]

                # 单次查询获取会话信息和摘要内容
                session_placeholders = ",".join(["?"] * len(session_ids))
                text_placeholders = ",".join(["?"] * len(text_ids))

                # 联合查询减少数据库往返
                cursor.execute(
                    f"""
                    SELECT s.session_id, s.start_timestamp, s.end_timestamp, 
                           sm.summary, sm.text_id
                    FROM session s
                    JOIN summary sm ON s.session_id = sm.session_id
                    WHERE s.session_id IN ({session_placeholders})
                    AND sm.text_id IN ({text_placeholders})
                    """,
                    session_ids + text_ids,
                )

                # 构建查询结果映射
                session_data = {}
                for row in cursor.fetchall():
                    sid, start_ts, end_ts, summary_text, text_id = row
                    session_data[text_id] = {
                        "session_id": sid,
                        "start_time": utils.timestamp_to_datetime(start_ts),
                        "end_time": (
                            utils.timestamp_to_datetime(end_ts) if end_ts else None
                        ),
                        "summary": summary_text,
                    }

                # 构建结果，保持向量搜索的顺序
                for r in summary_results:
                    text_id = r["text_id"]
                    if text_id in session_data:
                        data = session_data[text_id]
                        start_time = data["start_time"]
                        end_time = data["end_time"]
                        related_summaries.append(
                            f"[会话时间: {utils.datetime_str(start_time)} - {utils.datetime_str(end_time) or '进行中'}]\n{data['summary']}"
                        )
                        related_session_ids.append(data["session_id"])

                # 性能日志记录
                if Config.ENABLE_PERFORMANCE_LOGGING:
                    summary_logs = []
                    for r in summary_results:
                        text_id = r["text_id"]
                        if text_id in session_data:
                            distance = r["_distance"]
                            summary_text = session_data[text_id]["summary"][:100]
                            summary_logs.append(
                                f"distance: {distance:.4f}, summary: {summary_text}"
                            )

                    if summary_logs:
                        logging.debug("相关摘要搜索结果:\n" + "\n".join(summary_logs))

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
                    # 批量获取对话数据
                    conv_text_ids = [r["text_id"] for r in conv_results]
                    conv_placeholders = ",".join(["?"] * len(conv_text_ids))

                    cursor.execute(
                        f"""
                        SELECT text_id, role, text, timestamp
                        FROM conversation
                        WHERE text_id IN ({conv_placeholders})
                        ORDER BY timestamp
                        """,
                        conv_text_ids,
                    )

                    # 构建对话数据映射
                    conv_data_map = {}
                    for row in cursor.fetchall():
                        text_id, role, text, timestamp = row
                        conv_data_map[text_id] = {
                            "role": role,
                            "text": text,
                            "timestamp": timestamp,
                        }

                    # 按向量搜索结果顺序构建对话列表
                    for r in conv_results:
                        text_id = r["text_id"]
                        if text_id in conv_data_map:
                            data = conv_data_map[text_id]
                            timestamp_dt = utils.timestamp_to_datetime(
                                data["timestamp"]
                            )
                            related_conversations.append(
                                f"[{utils.datetime_str(timestamp_dt)}] {data['role']}: {data['text']}"
                            )

                    # 性能日志记录
                    if Config.ENABLE_PERFORMANCE_LOGGING:
                        conv_logs = []
                        for r in conv_results:
                            text_id = r["text_id"]
                            if text_id in conv_data_map:
                                distance = r["_distance"]
                                data = conv_data_map[text_id]
                                conv_logs.append(
                                    f"distance: {distance:.4f}, {data['role']}: {data['text'][:100]}"
                                )

                        if conv_logs:
                            logging.debug("相关对话搜索结果:\n" + "\n".join(conv_logs))

            return related_summaries, related_conversations

        finally:
            self._return_db(conn)

    def _get_summary_texts(self, text_ids: List[str]) -> List[Dict]:
        """获取摘要文本 - 已优化为批量查询，减少冗余"""
        conn = self._get_db()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(text_ids))
            cursor.execute(
                f"""
                SELECT text_id, summary FROM summary 
                WHERE text_id IN ({placeholders})
                """,
                text_ids,
            )
            # 返回按text_id索引的结果，保持顺序
            result_map = {row[0]: {"summary": row[1]} for row in cursor.fetchall()}
            return [result_map.get(text_id, {"summary": ""}) for text_id in text_ids]
        finally:
            self._return_db(conn)

    def _get_conversation_texts(self, text_ids: List[str]) -> List[Dict]:
        """获取对话文本 - 已优化为批量查询，减少冗余"""
        conn = self._get_db()
        try:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(text_ids))
            cursor.execute(
                f"""
                SELECT text_id, role, text, timestamp FROM conversation 
                WHERE text_id IN ({placeholders})
                """,
                text_ids,
            )
            # 返回按text_id索引的结果，保持顺序
            result_map = {}
            for row in cursor.fetchall():
                text_id, role, text, timestamp = row
                result_map[text_id] = {
                    "role": role,
                    "text": text,
                    "timestamp": utils.timestamp_to_datetime(timestamp),
                }
            return [result_map.get(text_id, {}) for text_id in text_ids]
        finally:
            self._return_db(conn)

    def close_session(self, session_id: str) -> None:
        conn = self._get_db()
        try:
            cursor = conn.cursor()

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
                cleaned_text = utils.remove_blockquote_tags(text)
                cursor.execute(
                    """
                    UPDATE conversation 
                    SET text = ? 
                    WHERE conversation_id = ?
                    """,
                    (cleaned_text, conv_id),
                )

            # 更新session状态
            current_time = utils.now_tz()
            cursor.execute(
                """
                UPDATE session 
                SET end_timestamp = ?, status = 'archived'
                WHERE session_id = ?
                """,
                (utils.datetime_to_timestamp(current_time), session_id),
            )
            conn.commit()
        finally:
            self._return_db(conn)

    def reset_session(self, session_id: str) -> None:
        conn = self._get_db()
        try:
            cursor = conn.cursor()
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
                SET current_conv_count = 0,
                    start_timestamp = ?
                WHERE session_id = ?
            """,
                (utils.datetime_to_timestamp(utils.now_tz()), session_id),
            )
            conn.commit()
        finally:
            self._return_db(conn)

    def get_current_summary(self, session_id: str) -> Optional[str]:
        """获取当前会话的最新摘要"""
        conn = self._get_db()
        try:
            cursor = conn.cursor()
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
        finally:
            self._return_db(conn)

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

    def get_persona_memory(self) -> str:
        """获取AI助手的人格记忆"""
        if os.path.exists(Config.PERSONA_MEMORY_PATH):
            with open(Config.PERSONA_MEMORY_PATH, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def get_user_profile(self) -> str:
        """获取用户档案"""
        if os.path.exists(Config.USER_PROFILE_PATH):
            with open(Config.USER_PROFILE_PATH, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def get_conv_count(self, session_id: str) -> int:
        """获取当前会话的对话计数"""
        conn = self._get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT current_conv_count FROM session 
                WHERE session_id = ?
                """,
                (session_id,),
            )
            result = cursor.fetchone()
            return result[0] if result else 0
        finally:
            self._return_db(conn)

    def update_conv_count(self, session_id: str, delta: int) -> int:
        """更新当前会话的对话计数

        Args:
            session_id: 会话ID
            delta: 计数的变化值,可以是正数或负数

        Returns:
            更新后的对话计数
        """
        conn = self._get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE session 
                SET current_conv_count = current_conv_count + ?
                WHERE session_id = ?
                """,
                (delta, session_id),
            )
            conn.commit()
            result = self.get_conv_count(session_id)
            return result
        finally:
            self._return_db(conn)

    def clean_vector_db(self) -> None:
        """清理向量数据库中的孤立数据"""
        # 获取所有有效的text_id
        conn = self._get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT text_id FROM conversation")
            valid_conv_ids = {row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT text_id FROM summary")
            valid_summary_ids = {row[0] for row in cursor.fetchall()}
        finally:
            self._return_db(conn)

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

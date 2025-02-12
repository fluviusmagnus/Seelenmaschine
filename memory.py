import os
import json
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
import lancedb
import pyarrow as pa
from datetime import datetime
import uuid

from llm import LLMInterface

logger = logging.getLogger(__name__)


class MemoryManager:
    """管理所有类型的记忆"""

    def __init__(
        self, config_path: str = "config.txt", personality_path: str = "personality.txt"
    ):
        """初始化记忆管理器

        Args:
            config_path: 配置文件路径
            personality_path: 人格记忆文件路径
        """
        # 加载配置
        self.config = self._load_config(config_path)
        self.personality_path = personality_path

        # 初始化LLM接口
        self.llm = LLMInterface(config_path)

        # 确保数据库目录存在
        os.makedirs(self.config["DB_PATH"], exist_ok=True)

        # 连接数据库
        self.db = lancedb.connect(self.config["DB_PATH"])

        # 初始化数据表
        self._init_tables()

        # 加载人格记忆
        self.self_perception, self.user_perception = self._load_personality()

        # 当前会话信息
        self.current_session_id = None
        self.current_summary = None

    def _load_config(self, path: str) -> Dict[str, Any]:
        """加载配置文件"""
        config = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
        return config

    def _init_tables(self):
        """初始化数据库表"""
        # 定义会话表schema
        session_schema = pa.schema(
            [
                ("session_id", pa.string()),
                ("created_at", pa.float64()),
                ("last_active", pa.float64()),
                ("status", pa.string()),  # active, archived, deleted, suspended
                ("summary", pa.string()),
            ]
        )

        # 定义对话记录表schema
        conv_schema = pa.schema(
            [
                ("session_id", pa.string()),
                ("timestamp", pa.float64()),
                ("text", pa.string()),
                (
                    "vector",
                    pa.list_(pa.float32(), 1536),
                ),  # text-embedding-3-small的向量维度是1536
            ]
        )

        # 定义对话总结表schema
        summary_schema = pa.schema(
            [
                ("session_id", pa.string()),
                ("start_timestamp", pa.float64()),
                ("end_timestamp", pa.float64()),
                ("summary", pa.string()),
                ("vector", pa.list_(pa.float32(), 1536)),
            ]
        )

        # 创建会话表
        if "sessions" not in self.db.table_names():
            logger.debug("创建会话表")
            self.db.create_table("sessions", schema=session_schema)
        self.session_table = self.db.open_table("sessions")
        logger.debug("打开会话表")

        # 创建对话记录表
        if "conversations" not in self.db.table_names():
            logger.debug("创建对话记录表")
            self.db.create_table("conversations", schema=conv_schema)
        self.conv_table = self.db.open_table("conversations")
        logger.debug("打开对话记录表")

        # 创建对话总结表
        if "summaries" not in self.db.table_names():
            logger.debug("创建对话总结表")
            self.db.create_table("summaries", schema=summary_schema)
        self.summary_table = self.db.open_table("summaries")
        logger.debug("打开对话总结表")

    def _load_personality(self) -> Tuple[str, str]:
        """加载人格记忆"""
        with open(self.personality_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 解析自我认知和用户形象
        self_perception = ""
        user_perception = ""
        current_section = None

        for line in content.split("\n"):
            if line.startswith("# 自我认知"):
                current_section = "self"
            elif line.startswith("# 用户形象"):
                current_section = "user"
            elif line.startswith('SELF_PERCEPTION="""'):
                self_perception = line.split('"""', 1)[1]
            elif line.startswith('USER_PERCEPTION="""'):
                user_perception = line.split('"""', 1)[1]
            elif '"""' in line and (self_perception or user_perception):
                if current_section == "self":
                    self_perception += line.split('"""')[0]
                else:
                    user_perception += line.split('"""')[0]
            elif self_perception and user_perception:
                if current_section == "self" and not '"""' in line:
                    self_perception += line
                elif current_section == "user" and not '"""' in line:
                    user_perception += line

        return self_perception.strip(), user_perception.strip()

    def _save_personality(self):
        """保存人格记忆"""
        content = f"""# 自我认知
## 这部分描述AI助手对自己的认知,会随着对话逐渐更新和深化
SELF_PERCEPTION=\"\"\"{self.self_perception}\"\"\"

# 用户形象
## 这部分描述AI助手对用户的认知,会随着对话逐渐更新和深化
USER_PERCEPTION=\"\"\"{self.user_perception}\"\"\""""

        with open(self.personality_path, "w", encoding="utf-8") as f:
            f.write(content)

    def start_new_session(self) -> str:
        """开始新的会话"""
        # 生成新的会话ID
        self.current_session_id = str(uuid.uuid4())
        self.current_summary = None

        # 创建会话记录
        session_data = {
            "session_id": self.current_session_id,
            "created_at": time.time(),
            "last_active": time.time(),
            "status": "active",
            "summary": "",
        }
        self.session_table.add([session_data])
        logger.debug(f"创建新会话: session_id={self.current_session_id}")

        return self.current_session_id

    def load_session(self, session_id: str):
        """加载已有会话"""
        # 从sessions表加载会话
        results = (
            self.session_table.search().where(f"session_id = '{session_id}'").to_list()
        )

        if not results:
            logger.warning(f"会话不存在: session_id={session_id}")
            return

        session = results[0]
        if session["status"] not in ["active", "suspended"]:
            logger.warning(
                f"会话状态不可用: session_id={session_id}, status={session['status']}"
            )
            return

        # 如果是暂存的会话,重新激活
        if session["status"] == "suspended":
            self.session_table.update().where(f"session_id = '{session_id}'").set(
                {"status": "active", "last_active": time.time()}
            ).execute()
            logger.debug(f"重新激活暂存会话: session_id={session_id}")

        self.current_session_id = session_id
        self.current_summary = session["summary"]

        # 更新最后活跃时间
        self.session_table.update().where(f"session_id = '{session_id}'").set(
            {"last_active": time.time()}
        ).execute()
        logger.debug(f"加载会话: session_id={session_id}")

    def save_conversation(self, role: str, text: str):
        """保存新的对话"""
        if not self.current_session_id:
            self.start_new_session()

        # 生成向量表示
        vector = self.llm.get_embedding(text)

        # 保存到数据库
        conversation_data = {
            "session_id": self.current_session_id,
            "timestamp": time.time(),
            "text": f"{role}: {text}",
            "vector": vector,
        }
        self.conv_table.add([conversation_data])
        logger.debug(f"保存对话记录: session_id={self.current_session_id}, role={role}")

    def get_current_conversation(self) -> List[Dict[str, str]]:
        """获取当前会话的所有对话"""
        if not self.current_session_id:
            return []

        logger.debug(f"查询当前会话对话: session_id={self.current_session_id}")
        results = (
            self.conv_table.search()
            .where(f"session_id = '{self.current_session_id}'")
            .to_arrow()
            .sort_by("timestamp")
            .to_pylist()
        )

        conversations = []
        for result in results:
            role, text = result["text"].split(": ", 1)
            conversations.append({"role": role.lower(), "text": text})

        logger.debug(f"获取到 {len(conversations)} 条对话记录")
        return conversations

    def get_relevant_memories(
        self, query: str, exclude_session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """检索相关记忆

        Args:
            query: 查询文本
            exclude_session_id: 要排除的会话ID

        Returns:
            相关记忆列表,每个元素包含会话总结和具体对话
        """
        logger.debug(
            f"开始检索相关记忆: query='{query}', exclude_session_id={exclude_session_id}"
        )

        # 生成查询向量
        query_vector = self.llm.get_embedding(query)

        # 搜索相关会话总结
        where_clause = ""
        if exclude_session_id:
            where_clause = f"session_id != '{exclude_session_id}'"

        summaries = (
            self.summary_table.search(query_vector, vector_column_name="vector")
            .where(where_clause)
            .limit(int(self.config["RECALL_SESSION_NUM"]))
            .to_arrow()
            .to_pylist()
        )

        logger.debug(f"检索到 {len(summaries)} 个相关会话总结")

        # 对每个相关会话,搜索具体对话
        memories = []
        for summary in summaries:
            # 获取会话中的相关对话
            conversations = (
                self.conv_table.search(query_vector, vector_column_name="vector")
                .where(f"session_id = '{summary['session_id']}'")
                .limit(int(self.config["RECALL_CONV_NUM"]))
                .to_arrow()
                .to_pylist()
            )

            # 转换对话格式
            conv_list = []
            for conv in conversations:
                role, text = conv["text"].split(": ", 1)
                conv_list.append({"role": role.lower(), "text": text})

            memories.append(
                {
                    "summary": summary["summary"],
                    "conversations": sorted(
                        conv_list,
                        key=lambda x: x["timestamp"] if "timestamp" in x else 0,
                    ),
                }
            )

        return memories

    def update_summary(self):
        """更新当前会话的总结"""
        if not self.current_session_id:
            return

        # 获取当前会话
        conversations = self.get_current_conversation()
        if len(conversations) <= int(self.config["MAX_CONV_NUM"]):
            return

        # 获取需要总结的对话
        conv_to_summarize = conversations[: int(self.config["REFRESH_EVERY_CONV_NUM"])]

        # 生成新的总结
        new_summary = self.llm.generate_summary(conv_to_summarize, self.current_summary)
        self.current_summary = new_summary

        # 保存总结
        start_time = time.time() - 86400  # 假设开始时间是24小时前
        end_time = time.time()

        # 生成总结的向量表示
        vector = self.llm.get_embedding(new_summary)

        # 保存到summaries表
        summary_data = {
            "session_id": self.current_session_id,
            "start_timestamp": start_time,
            "end_timestamp": end_time,
            "summary": new_summary,
            "vector": vector,
        }
        self.summary_table.add([summary_data])

        # 更新sessions表中的summary
        self.session_table.update().where(
            f"session_id = '{self.current_session_id}'"
        ).set({"summary": new_summary, "last_active": time.time()}).execute()
        logger.debug(f"更新会话总结: session_id={self.current_session_id}")

    def update_personality(self):
        """更新人格记忆"""
        if not self.current_session_id:
            return

        # 获取当前会话总结
        if not self.current_summary:
            conversations = self.get_current_conversation()
            self.current_summary = self.llm.generate_summary(conversations)

        # 更新人格记忆
        self.self_perception, self.user_perception = self.llm.update_personality(
            self.self_perception, self.user_perception, self.current_summary
        )

        # 保存更新后的人格记忆
        self._save_personality()

    def suspend_session(self):
        """暂存当前会话"""
        if not self.current_session_id:
            return

        # 更新会话状态为suspended
        self.session_table.update().where(
            f"session_id = '{self.current_session_id}'"
        ).set({"status": "suspended", "last_active": time.time()}).execute()
        logger.debug(f"暂存会话: session_id={self.current_session_id}")

        # 重置当前会话状态
        self.current_session_id = None
        self.current_summary = None

    def reset_session(self):
        """重置当前会话"""
        if not self.current_session_id:
            return

        # 更新会话状态为deleted
        self.session_table.update().where(
            f"session_id = '{self.current_session_id}'"
        ).set({"status": "deleted", "last_active": time.time()}).execute()
        logger.debug(f"标记会话为deleted: session_id={self.current_session_id}")

        # 删除相关数据
        self.conv_table.delete(f"session_id = '{self.current_session_id}'")
        self.summary_table.delete(f"session_id = '{self.current_session_id}'")
        logger.debug(f"删除会话相关数据: session_id={self.current_session_id}")

        # 重置会话状态
        self.current_session_id = None
        self.current_summary = None

    def save_session(self):
        """归档当前会话"""
        if not self.current_session_id:
            return

        # 确保有总结
        if not self.current_summary:
            conversations = self.get_current_conversation()
            if conversations:
                self.current_summary = self.llm.generate_summary(conversations)

        # 更新会话状态和总结
        if self.current_summary:
            # 生成总结的向量表示
            vector = self.llm.get_embedding(self.current_summary)

            # 保存到summaries表
            summary_data = {
                "session_id": self.current_session_id,
                "start_timestamp": time.time() - 86400,  # 假设开始时间是24小时前
                "end_timestamp": time.time(),
                "summary": self.current_summary,
                "vector": vector,
            }
            self.summary_table.add([summary_data])

            # 更新sessions表
            self.session_table.update().where(
                f"session_id = '{self.current_session_id}'"
            ).set(
                {
                    "status": "archived",
                    "last_active": time.time(),
                    "summary": self.current_summary,
                }
            ).execute()
            logger.debug(f"归档会话: session_id={self.current_session_id}")

        # 更新人格记忆
        self.update_personality()

        # 开始新会话
        self.start_new_session()

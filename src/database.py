import lancedb
from datetime import datetime
from typing import List, Dict, Optional
import json
import pyarrow as pa

from config import DB_PATH, EMBEDDING_MODEL, OPENAI_API_KEY, OPENAI_API_BASE
from openai import OpenAI


class Database:
    def __init__(self):
        # Ensure we're using persistent storage mode
        self.db = lancedb.connect(str(DB_PATH))
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_API_BASE,
        )
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure required tables exist"""
        # Only create table if it doesn't exist
        if "conversations" not in self.db.table_names():
            schema = pa.schema(
                [
                    ("session_id", pa.string()),
                    (
                        "start_timestamp",
                        pa.timestamp("us"),
                    ),  # Changed to microsecond precision
                    (
                        "end_timestamp",
                        pa.timestamp("us"),
                    ),  # Changed to microsecond precision
                    ("summary", pa.string()),
                    (
                        "vector",
                        pa.list_(pa.float32(), 1536),
                    ),  # Dimension for text-embedding-3-small (1536)
                    ("conversations", pa.string()),  # JSON string of conversation list
                ]
            )
            self.db.create_table("conversations", schema=schema)

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding vector for text"""
        response = self.client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    def save_session(
        self,
        session_id: str,
        summary: str,
        conversations: List[Dict],
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> None:
        """Save or update a chat session"""
        if end_time is None:
            end_time = datetime.now()

        table = self.db.open_table("conversations")
        vector = self._get_embedding(summary)

        data = {
            "session_id": session_id,
            "start_timestamp": start_time,
            "end_timestamp": end_time,
            "summary": summary,
            "vector": vector,
            "conversations": json.dumps(conversations),
        }

        # Update if exists, otherwise create
        existing = table.search().where(f"session_id = '{session_id}'").to_pandas()
        if len(existing) > 0:
            table.delete(f"session_id = '{session_id}'")
        table.add([data])

    def find_relevant_sessions(self, query: str, limit: int = 3) -> List[Dict]:
        """Find relevant past sessions based on query"""
        vector = self._get_embedding(query)
        table = self.db.open_table("conversations")

        results = table.search(vector).limit(limit).to_pandas()

        sessions = []
        for _, row in results.iterrows():
            sessions.append(
                {
                    "session_id": row["session_id"],
                    "summary": row["summary"],
                    "conversations": json.loads(row["conversations"]),
                }
            )

        return sessions

    def get_last_session(self) -> Optional[Dict]:
        """Get the most recent session"""
        table = self.db.open_table("conversations")

        # First check if table has any data
        df = table.to_pandas()
        if len(df) == 0:
            return None

        # Sort by end_timestamp if we have data
        df = df.sort_values("end_timestamp", ascending=False).head(1)
        row = df.iloc[0]

        return {
            "session_id": row["session_id"],
            "summary": row["summary"],
            "conversations": json.loads(row["conversations"]),
            "start_time": row["start_timestamp"].to_pydatetime(),
        }

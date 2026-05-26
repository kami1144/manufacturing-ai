"""
知识库持久化层 - SQLite

功能：
- 将 KB 条目持久化到 SQLite 数据库
- 启动时从数据库加载
- 运行时自动保存（增量 upsert）

使用：
    from app.workflow.kb_persistence import PersistedKnowledgeBase

    # 初始化持久化层
    kb_persisted = PersistedKnowledgeBase()

    # 保存条目
    kb_persisted.save_entry(entry)

    # 加载所有条目（启动时）
    entries = kb_persisted.load_all()
"""

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

from app.modules.kb_module import KBEntry


# 数据库路径（在项目根目录）
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.file__))),
    "kb.sqlite"
)


@dataclass
class PersistedEntry:
    """持久化的 KB 条目"""
    id: str
    title: str
    content: str
    category: str
    keywords: list[str] = field(default_factory=list)
    source: str = ""
    updated_at: int = field(default_factory=lambda: int(time.time()))


class PersistedKnowledgeBase:
    """基于 SQLite 的知识库持久化层"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv("KB_DB_PATH", DB_PATH)
        self._ensure_db()

    def _ensure_db(self):
        """确保数据库和表存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_entries (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                category TEXT,
                keywords TEXT,
                source TEXT,
                updated_at INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON kb_entries(category)
        """)
        conn.commit()
        conn.close()

    def save_entry(self, entry: KBEntry) -> None:
        """保存/更新单条记录（upsert）"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO kb_entries (id, title, content, category, keywords, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                category = excluded.category,
                keywords = excluded.keywords,
                source = excluded.source,
                updated_at = excluded.updated_at
        """, (
            entry.id,
            entry.title,
            entry.content,
            entry.category,
            json.dumps(entry.keywords, ensure_ascii=False),
            entry.source,
            int(time.time())
        ))
        conn.commit()
        conn.close()

    def load_all(self) -> list[PersistedEntry]:
        """加载所有条目"""
        if not os.path.exists(self.db_path):
            return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT id, title, content, category, keywords, source, updated_at FROM kb_entries")
        entries = []
        for row in cursor.fetchall():
            entries.append(PersistedEntry(
                id=row[0],
                title=row[1],
                content=row[2],
                category=row[3],
                keywords=json.loads(row[4]) if row[4] else [],
                source=row[5],
                updated_at=row[6]
            ))
        conn.close()
        return entries

    def delete(self, entry_id: str) -> bool:
        """删除条目"""
        if not os.path.exists(self.db_path):
            return False

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("DELETE FROM kb_entries WHERE id = ?", (entry_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def count(self) -> int:
        """统计条目数"""
        if not os.path.exists(self.db_path):
            return 0

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM kb_entries")
        count = cursor.fetchone()[0]
        conn.close()
        return count


# ── 单例 ────────────────────────────────────────────────

_persisted: Optional[PersistedKnowledgeBase] = None


def get_persisted_kb() -> PersistedKnowledgeBase:
    global _persisted
    if _persisted is None:
        _persisted = PersistedKnowledgeBase()
    return _persisted
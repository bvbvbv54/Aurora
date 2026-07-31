"""Persistent SQLite topic graph for accumulated Aurora research evidence."""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

NodeType = Literal["problem", "workflow", "platform", "audience"]
NodeStatus = Literal["explored", "unexplored", "emerging"]


@dataclass(frozen=True)
class TopicNode:
    niche: str
    label: str
    node_type: NodeType
    status: NodeStatus = "unexplored"
    evidence_count: int = 0
    median_views: float = 0.0
    id: int | None = None
    created_at: str = ""
    updated_at: str = ""


class TopicGraph:
    """Lightweight knowledge graph stored beside Aurora's relational tables."""

    CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS topic_nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        niche TEXT NOT NULL,
        label TEXT NOT NULL,
        node_type TEXT NOT NULL DEFAULT 'problem',
        status TEXT NOT NULL DEFAULT 'unexplored',
        evidence_count INTEGER NOT NULL DEFAULT 0,
        median_views REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(niche, label)
    );
    CREATE INDEX IF NOT EXISTS idx_topic_nodes_niche ON topic_nodes(niche);
    CREATE INDEX IF NOT EXISTS idx_topic_nodes_status ON topic_nodes(status);
    """

    def __init__(self, db_path: str | Path = "aurora.db") -> None:
        self.db_path = str(db_path)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._conn() as connection:
            connection.executescript(self.CREATE_TABLE)

    def ingest_titles(self, evidence: list, niche: str) -> int:
        patterns: dict[str, NodeType] = {
            "not working": "problem",
            "fix": "problem",
            "crash": "problem",
            "error": "problem",
            "black screen": "problem",
            "not loading": "problem",
            "login": "problem",
            "how to": "workflow",
            "setup": "workflow",
            "step by step": "workflow",
            "on android": "platform",
            "on iphone": "platform",
            "on mobile": "platform",
            "for beginners": "audience",
            "for freelancers": "audience",
        }
        node_evidence: dict[tuple[str, NodeType], list[int]] = {}
        for item in evidence:
            title = item.title.lower()
            for pattern, node_type in patterns.items():
                if pattern in title:
                    node_evidence.setdefault((pattern, node_type), []).append(item.views)

        now = datetime.now(UTC).isoformat()
        new_count = 0
        with self._conn() as connection:
            for (label, node_type), views in node_evidence.items():
                existing = connection.execute(
                    "SELECT id FROM topic_nodes WHERE niche=? AND label=?",
                    (niche, label),
                ).fetchone()
                values = (len(views), statistics.median(views), now, niche, label)
                if existing:
                    connection.execute(
                        """UPDATE topic_nodes SET evidence_count=?, median_views=?,
                           updated_at=? WHERE niche=? AND label=?""",
                        values,
                    )
                else:
                    connection.execute(
                        """INSERT INTO topic_nodes
                           (niche,label,node_type,status,evidence_count,median_views,
                            created_at,updated_at)
                           VALUES (?,? ,?,'unexplored',?,?,?,?)""",
                        (
                            niche,
                            label,
                            node_type,
                            len(views),
                            statistics.median(views),
                            now,
                            now,
                        ),
                    )
                    new_count += 1
        return new_count

    def mark_explored(self, niche: str, label: str) -> None:
        self._mark(niche, label, "explored")

    def mark_emerging(self, niche: str, label: str) -> None:
        self._mark(niche, label, "emerging")

    def _mark(self, niche: str, label: str, status: NodeStatus) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as connection:
            connection.execute(
                """INSERT INTO topic_nodes
                   (niche,label,node_type,status,evidence_count,median_views,created_at,updated_at)
                   VALUES (?,?,'problem',?,0,0.0,?,?)
                   ON CONFLICT(niche,label) DO UPDATE SET status=excluded.status,
                   updated_at=excluded.updated_at""",
                (niche, label, status, now, now),
            )

    def find_unexplored(self, niche: str, limit: int = 20) -> list[TopicNode]:
        with self._conn() as connection:
            rows = connection.execute(
                """SELECT * FROM topic_nodes WHERE niche=? AND status='unexplored'
                   ORDER BY evidence_count DESC LIMIT ?""",
                (niche, limit),
            ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def find_emerging(self, niche: str, min_evidence: int = 3) -> list[TopicNode]:
        with self._conn() as connection:
            rows = connection.execute(
                """SELECT * FROM topic_nodes WHERE niche=? AND status='emerging'
                   AND evidence_count>=? ORDER BY median_views DESC""",
                (niche, min_evidence),
            ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def summary(self, niche: str) -> dict[str, int]:
        with self._conn() as connection:
            row = connection.execute(
                """SELECT
                   SUM(CASE WHEN status='explored' THEN 1 ELSE 0 END) AS explored,
                   SUM(CASE WHEN status='unexplored' THEN 1 ELSE 0 END) AS unexplored,
                   SUM(CASE WHEN status='emerging' THEN 1 ELSE 0 END) AS emerging
                   FROM topic_nodes WHERE niche=?""",
                (niche,),
            ).fetchone()
        return {
            "explored": int(row["explored"] or 0),
            "unexplored": int(row["unexplored"] or 0),
            "emerging": int(row["emerging"] or 0),
        }

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> TopicNode:
        return TopicNode(
            id=row["id"],
            niche=row["niche"],
            label=row["label"],
            node_type=row["node_type"],
            status=row["status"],
            evidence_count=row["evidence_count"],
            median_views=row["median_views"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

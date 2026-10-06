from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FeedbackMemory:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists feedback_memory (
                    id integer primary key autoincrement,
                    session_id text not null,
                    edition_date text not null,
                    category text not null,
                    sport text not null,
                    agent_id text not null,
                    agent_name text not null,
                    score integer not null,
                    what_worked text not null,
                    improve_next text not null,
                    learning_rule text not null,
                    created_at text not null default current_timestamp
                );
                create index if not exists feedback_memory_lookup_idx
                    on feedback_memory(category, agent_id, created_at desc);

                create table if not exists local_runs (
                    session_id text primary key,
                    edition_date text not null,
                    category text not null,
                    sport text not null,
                    topic text not null,
                    source_name text,
                    markdown_sha256 text not null,
                    output_path text not null,
                    created_at text not null default current_timestamp
                );
                """
            )

    def recent_rules(
        self,
        *,
        category: str,
        agent_ids: list[str],
        per_agent: int = 3,
    ) -> list[dict[str, Any]]:
        if not agent_ids:
            return []
        placeholders = ",".join("?" for _ in agent_ids)
        query = f"""
            select category, agent_id, agent_name, score, improve_next, learning_rule, created_at
            from feedback_memory
            where agent_id in ({placeholders})
              and (category = ? or category = '*')
            order by created_at desc
        """
        with self._connect() as conn:
            rows = conn.execute(query, [*agent_ids, category]).fetchall()
        result: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for row in rows:
            agent_id = str(row["agent_id"])
            if counts.get(agent_id, 0) >= per_agent:
                continue
            counts[agent_id] = counts.get(agent_id, 0) + 1
            result.append(dict(row))
        return result

    def save_feedback(
        self,
        *,
        session_id: str,
        edition_date: str,
        category: str,
        sport: str,
        feedback: list[dict[str, Any]],
    ) -> None:
        rows = [
            (
                session_id, edition_date, category, sport,
                item["agent_id"], item["agent_name"], int(item["score"]),
                item["what_worked"], item["improve_next"], item["learning_rule"],
            )
            for item in feedback
        ]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                insert into feedback_memory(
                    session_id, edition_date, category, sport,
                    agent_id, agent_name, score, what_worked, improve_next, learning_rule
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def save_run(
        self,
        *,
        session_id: str,
        edition_date: str,
        category: str,
        sport: str,
        topic: str,
        source_name: str,
        markdown_sha256: str,
        output_path: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into local_runs(
                    session_id, edition_date, category, sport, topic,
                    source_name, markdown_sha256, output_path
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, edition_date, category, sport, topic,
                    source_name, markdown_sha256, output_path,
                ),
            )

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            feedback_count = conn.execute("select count(*) from feedback_memory").fetchone()[0]
            run_count = conn.execute("select count(*) from local_runs").fetchone()[0]
        return {"feedback_count": int(feedback_count), "run_count": int(run_count)}

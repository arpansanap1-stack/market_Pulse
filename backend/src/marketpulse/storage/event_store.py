"""Append-only SQLite event store for session persistence and historical replay."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marketpulse.core.events import Event, event_from_json


@dataclass(slots=True, frozen=True)
class SessionMetadata:
    """Metadata describing a recorded or live simulation session."""

    session_id: str
    symbol: str
    seed: int
    config: dict[str, Any]
    start_ts_ns: int
    end_ts_ns: int | None
    total_events: int
    status: str  # "ACTIVE", "STOPPED", "COMPLETED"
    created_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        """Convert session metadata to a JSON-serializable dictionary."""
        return asdict(self)


class SQLiteEventStore:
    """ACID append-only event store backed by SQLite."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        # check_same_thread=False allows multi-threaded access when queries are synchronized
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database pragmas, tables, and indexes."""
        with self._conn:
            # Enable WAL mode for non-memory databases for concurrency and fast writes
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
                self._conn.execute("PRAGMA synchronous = NORMAL;")
            self._conn.execute("PRAGMA foreign_keys = ON;")

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    config_json TEXT NOT NULL,
                    start_ts_ns INTEGER NOT NULL,
                    end_ts_ns INTEGER,
                    total_events INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                """
            )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    ts_ns INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (session_id, seq),
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
                );
                """
            )

            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_session_ts
                ON events (session_id, ts_ns);
                """
            )

    def create_session(
        self,
        session_id: str,
        symbol: str,
        seed: int,
        config: dict[str, Any],
        start_ts_ns: int,
        created_at_utc: str | None = None,
    ) -> SessionMetadata:
        """Create and record a new simulation session."""
        if not session_id:
            raise ValueError("session_id must be non-empty")
        if not symbol:
            raise ValueError("symbol must be non-empty")

        created_at = created_at_utc or datetime.now(UTC).isoformat()
        config_json = json.dumps(config, sort_keys=True)
        status = "ACTIVE"
        total_events = 0

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, symbol, seed, config_json, start_ts_ns,
                    end_ts_ns, total_events, status, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?);
                """,
                (
                    session_id,
                    symbol,
                    seed,
                    config_json,
                    start_ts_ns,
                    total_events,
                    status,
                    created_at,
                ),
            )

        return SessionMetadata(
            session_id=session_id,
            symbol=symbol,
            seed=seed,
            config=config,
            start_ts_ns=start_ts_ns,
            end_ts_ns=None,
            total_events=total_events,
            status=status,
            created_at_utc=created_at,
        )

    def get_session(self, session_id: str) -> SessionMetadata | None:
        """Retrieve metadata for a specific session."""
        cursor = self._conn.execute(
            """
            SELECT session_id, symbol, seed, config_json, start_ts_ns,
                   end_ts_ns, total_events, status, created_at_utc
            FROM sessions
            WHERE session_id = ?;
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return SessionMetadata(
            session_id=row["session_id"],
            symbol=row["symbol"],
            seed=row["seed"],
            config=json.loads(row["config_json"]),
            start_ts_ns=row["start_ts_ns"],
            end_ts_ns=row["end_ts_ns"],
            total_events=row["total_events"],
            status=row["status"],
            created_at_utc=row["created_at_utc"],
        )

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[SessionMetadata]:
        """List recorded simulation sessions ordered by creation date descending."""
        cursor = self._conn.execute(
            """
            SELECT session_id, symbol, seed, config_json, start_ts_ns,
                   end_ts_ns, total_events, status, created_at_utc
            FROM sessions
            ORDER BY created_at_utc DESC
            LIMIT ? OFFSET ?;
            """,
            (max(1, limit), max(0, offset)),
        )
        rows = cursor.fetchall()
        return [
            SessionMetadata(
                session_id=r["session_id"],
                symbol=r["symbol"],
                seed=r["seed"],
                config=json.loads(r["config_json"]),
                start_ts_ns=r["start_ts_ns"],
                end_ts_ns=r["end_ts_ns"],
                total_events=r["total_events"],
                status=r["status"],
                created_at_utc=r["created_at_utc"],
            )
            for r in rows
        ]

    def update_session(
        self,
        session_id: str,
        status: str | None = None,
        end_ts_ns: int | None = None,
        total_events: int | None = None,
    ) -> None:
        """Update status, completion time, or event count for a session."""
        updates: list[str] = []
        params: list[Any] = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if end_ts_ns is not None:
            updates.append("end_ts_ns = ?")
            params.append(end_ts_ns)
        if total_events is not None:
            updates.append("total_events = ?")
            params.append(total_events)

        if not updates:
            return

        params.append(session_id)
        sql = f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?;"
        with self._conn:
            self._conn.execute(sql, params)

    def append_event(self, session_id: str, event: Event) -> None:
        """Append a single event to the session event log."""
        self.append_events(session_id, [event])

    def append_events(self, session_id: str, events: Sequence[Event]) -> None:
        """Append a batch of events atomically to the session event log."""
        if not events:
            return

        rows = [
            (
                session_id,
                e.seq,
                e.ts_ns,
                e.event_type.value,
                e.to_json(),
            )
            for e in events
        ]

        max_seq = max(e.seq for e in events)

        with self._conn:
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO events (
                    session_id, seq, ts_ns, event_type, payload_json
                ) VALUES (?, ?, ?, ?, ?);
                """,
                rows,
            )
            # Maintain total_events counter on session
            self._conn.execute(
                """
                UPDATE sessions
                SET total_events = MAX(total_events, ?)
                WHERE session_id = ?;
                """,
                (max_seq, session_id),
            )

    def count_events(self, session_id: str) -> int:
        """Return the number of persisted events for a session."""
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE session_id = ?;",
            (session_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def get_events(
        self,
        session_id: str,
        from_seq: int = 1,
        to_seq: int | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """Fetch a slice of events for a session within sequence boundaries."""
        query = "SELECT payload_json FROM events WHERE session_id = ? AND seq >= ?"
        params: list[Any] = [session_id, from_seq]

        if to_seq is not None:
            query += " AND seq <= ?"
            params.append(to_seq)

        query += " ORDER BY seq ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(max(1, limit))

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()
        return [event_from_json(r["payload_json"]) for r in rows]

    def stream_events(
        self,
        session_id: str,
        from_seq: int = 1,
        to_seq: int | None = None,
        chunk_size: int = 500,
    ) -> Iterator[Event]:
        """Stream events lazily in chunks for memory-efficient iteration."""
        current_seq = from_seq
        while True:
            chunk = self.get_events(
                session_id=session_id,
                from_seq=current_seq,
                to_seq=to_seq,
                limit=chunk_size,
            )
            if not chunk:
                break
            yield from chunk
            if len(chunk) < chunk_size:
                break
            current_seq = chunk[-1].seq + 1

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

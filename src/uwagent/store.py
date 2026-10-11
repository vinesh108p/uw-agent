"""SQLite persistence: leads, cases, reply/UW facts, flags, outbox, cards, decisions and an audit trail."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .facts import Fact
from .models import Lead, UWDecision

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leads (lead_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cases (lead_id TEXT PRIMARY KEY, state TEXT NOT NULL, rounds_sent INTEGER NOT NULL DEFAULT 0,
    assessment_json TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, field TEXT NOT NULL, value_json TEXT NOT NULL,
    source TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS flags (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, round INTEGER NOT NULL, text TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tool_calls (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, run_id TEXT NOT NULL, tool TEXT NOT NULL,
    args_json TEXT NOT NULL, ok INTEGER NOT NULL, reasons_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, kind TEXT NOT NULL, round INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, status TEXT NOT NULL, mailbox_id INTEGER, error TEXT,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, round INTEGER NOT NULL, payload_json TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL, lead_id TEXT NOT NULL, round INTEGER NOT NULL,
    choice TEXT NOT NULL, note TEXT NOT NULL, scope_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages_in (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, round INTEGER NOT NULL, body TEXT NOT NULL,
    parsed_json TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes (lead_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(value: Any) -> str:
    return json.dumps(value, default=str)


class Store:
    def __init__(self, path: Path | str):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            row = self._conn.execute("SELECT value FROM meta WHERE key = 'instance_id'").fetchone()
            if row is None:
                self.instance_id = uuid.uuid4().hex[:8]
                self._conn.execute("INSERT INTO meta (key, value) VALUES ('instance_id', ?)", (self.instance_id,))
            else:
                self.instance_id = row["value"]

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _exec(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).lastrowid

    # leads & cases
    def upsert_lead(self, lead: Lead) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO leads (lead_id, payload_json, created_at) VALUES (?, ?, ?)",
                               (lead.lead_id, lead.model_dump_json(), _now()))
            self._conn.execute("INSERT OR IGNORE INTO cases (lead_id, state, rounds_sent, updated_at) VALUES (?, 'NEW', 0, ?)",
                               (lead.lead_id, _now()))

    def get_lead(self, lead_id: str) -> Lead:
        rows = self._rows("SELECT payload_json FROM leads WHERE lead_id = ?", (lead_id,))
        if not rows:
            raise KeyError(lead_id)
        return Lead.model_validate_json(rows[0]["payload_json"])

    def lead_ids(self) -> list[str]:
        return [r["lead_id"] for r in self._rows("SELECT lead_id FROM leads ORDER BY lead_id")]

    def get_case(self, lead_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM cases WHERE lead_id = ?", (lead_id,))
        if not rows:
            return None
        row = rows[0]
        return {"lead_id": row["lead_id"], "state": row["state"], "rounds_sent": row["rounds_sent"],
                "assessment": json.loads(row["assessment_json"]) if row["assessment_json"] else None,
                "updated_at": row["updated_at"]}

    def update_case(self, lead_id: str, *, state: str | None = None, rounds_sent: int | None = None,
                    assessment: dict[str, Any] | None = None) -> None:
        sets, params = ["updated_at = ?"], [_now()]
        if state is not None:
            sets.append("state = ?")
            params.append(state)
        if rounds_sent is not None:
            sets.append("rounds_sent = ?")
            params.append(rounds_sent)
        if assessment is not None:
            sets.append("assessment_json = ?")
            params.append(_dump(assessment))
        self._exec(f"UPDATE cases SET {', '.join(sets)} WHERE lead_id = ?", (*params, lead_id))

    # facts & flags
    def add_fact(self, lead_id: str, fact: Fact) -> None:
        self._exec("INSERT INTO facts (lead_id, field, value_json, source, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (lead_id, fact.field, _dump(fact.value), fact.source, fact.detail, _now()))

    def facts_for(self, lead_id: str) -> list[Fact]:
        rows = self._rows("SELECT * FROM facts WHERE lead_id = ? ORDER BY id", (lead_id,))
        return [Fact(r["field"], json.loads(r["value_json"]), r["source"], r["detail"]) for r in rows]

    def add_flag(self, lead_id: str, round_: int, text: str) -> None:
        self._exec("INSERT INTO flags (lead_id, round, text) VALUES (?, ?, ?)", (lead_id, round_, text))

    def open_flags(self, lead_id: str) -> list[str]:
        return [r["text"] for r in self._rows("SELECT text FROM flags WHERE lead_id = ? AND resolved = 0 ORDER BY id", (lead_id,))]

    def resolve_flags(self, lead_id: str) -> None:
        self._exec("UPDATE flags SET resolved = 1 WHERE lead_id = ?", (lead_id,))

    # tool calls
    def log_tool_call(self, lead_id: str, run_id: str, tool: str, args: dict[str, Any], ok: bool, reasons: list[str]) -> None:
        self._exec("INSERT INTO tool_calls (lead_id, run_id, tool, args_json, ok, reasons_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (lead_id, run_id, tool, _dump(args), int(ok), _dump(reasons), _now()))

    def tool_calls_for(self, lead_id: str) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM tool_calls WHERE lead_id = ? ORDER BY id", (lead_id,))
        return [{"id": r["id"], "run_id": r["run_id"], "tool": r["tool"], "args": json.loads(r["args_json"]), "ok": bool(r["ok"]),
                 "reasons": json.loads(r["reasons_json"]), "created_at": r["created_at"]} for r in rows]

    # outbox
    def _outbox(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "lead_id": row["lead_id"], "kind": row["kind"], "round": row["round"],
                "idempotency_key": row["idempotency_key"], "payload": json.loads(row["payload_json"]), "status": row["status"],
                "mailbox_id": row["mailbox_id"], "error": row["error"]}

    def enqueue_outbox(self, lead_id: str, kind: str, round_: int, payload: dict[str, Any], revision: int = 0) -> dict[str, Any]:
        key = f"{self.instance_id}:{lead_id}:{kind}:{round_}" + (f":r{revision}" if revision else "")
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO outbox (lead_id, kind, round, idempotency_key, payload_json, status, created_at) "
                               "VALUES (?, ?, ?, ?, ?, 'pending', ?)", (lead_id, kind, round_, key, _dump(payload), _now()))
            row = self._conn.execute("SELECT * FROM outbox WHERE idempotency_key = ?", (key,)).fetchone()
        return self._outbox(row)

    def get_outbox(self, outbox_id: int) -> dict[str, Any]:
        return self._outbox(self._rows("SELECT * FROM outbox WHERE id = ?", (outbox_id,))[0])

    def outbox_for(self, lead_id: str) -> list[dict[str, Any]]:
        return [self._outbox(r) for r in self._rows("SELECT * FROM outbox WHERE lead_id = ? ORDER BY id", (lead_id,))]

    def pending_outbox(self) -> list[dict[str, Any]]:
        return [self._outbox(r) for r in self._rows("SELECT * FROM outbox WHERE status IN ('pending', 'failed') ORDER BY id")]

    def mark_outbox_sent(self, outbox_id: int, mailbox_id: int) -> None:
        self._exec("UPDATE outbox SET status = 'sent', mailbox_id = ?, error = NULL WHERE id = ?", (mailbox_id, outbox_id))

    def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        self._exec("UPDATE outbox SET status = 'failed', error = ? WHERE id = ?", (error, outbox_id))

    # cards & decisions
    def _card(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "lead_id": row["lead_id"], "round": row["round"], "payload": json.loads(row["payload_json"]),
                "status": row["status"], "created_at": row["created_at"]}

    def create_card(self, lead_id: str, round_: int, payload: dict[str, Any]) -> int:
        return self._exec("INSERT INTO cards (lead_id, round, payload_json, status, created_at) VALUES (?, ?, ?, 'open', ?)",
                          (lead_id, round_, _dump(payload), _now()))

    def get_card(self, card_id: int) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM cards WHERE id = ?", (card_id,))
        return self._card(rows[0]) if rows else None

    def open_card_for(self, lead_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM cards WHERE lead_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1", (lead_id,))
        return self._card(rows[0]) if rows else None

    def list_open_cards(self) -> list[dict[str, Any]]:
        return [self._card(r) for r in self._rows("SELECT * FROM cards WHERE status = 'open' ORDER BY id")]

    def close_card(self, card_id: int, status: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("UPDATE cards SET status = ? WHERE id = ? AND status = 'open'", (status, card_id))
            return cursor.rowcount == 1

    def add_decision(self, card_id: int, lead_id: str, round_: int, choice: str, note: str,
                     scope: tuple[str, ...] = ()) -> None:
        self._exec("INSERT INTO decisions (card_id, lead_id, round, choice, note, scope_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (card_id, lead_id, round_, choice, note, _dump(list(scope)), _now()))

    def latest_decision(self, lead_id: str) -> UWDecision | None:
        rows = self._rows("SELECT choice, note, round, scope_json FROM decisions WHERE lead_id = ? ORDER BY id DESC LIMIT 1", (lead_id,))
        if not rows:
            return None
        return UWDecision(rows[0]["choice"], rows[0]["note"], rows[0]["round"], tuple(json.loads(rows[0]["scope_json"])))

    # inbound messages, quotes, events
    def add_message_in(self, lead_id: str, round_: int, body: str, parsed: dict[str, Any]) -> int:
        return self._exec("INSERT INTO messages_in (lead_id, round, body, parsed_json, created_at) VALUES (?, ?, ?, ?, ?)",
                          (lead_id, round_, body, _dump(parsed), _now()))

    def messages_for(self, lead_id: str) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM messages_in WHERE lead_id = ? ORDER BY id", (lead_id,))
        return [{"id": r["id"], "round": r["round"], "body": r["body"], "parsed": json.loads(r["parsed_json"]),
                 "created_at": r["created_at"]} for r in rows]

    def save_quote(self, lead_id: str, payload: dict[str, Any]) -> None:
        self._exec("INSERT OR REPLACE INTO quotes (lead_id, payload_json, created_at) VALUES (?, ?, ?)", (lead_id, _dump(payload), _now()))

    def get_quote(self, lead_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT payload_json FROM quotes WHERE lead_id = ?", (lead_id,))
        return json.loads(rows[0]["payload_json"]) if rows else None

    def add_event(self, lead_id: str, type_: str, payload: dict[str, Any]) -> None:
        self._exec("INSERT INTO events (lead_id, type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                   (lead_id, type_, _dump(payload), _now()))

    def events_for(self, lead_id: str) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM events WHERE lead_id = ? ORDER BY id", (lead_id,))
        return [{"type": r["type"], "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]} for r in rows]

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, database: Path):
        self.database = database
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    state TEXT NOT NULL,
                    current_stage TEXT,
                    config_json TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    source_image TEXT,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    process_pid INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stages (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    message TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    PRIMARY KEY (job_id, name)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_stages_job ON stages(job_id, position);
                """
            )
            # A service restart must never leave a job falsely marked as running.
            db.execute(
                "UPDATE jobs SET state='interrupted', error='Web service restarted during execution', "
                "process_pid=NULL, updated_at=? WHERE state IN ('running','queued')",
                (utc_now(),),
            )
            db.execute(
                "UPDATE stages SET state='pending', message='Interrupted; safe to resume', "
                "started_at=NULL WHERE state='running'"
            )

    def create_job(
        self,
        *,
        job_id: str | None = None,
        name: str,
        workflow: str,
        quality: str,
        config: dict[str, Any],
        output_dir: Path,
        source_image: Path | None,
        stages: list[str],
    ) -> dict[str, Any]:
        job_id = job_id or uuid.uuid4().hex[:12]
        now = utc_now()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO jobs(id,name,workflow,quality,state,config_json,output_dir,source_image,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    name,
                    workflow,
                    quality,
                    "created",
                    json.dumps(config, ensure_ascii=False),
                    str(output_dir),
                    str(source_image) if source_image else None,
                    now,
                    now,
                ),
            )
            db.executemany(
                "INSERT INTO stages(job_id,name,position,state) VALUES(?,?,?,?)",
                [(job_id, stage, position, "pending") for position, stage in enumerate(stages)],
            )
        return self.get_job(job_id)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        item["cancel_requested"] = bool(item["cancel_requested"])
        return item

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = self._decode(row)
            job["stages"] = [
                dict(stage)
                for stage in db.execute(
                    "SELECT name,position,state,message,started_at,finished_at FROM stages "
                    "WHERE job_id=? ORDER BY position",
                    (job_id,),
                ).fetchall()
            ]
            return job

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "state",
            "current_stage",
            "error",
            "cancel_requested",
            "process_pid",
            "source_image",
            "name",
            "quality",
            "workflow",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return self.get_job(job_id)
        values["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in values)
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE jobs SET {assignments} WHERE id=?",
                (*[int(v) if isinstance(v, bool) else v for v in values.values()], job_id),
            )
        return self.get_job(job_id)

    def update_config(self, job_id: str, config: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET config_json=?,updated_at=? WHERE id=?",
                (json.dumps(config, ensure_ascii=False), utc_now(), job_id),
            )
        return self.get_job(job_id)

    def update_stage(self, job_id: str, stage: str, state: str, message: str | None = None) -> None:
        now = utc_now()
        fields: dict[str, Any] = {"state": state, "message": message}
        if state == "running":
            fields["started_at"] = now
            fields["finished_at"] = None
        elif state in {"succeeded", "failed", "skipped", "cancelled"}:
            fields["finished_at"] = now
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE stages SET {assignments} WHERE job_id=? AND name=?",
                (*fields.values(), job_id, stage),
            )
            db.execute(
                "UPDATE jobs SET current_stage=?,updated_at=? WHERE id=?", (stage, now, job_id)
            )

    def reset_from_stage(self, job_id: str, stage_name: str) -> None:
        with self._lock, self._connect() as db:
            stage = db.execute(
                "SELECT position FROM stages WHERE job_id=? AND name=?", (job_id, stage_name)
            ).fetchone()
            if stage is None:
                raise KeyError(stage_name)
            db.execute(
                "UPDATE stages SET state='pending',message=NULL,started_at=NULL,finished_at=NULL "
                "WHERE job_id=? AND position>=?",
                (job_id, stage["position"]),
            )
            db.execute(
                "UPDATE jobs SET state='created',current_stage=NULL,error=NULL,cancel_requested=0,"
                "process_pid=NULL,updated_at=? WHERE id=?",
                (utc_now(), job_id),
            )

    def next_pending_stage(self, job_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT name FROM stages WHERE job_id=? AND state IN ('pending','waiting') "
                "ORDER BY position LIMIT 1",
                (job_id,),
            ).fetchone()
        return row["name"] if row else None

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        return self.update_job(job_id, cancel_requested=True)

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

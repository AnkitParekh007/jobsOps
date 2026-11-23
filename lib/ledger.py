#!/usr/bin/env python3
"""SQLite WAL event ledger for JobOps runs, artifacts, jobs, locks, and audit."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

# Allow `python3 lib/ledger.py` and `from ledger import …` under tests.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    content_hash,
    discovered_job_from_match,
    job_key_from_url,
    make_envelope,
    normalize_url,
    utc_now_iso,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "state" / "jobops.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  floor INTEGER,
  phase TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL,
  job_key TEXT,
  task_id TEXT,
  artifact_type TEXT NOT NULL,
  producer TEXT NOT NULL,
  status TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  blocking_reasons_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE (job_key, artifact_type, content_hash),
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS jobs (
  job_key TEXT PRIMARY KEY,
  canonical_url TEXT NOT NULL,
  organization TEXT,
  role TEXT,
  status TEXT NOT NULL,
  country TEXT,
  lane TEXT,
  first_seen_run_id TEXT,
  last_run_id TEXT,
  updated_at TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS task_attempts (
  task_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  detail_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS locks (
  lock_id TEXT PRIMARY KEY,
  resource TEXT NOT NULL UNIQUE,
  run_id TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  released_at TEXT,
  state TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  run_id TEXT,
  kind TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  job_key TEXT NOT NULL,
  session_id TEXT NOT NULL,
  artifact_fingerprint TEXT NOT NULL,
  document_path TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT,
  decided_by TEXT NOT NULL DEFAULT '',
  run_id TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS submission_reservations (
  reservation_id TEXT PRIMARY KEY,
  job_key TEXT NOT NULL,
  run_id TEXT NOT NULL,
  submit_date TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_key, submit_date)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(job_key);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_task_run ON task_attempts(run_id, stage);
CREATE INDEX IF NOT EXISTS idx_approvals_job ON approvals(job_key, status);
CREATE INDEX IF NOT EXISTS idx_approvals_user ON approvals(user_id, status);
CREATE INDEX IF NOT EXISTS idx_reservations_date ON submission_reservations(submit_date, state);
"""


def _now() -> str:
    return utc_now_iso()


class Ledger:
    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def audit(self, kind: str, *, run_id: Optional[str] = None, detail: Optional[Mapping[str, Any]] = None) -> None:
        self._conn.execute(
            "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
            (_now(), run_id, kind, json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def start_run(
        self,
        run_id: str,
        *,
        floor: int,
        phase: str = "context",
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO runs(run_id, started_at, status, floor, phase, meta_json)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                  status=excluded.status,
                  floor=excluded.floor,
                  phase=excluded.phase,
                  meta_json=excluded.meta_json
                """,
                (
                    run_id,
                    _now(),
                    "running",
                    floor,
                    phase,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            self._conn.execute(
                "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
                (_now(), run_id, "run_started", json.dumps({"floor": floor, "phase": phase})),
            )

    def set_phase(self, run_id: str, phase: str) -> None:
        self._conn.execute(
            "UPDATE runs SET phase=? WHERE run_id=?",
            (phase, run_id),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, status: str = "complete", meta: Optional[Mapping[str, Any]] = None) -> None:
        if meta:
            row = self._conn.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            existing = json.loads(row["meta_json"]) if row else {}
            existing.update(meta)
            meta_json = json.dumps(existing, ensure_ascii=False)
            self._conn.execute(
                "UPDATE runs SET finished_at=?, status=?, phase=?, meta_json=? WHERE run_id=?",
                (_now(), status, "complete", meta_json, run_id),
            )
        else:
            self._conn.execute(
                "UPDATE runs SET finished_at=?, status=?, phase=? WHERE run_id=?",
                (_now(), status, "complete", run_id),
            )
        self._conn.commit()
        self.audit("run_finished", run_id=run_id, detail={"status": status})

    def mark_task(
        self,
        task_id: str,
        run_id: str,
        stage: str,
        status: str,
        *,
        detail: Optional[Mapping[str, Any]] = None,
        finished: bool = False,
    ) -> None:
        now = _now()
        existing = self._conn.execute(
            "SELECT task_id FROM task_attempts WHERE task_id=?", (task_id,)
        ).fetchone()
        if existing:
            self._conn.execute(
                """
                UPDATE task_attempts
                SET status=?, finished_at=?, detail_json=?
                WHERE task_id=?
                """,
                (
                    status,
                    now if finished or status in {"complete", "skipped", "failed"} else None,
                    json.dumps(detail or {}, ensure_ascii=False),
                    task_id,
                ),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO task_attempts(task_id, run_id, stage, status, started_at, finished_at, detail_json)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    run_id,
                    stage,
                    status,
                    now,
                    now if finished or status in {"complete", "skipped", "failed"} else None,
                    json.dumps(detail or {}, ensure_ascii=False),
                ),
            )
        self._conn.commit()

    def is_task_complete(self, task_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM task_attempts WHERE task_id=?", (task_id,)
        ).fetchone()
        return bool(row and row["status"] == "complete")

    def completed_stages(self, run_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT stage FROM task_attempts WHERE run_id=? AND status='complete'",
            (run_id,),
        ).fetchall()
        return {r["stage"] for r in rows}

    def acquire_lock(self, resource: str, run_id: str, lock_id: Optional[str] = None) -> str:
        import uuid

        lid = lock_id or f"lock_{uuid.uuid4().hex}"
        row = self._conn.execute(
            "SELECT lock_id, run_id, state FROM locks WHERE resource=?",
            (resource,),
        ).fetchone()
        if row and row["state"] == "open" and row["run_id"] != run_id:
            raise RuntimeError(
                f"lock held by run {row['run_id']} for resource {resource}"
            )
        if row and row["state"] == "open" and row["run_id"] == run_id:
            return str(row["lock_id"])
        if row:
            self._conn.execute(
                """
                UPDATE locks SET lock_id=?, run_id=?, acquired_at=?, released_at=NULL, state='open'
                WHERE resource=?
                """,
                (lid, run_id, _now(), resource),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO locks(lock_id, resource, run_id, acquired_at, state)
                VALUES (?,?,?,?, 'open')
                """,
                (lid, resource, run_id, _now()),
            )
        self._conn.commit()
        self.audit("lock_acquired", run_id=run_id, detail={"resource": resource, "lock_id": lid})
        return lid

    def release_lock(self, resource: str, *, run_id: Optional[str] = None) -> None:
        self._conn.execute(
            """
            UPDATE locks SET released_at=?, state='released'
            WHERE resource=? AND state='open'
            """,
            (_now(), resource),
        )
        self._conn.commit()
        self.audit("lock_released", run_id=run_id, detail={"resource": resource})

    def _require_approval_authority(self, *, action: str) -> None:
        """Approval writes are orchestrator-only — never from untrusted agents."""
        from trust_boundary import (  # local import
            agent_role_from_env,
            is_untrusted_agent_role,
            require_orchestrator,
        )

        role = agent_role_from_env()
        if is_untrusted_agent_role(role):
            raise PermissionError(f"approval_write_forbidden_in_agent_role:{role}:{action}")
        require_orchestrator("record_approval" if action != "approve" else "approve")

    def record_approval(
        self,
        *,
        approval_id: str,
        user_id: str,
        job_key: str,
        session_id: str,
        artifact_fingerprint: str,
        document_path: str = "",
        status: str = "pending",
        decided_by: str = "",
        run_id: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
        require_authority: bool = True,
    ) -> str:
        """
        Durable approval bound to user, requisition, session, document.

        New rows default to ``pending``. Creating ``approved``/``revoked`` directly
        still requires orchestrator authority (prefer ApprovalController.approve).
        """
        if status not in {"pending", "approved", "revoked"}:
            raise ValueError(f"invalid approval status: {status}")
        if require_authority:
            self._require_approval_authority(
                action="approve" if status in {"approved", "revoked"} else "record"
            )
        now = _now()
        decided_at = now if status in {"approved", "revoked"} else None
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO approvals(
                  approval_id, user_id, job_key, session_id, artifact_fingerprint,
                  document_path, status, created_at, decided_at, decided_by, run_id, meta_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(approval_id) DO UPDATE SET
                  status=excluded.status,
                  decided_at=excluded.decided_at,
                  decided_by=excluded.decided_by,
                  meta_json=excluded.meta_json
                """,
                (
                    approval_id,
                    user_id,
                    job_key,
                    session_id,
                    artifact_fingerprint,
                    document_path or "",
                    status,
                    now,
                    decided_at,
                    decided_by,
                    run_id,
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            self._conn.execute(
                "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
                (
                    now,
                    run_id,
                    "approval_recorded",
                    json.dumps(
                        {
                            "approval_id": approval_id,
                            "user_id": user_id,
                            "job_key": job_key,
                            "session_id": session_id,
                            "artifact_fingerprint": artifact_fingerprint,
                            "status": status,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        return approval_id

    def decide_approval(
        self,
        *,
        approval_id: str,
        status: str,
        decided_by: str,
        meta: Optional[Mapping[str, Any]] = None,
        require_authority: bool = True,
    ) -> None:
        """Transition an existing approval (pending → approved/revoked)."""
        if status not in {"approved", "revoked"}:
            raise ValueError(f"invalid decision status: {status}")
        if require_authority:
            self._require_approval_authority(action="approve")
        row = self.get_approval(approval_id)
        if row is None:
            raise KeyError(f"approval_not_found:{approval_id}")
        now = _now()
        merged = dict(row.get("meta") or {})
        if meta:
            merged.update(meta)
        with self.transaction():
            self._conn.execute(
                """
                UPDATE approvals
                SET status=?, decided_at=?, decided_by=?, meta_json=?
                WHERE approval_id=?
                """,
                (status, now, decided_by, json.dumps(merged, ensure_ascii=False), approval_id),
            )
            self._conn.execute(
                "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
                (
                    now,
                    row.get("run_id"),
                    "approval_decided",
                    json.dumps(
                        {
                            "approval_id": approval_id,
                            "status": status,
                            "decided_by": decided_by,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

    def get_approval(self, approval_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "approval_id": row["approval_id"],
            "user_id": row["user_id"],
            "job_key": row["job_key"],
            "session_id": row["session_id"],
            "artifact_fingerprint": row["artifact_fingerprint"],
            "document_path": row["document_path"] or "",
            "status": row["status"],
            "created_at": row["created_at"],
            "decided_at": row["decided_at"],
            "decided_by": row["decided_by"] or "",
            "run_id": row["run_id"],
            "meta": json.loads(row["meta_json"] or "{}"),
        }

    def require_approved(
        self,
        approval_id: str,
        *,
        user_id: str,
        job_key: str,
        session_id: str,
        artifact_fingerprint: str,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        """Verify durable approval bindings; used by trusted evidence issuer."""
        row = self.get_approval(approval_id)
        if row is None:
            return False, "approval_not_found", None
        if row["status"] != "approved":
            return False, f"approval_not_approved:{row['status']}", row
        if row["user_id"] != user_id:
            return False, "approval_user_mismatch", row
        if row["job_key"] != job_key:
            return False, "approval_job_mismatch", row
        if row["session_id"] != session_id:
            return False, "approval_session_mismatch", row
        if row["artifact_fingerprint"] != artifact_fingerprint:
            return False, "approval_fingerprint_mismatch", row
        return True, "ok", row

    def count_submission_reservations(
        self,
        *,
        submit_date: str,
        states: tuple[str, ...] = ("reserved", "consumed"),
    ) -> int:
        placeholders = ",".join("?" for _ in states)
        row = self._conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM submission_reservations
            WHERE submit_date=? AND state IN ({placeholders})
            """,
            (submit_date, *states),
        ).fetchone()
        return int(row["n"] if row else 0)

    def reserve_submission_slot(
        self,
        *,
        reservation_id: str,
        job_key: str,
        run_id: str,
        submit_date: str,
        cap: int = 1,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Atomically reserve a daily submit slot across concurrent processes.

        Uses BEGIN IMMEDIATE so concurrent writers serialize on the SQLite lock.
        Returns (ok, reason, reservation_id).
        """
        from trust_boundary import require_orchestrator

        require_orchestrator("reserve_submit")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            existing = self._conn.execute(
                """
                SELECT reservation_id, state, run_id FROM submission_reservations
                WHERE job_key=? AND submit_date=?
                """,
                (job_key, submit_date),
            ).fetchone()
            if existing and existing["state"] in {"reserved", "consumed"}:
                if existing["run_id"] == run_id:
                    self._conn.commit()
                    return True, "already_reserved", str(existing["reservation_id"])
                self._conn.rollback()
                return False, "job_already_reserved", str(existing["reservation_id"])
            used = self._conn.execute(
                """
                SELECT COUNT(*) AS n FROM submission_reservations
                WHERE submit_date=? AND state IN ('reserved', 'consumed')
                """,
                (submit_date,),
            ).fetchone()
            if int(used["n"] if used else 0) >= cap:
                self._conn.rollback()
                return False, "daily_submit_cap_exhausted", None
            now = _now()
            if existing:
                self._conn.execute(
                    """
                    UPDATE submission_reservations
                    SET reservation_id=?, run_id=?, state='reserved', created_at=?
                    WHERE job_key=? AND submit_date=?
                    """,
                    (reservation_id, run_id, now, job_key, submit_date),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO submission_reservations(
                      reservation_id, job_key, run_id, submit_date, state, created_at
                    ) VALUES (?,?,?,?, 'reserved', ?)
                    """,
                    (reservation_id, job_key, run_id, submit_date, now),
                )
            self._conn.execute(
                "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
                (
                    now,
                    run_id,
                    "submission_reserved",
                    json.dumps(
                        {
                            "reservation_id": reservation_id,
                            "job_key": job_key,
                            "submit_date": submit_date,
                            "cap": cap,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            self._conn.commit()
            return True, "reserved", reservation_id
        except Exception:
            try:
                self._conn.rollback()
            except sqlite3.Error:
                pass
            raise

    def consume_submission_reservation(
        self, reservation_id: str, *, run_id: Optional[str] = None
    ) -> None:
        now = _now()
        with self.transaction():
            self._conn.execute(
                """
                UPDATE submission_reservations SET state='consumed'
                WHERE reservation_id=? AND state='reserved'
                """,
                (reservation_id,),
            )
            self._conn.execute(
                "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
                (
                    now,
                    run_id,
                    "submission_reservation_consumed",
                    json.dumps({"reservation_id": reservation_id}, ensure_ascii=False),
                ),
            )

    def release_submission_reservation(
        self, reservation_id: str, *, run_id: Optional[str] = None
    ) -> None:
        now = _now()
        with self.transaction():
            self._conn.execute(
                """
                UPDATE submission_reservations SET state='released'
                WHERE reservation_id=? AND state='reserved'
                """,
                (reservation_id,),
            )
            self._conn.execute(
                "INSERT INTO audit_events(created_at, run_id, kind, detail_json) VALUES (?,?,?,?)",
                (
                    now,
                    run_id,
                    "submission_reservation_released",
                    json.dumps({"reservation_id": reservation_id}, ensure_ascii=False),
                ),
            )

    def append_artifact(self, envelope: Mapping[str, Any]) -> bool:
        """Insert enveloped artifact. Returns False if idempotent duplicate."""
        payload = envelope.get("payload") or {}
        chash = content_hash(payload)
        job_key = envelope.get("job_key")
        try:
            with self.transaction():
                self._conn.execute(
                    """
                    INSERT INTO artifacts(
                      event_id, run_id, job_key, task_id, artifact_type, producer,
                      status, content_hash, created_at, payload_json,
                      evidence_refs_json, blocking_reasons_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        envelope["event_id"],
                        envelope["run_id"],
                        job_key,
                        envelope.get("task_id"),
                        envelope["artifact_type"],
                        envelope["producer"],
                        envelope.get("status") or "ok",
                        chash,
                        envelope.get("created_at") or _now(),
                        json.dumps(payload, ensure_ascii=False),
                        json.dumps(list(envelope.get("evidence_refs") or []), ensure_ascii=False),
                        json.dumps(list(envelope.get("blocking_reasons") or []), ensure_ascii=False),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def transition_job(
        self,
        job_key: str,
        *,
        canonical_url: str,
        status: str,
        run_id: str,
        organization: str = "",
        role: str = "",
        country: str = "",
        lane: Any = None,
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        now = _now()
        existing = self._conn.execute(
            "SELECT job_key, first_seen_run_id, meta_json FROM jobs WHERE job_key=?",
            (job_key,),
        ).fetchone()
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        if existing:
            prior_meta = json.loads(existing["meta_json"] or "{}")
            if meta:
                prior_meta.update(meta)
            self._conn.execute(
                """
                UPDATE jobs SET canonical_url=?, organization=?, role=?, status=?,
                  country=?, lane=?, last_run_id=?, updated_at=?, meta_json=?
                WHERE job_key=?
                """,
                (
                    normalize_url(canonical_url),
                    organization,
                    role,
                    status,
                    country,
                    str(lane) if lane is not None else "",
                    run_id,
                    now,
                    json.dumps(prior_meta, ensure_ascii=False),
                    job_key,
                ),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO jobs(
                  job_key, canonical_url, organization, role, status, country, lane,
                  first_seen_run_id, last_run_id, updated_at, meta_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_key,
                    normalize_url(canonical_url),
                    organization,
                    role,
                    status,
                    country,
                    str(lane) if lane is not None else "",
                    run_id,
                    run_id,
                    now,
                    meta_json,
                ),
            )
        self._conn.commit()

    def prior_job_keys(self) -> set[str]:
        rows = self._conn.execute("SELECT job_key FROM jobs").fetchall()
        return {r["job_key"] for r in rows}

    def ingest_shard_file(
        self,
        shard_path: Path,
        *,
        run_id: str,
        producer: str = "discovery-worker",
    ) -> dict[str, Any]:
        data = json.loads(Path(shard_path).read_text(encoding="utf-8"))
        shard_id = data.get("shard_id") or Path(shard_path).stem
        inserted = 0
        skipped = 0
        errors: list[str] = []
        for raw in data.get("matches") or []:
            if not isinstance(raw, dict):
                continue
            try:
                job = discovered_job_from_match(raw, shard_id=str(shard_id))
            except Exception as exc:  # noqa: BLE001
                # Phase 0 may still drop reason on merge; ingest best-effort.
                url = raw.get("canonical_url")
                if not isinstance(url, str) or not url.startswith("http"):
                    skipped += 1
                    continue
                reason = raw.get("reason") if isinstance(raw.get("reason"), str) else ""
                if not reason.strip():
                    errors.append(f"{url}: missing reason")
                    skipped += 1
                    continue
                try:
                    job = discovered_job_from_match(
                        {**raw, "reason": reason},
                        shard_id=str(shard_id),
                    )
                except Exception as exc2:  # noqa: BLE001
                    errors.append(f"{url}: {exc2}")
                    skipped += 1
                    continue
                _ = exc  # keep lint quiet
            env = make_envelope(
                run_id=run_id,
                producer=producer,
                artifact_type="discovered_job",
                payload=job,
                job_key=job["job_key"],
                task_id=f"{run_id}:worker:{shard_id}",
                evidence_refs=job.get("evidence_refs") or [],
                status=job.get("status") or "ok",
            )
            if self.append_artifact(env):
                inserted += 1
            else:
                skipped += 1
            self.transition_job(
                job["job_key"],
                canonical_url=job["canonical_url"],
                status=job["status"],
                run_id=run_id,
                organization=job.get("organization") or "",
                role=job.get("role") or "",
                country=job.get("country") or "",
                lane=job.get("lane"),
                meta={"shard_id": shard_id, "source": job.get("source")},
            )
        # Also store the raw shard artifact once.
        shard_env = make_envelope(
            run_id=run_id,
            producer=producer,
            artifact_type="worker_shard",
            payload={"shard_id": shard_id, "path": str(shard_path), "match_count": len(data.get("matches") or [])},
            task_id=f"{run_id}:worker:{shard_id}:shard",
            evidence_refs=[str(shard_path)],
        )
        self.append_artifact(shard_env)
        return {
            "shard_id": shard_id,
            "inserted": inserted,
            "skipped": skipped,
            "errors": errors[:20],
        }

    def ingest_handoff_state(
        self,
        state_path: Path,
        *,
        run_id: str,
        producer: str = "merge_shards",
    ) -> dict[str, Any]:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        matches = state.get("matches") or []
        inserted = 0
        for raw in matches:
            if not isinstance(raw, dict):
                continue
            url = raw.get("canonical_url")
            if not isinstance(url, str) or not url.startswith("http"):
                continue
            jk = raw.get("job_key") or job_key_from_url(url)
            reason = raw.get("reason") if isinstance(raw.get("reason"), str) else ""
            payload = {
                "job_key": jk,
                "canonical_url": normalize_url(url),
                "employer_or_ats_url": normalize_url(
                    raw.get("employer_or_ats_url") or url
                ),
                "organization": raw.get("organization") or "",
                "role": raw.get("role") or "",
                "status": raw.get("status") or "Needs review",
                "lane": raw.get("lane"),
                "country": raw.get("country") or "",
                "source": raw.get("source") or "",
                "reason": reason,
                "shard_id": raw.get("shard_id"),
                "evidence_refs": raw.get("evidence_refs")
                or [normalize_url(raw.get("employer_or_ats_url") or url)],
            }
            env = make_envelope(
                run_id=run_id,
                producer=producer,
                artifact_type="handoff_match",
                payload=payload,
                job_key=jk,
                task_id=f"{run_id}:merge",
                evidence_refs=payload["evidence_refs"],
                status=str(payload["status"]),
            )
            if self.append_artifact(env):
                inserted += 1
            self.transition_job(
                jk,
                canonical_url=payload["canonical_url"],
                status=str(payload["status"]),
                run_id=run_id,
                organization=payload["organization"],
                role=payload["role"],
                country=payload["country"],
                lane=payload["lane"],
            )

        summary_env = make_envelope(
            run_id=run_id,
            producer=producer,
            artifact_type="handoff_state",
            payload={
                "path": str(state_path),
                "cumulative_handoff_matches": state.get("cumulative_handoff_matches"),
                "floor": state.get("floor"),
                "floor_met": state.get("floor_met"),
                "eligible_count": state.get("eligible_count"),
                "phase": state.get("phase"),
            },
            task_id=f"{run_id}:merge:state",
            evidence_refs=[str(state_path)],
        )
        self.append_artifact(summary_env)
        return {
            "matches": len(matches),
            "inserted": inserted,
            "eligible_count": state.get("eligible_count"),
        }

    def job_key_exists(self, job_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM jobs WHERE job_key=? LIMIT 1", (job_key,)
        ).fetchone()
        return row is not None


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JobOps SQLite ledger helpers")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start-run")
    p_start.add_argument("--run-id", required=True)
    p_start.add_argument("--floor", type=int, required=True)

    p_phase = sub.add_parser("set-phase")
    p_phase.add_argument("--run-id", required=True)
    p_phase.add_argument("--phase", required=True)

    p_task = sub.add_parser("mark-task")
    p_task.add_argument("--run-id", required=True)
    p_task.add_argument("--task-id", required=True)
    p_task.add_argument("--stage", required=True)
    p_task.add_argument("--status", required=True)
    p_task.add_argument("--finished", action="store_true")

    p_lock = sub.add_parser("acquire-lock")
    p_lock.add_argument("--run-id", required=True)
    p_lock.add_argument("--resource", required=True)

    p_rel = sub.add_parser("release-lock")
    p_rel.add_argument("--run-id", required=True)
    p_rel.add_argument("--resource", required=True)

    p_shard = sub.add_parser("ingest-shards")
    p_shard.add_argument("--run-id", required=True)
    p_shard.add_argument("--shards-dir", required=True)

    p_merge = sub.add_parser("ingest-handoff")
    p_merge.add_argument("--run-id", required=True)
    p_merge.add_argument("--state", required=True)

    p_fin = sub.add_parser("finalize")
    p_fin.add_argument("--run-id", required=True)
    p_fin.add_argument("--status", default="complete")
    p_fin.add_argument("--validate-json", default="")
    p_fin.add_argument("--eligible-count", type=int, default=-1)

    p_done = sub.add_parser("stage-done")
    p_done.add_argument("--run-id", required=True)
    p_done.add_argument("--stage", required=True)

    args = ap.parse_args()
    led = Ledger(args.db)
    try:
        if args.cmd == "start-run":
            led.start_run(args.run_id, floor=args.floor)
            print(json.dumps({"ok": True, "run_id": args.run_id}))
        elif args.cmd == "set-phase":
            led.set_phase(args.run_id, args.phase)
            print(json.dumps({"ok": True, "phase": args.phase}))
        elif args.cmd == "mark-task":
            led.mark_task(
                args.task_id,
                args.run_id,
                args.stage,
                args.status,
                finished=args.finished or args.status == "complete",
            )
            print(json.dumps({"ok": True, "task_id": args.task_id, "status": args.status}))
        elif args.cmd == "acquire-lock":
            lid = led.acquire_lock(args.resource, args.run_id)
            print(json.dumps({"ok": True, "lock_id": lid}))
        elif args.cmd == "release-lock":
            led.release_lock(args.resource, run_id=args.run_id)
            print(json.dumps({"ok": True}))
        elif args.cmd == "ingest-shards":
            shards_dir = Path(args.shards_dir)
            results = []
            for path in sorted(shards_dir.glob("*.json")):
                results.append(led.ingest_shard_file(path, run_id=args.run_id))
            led.set_phase(args.run_id, "workers_ingested")
            print(json.dumps({"ok": True, "shards": results}, indent=2))
        elif args.cmd == "ingest-handoff":
            summary = led.ingest_handoff_state(Path(args.state), run_id=args.run_id)
            led.set_phase(args.run_id, "merged")
            print(json.dumps({"ok": True, **summary}, indent=2))
        elif args.cmd == "finalize":
            meta: dict[str, Any] = {}
            if args.validate_json:
                meta["validate"] = json.loads(Path(args.validate_json).read_text(encoding="utf-8"))
            if args.eligible_count >= 0:
                meta["eligible_count"] = args.eligible_count
            led.mark_task(
                f"{args.run_id}:ledger_finalize",
                args.run_id,
                "ledger_finalize",
                "complete",
                finished=True,
                detail=meta,
            )
            led.finish_run(args.run_id, status=args.status, meta=meta)
            # Release run-scoped lock if held.
            led.release_lock(f"run:{args.run_id}", run_id=args.run_id)
            print(json.dumps({"ok": True, "run_id": args.run_id, "status": args.status}))
        elif args.cmd == "stage-done":
            done = args.stage in led.completed_stages(args.run_id)
            print(json.dumps({"ok": True, "stage": args.stage, "complete": done}))
        else:
            return 2
    finally:
        led.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

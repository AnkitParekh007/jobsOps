#!/usr/bin/env python3
"""JobOps typed contracts: envelope + core payload helpers + schema validation."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "jsonschema is required for lib/contracts.py. "
        "Install with: python3 -m pip install --user jsonschema"
    ) from exc


SCHEMA_VERSION = "1.0.0"
POLICY_VERSION = "jobops-p1-2026-11"
CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"

_SCHEMA_CACHE: dict[str, Draft202012Validator] = {}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex
    return f"{prefix}{uid}" if prefix else uid


def content_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def job_key_from_url(url: str) -> str:
    return f"url:{normalize_url(url)}"


def load_schema(name: str) -> dict:
    path = CONTRACTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"schema missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_validator(schema_name: str) -> Draft202012Validator:
    if schema_name not in _SCHEMA_CACHE:
        schema = load_schema(schema_name)
        _SCHEMA_CACHE[schema_name] = Draft202012Validator(schema)
    return _SCHEMA_CACHE[schema_name]


class ContractError(ValueError):
    """Raised when a payload fails schema or provenance checks."""


def validate(instance: Mapping[str, Any], schema_name: str) -> None:
    validator = get_validator(schema_name)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        msgs = []
        for err in errors[:8]:
            path = ".".join(str(p) for p in err.path) or "<root>"
            msgs.append(f"{path}: {err.message}")
        raise ContractError("; ".join(msgs))


def validate_envelope(envelope: Mapping[str, Any]) -> None:
    validate(envelope, "envelope.schema.json")


def make_envelope(
    *,
    run_id: str,
    producer: str,
    artifact_type: str,
    payload: Mapping[str, Any],
    status: str = "ok",
    job_key: Optional[str] = None,
    task_id: Optional[str] = None,
    evidence_refs: Optional[Iterable[str]] = None,
    blocking_reasons: Optional[Iterable[str]] = None,
    retryable: bool = False,
    event_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    schema_version: str = SCHEMA_VERSION,
    policy_version: str = POLICY_VERSION,
    created_at: Optional[str] = None,
) -> dict[str, Any]:
    env = {
        "schema_version": schema_version,
        "event_id": event_id or new_id("evt_"),
        "run_id": run_id,
        "job_key": job_key,
        "task_id": task_id or new_id("task_"),
        "producer": producer,
        "artifact_type": artifact_type,
        "created_at": created_at or utc_now_iso(),
        "policy_version": policy_version,
        "trace_id": trace_id or new_id("tr_"),
        "status": status,
        "payload": dict(payload),
        "evidence_refs": list(evidence_refs or []),
        "blocking_reasons": list(blocking_reasons or []),
        "retryable": bool(retryable),
    }
    validate_envelope(env)
    return env


def discovered_job_from_match(
    raw: Mapping[str, Any],
    *,
    shard_id: Optional[str] = None,
) -> dict[str, Any]:
    """Normalize a worker match into a DiscoveredJob payload (Phase 1 contract)."""
    url = raw.get("canonical_url")
    if not isinstance(url, str) or not url.startswith("http"):
        raise ContractError("canonical_url must be an http(s) URL")
    status = raw.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ContractError("status must be a non-empty string")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ContractError("reason must be a non-empty string")
    employer = raw.get("employer_or_ats_url") or url
    if not isinstance(employer, str) or not employer.startswith("http"):
        raise ContractError("employer_or_ats_url must be an http(s) URL")

    canonical = normalize_url(url)
    refs = raw.get("evidence_refs")
    if isinstance(refs, list) and refs:
        evidence_refs = [str(r) for r in refs]
    else:
        evidence_refs = [normalize_url(employer)]

    job = {
        "job_key": raw.get("job_key") or job_key_from_url(canonical),
        "canonical_url": canonical,
        "employer_or_ats_url": normalize_url(employer),
        "organization": raw.get("organization") or "",
        "role": raw.get("role") or "",
        "status": status.strip(),
        "lane": raw.get("lane"),
        "country": raw.get("country") or "",
        "source": raw.get("source") or "",
        "reason": reason.strip(),
        "evidence_quote": raw.get("evidence_quote"),
        "evidence_refs": evidence_refs,
        "shard_id": shard_id or raw.get("shard_id"),
    }
    validate(job, "discovered-job.schema.json")
    return job


def make_eligibility_decision(
    *,
    job_key: str,
    canonical_url: str,
    decision: str,
    blocking_reasons: Optional[Iterable[str]] = None,
    evidence_refs: Optional[Iterable[str]] = None,
    sponsorship_evidence: Optional[str] = None,
    hard_miss: bool = False,
    policy_version: str = POLICY_VERSION,
    notes: str = "",
) -> dict[str, Any]:
    payload = {
        "job_key": job_key,
        "canonical_url": normalize_url(canonical_url),
        "decision": decision,
        "blocking_reasons": list(blocking_reasons or []),
        "evidence_refs": list(evidence_refs or [normalize_url(canonical_url)]),
        "sponsorship_evidence": sponsorship_evidence,
        "hard_miss": hard_miss,
        "policy_version": policy_version,
        "notes": notes,
    }
    validate(payload, "eligibility-decision.schema.json")
    return payload


def count_eligible(matches: Iterable[Mapping[str, Any]]) -> int:
    n = 0
    for m in matches:
        status = (m.get("status") or "").strip().lower()
        if status == "eligible":
            n += 1
    return n


def validate_handoff_state_contract(state: Mapping[str, Any]) -> None:
    validate(state, "handoff-state.schema.json")
    matches = state.get("matches") or []
    if int(state.get("cumulative_handoff_matches", -1)) != len(matches):
        raise ContractError("cumulative_handoff_matches must equal len(matches)")
    urls = [m.get("canonical_url") for m in matches if isinstance(m, dict)]
    if len(urls) != len(set(urls)):
        raise ContractError("matches contain duplicate canonical_url values")


def attach_eligible_count(state: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    matches = state.get("matches") or []
    if isinstance(matches, list):
        state["eligible_count"] = count_eligible(matches)
    return state


def main() -> int:
    """CLI: validate a JSON file against a named schema."""
    import argparse

    ap = argparse.ArgumentParser(description="Validate JobOps contract JSON")
    ap.add_argument("schema", help="schema file name under contracts/")
    ap.add_argument("path", help="JSON file to validate")
    args = ap.parse_args()
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    try:
        validate(data, args.schema)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, "schema": args.schema}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

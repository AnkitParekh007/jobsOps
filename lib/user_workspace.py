#!/usr/bin/env python3
"""User/system data ownership — private workspace isolation (JOBOPS_HOME)."""
from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
ROOT = _LIB.parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import POLICY_VERSION  # noqa: E402

PROFILE_FILENAME = "candidate-profile.json"
FACTS_FILENAME = "verified-facts.md"
CONSENT_FILENAME = "consent.json"
SECRETS_DIRNAME = "secrets"
STATE_DIRNAME = "state"
BACKUPS_DIRNAME = "backups"
ARTIFACTS_DIRNAME = "artifacts"

# Public-repo safe defaults — never personal candidate facts.
DEFAULT_PREFERENCES: dict[str, Any] = {
    "country_priority": ["Remote"],
    "sponsorship_required_countries": [],
    "daily_submit_cap": 1,
    "handoff_floor": 40,
    "india_remote_only": False,
}

DEFAULT_CONSENT: dict[str, Any] = {
    "auto_submit_enabled": False,
    "outreach_send_enabled": False,
    "live_browser_submit_enabled": False,
    "acknowledged_policy_version": POLICY_VERSION,
}


@dataclass
class CandidateProfile:
    """Verified candidate facts loaded from the private user workspace only."""

    display_name: str = ""
    identity_markers: list[str] = field(default_factory=list)
    resume_urls: list[str] = field(default_factory=list)
    verified_facts: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PREFERENCES))
    portal_accounts: dict[str, Any] = field(default_factory=dict)
    consent: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONSENT))
    source_path: Optional[str] = None
    loaded: bool = False
    missing_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "identity_markers": list(self.identity_markers),
            "resume_urls": list(self.resume_urls),
            "verified_facts": list(self.verified_facts),
            "preferences": dict(self.preferences),
            "portal_accounts": dict(self.portal_accounts),
            "consent": dict(self.consent),
            "source_path": self.source_path,
            "loaded": self.loaded,
            "missing_reasons": list(self.missing_reasons),
            "policy_version": POLICY_VERSION,
        }


def default_jobops_home() -> Path:
    """OS-appropriate private data root (outside the git checkout)."""
    override = os.environ.get("JOBOPS_HOME") or os.environ.get("JOBOPS_USER_WORKSPACE")
    if override:
        return Path(override).expanduser().resolve()
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return (home / "Library" / "Application Support" / "jobops").resolve()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return (Path(base) / "jobops").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg) / "jobops").resolve()
    return (home / ".local" / "share" / "jobops").resolve()


def workspace_paths(home: Optional[Path] = None) -> dict[str, Path]:
    root = Path(home) if home is not None else default_jobops_home()
    return {
        "home": root,
        "profile": root / PROFILE_FILENAME,
        "facts": root / FACTS_FILENAME,
        "consent": root / CONSENT_FILENAME,
        "secrets": root / SECRETS_DIRNAME,
        "state": root / STATE_DIRNAME,
        "backups": root / BACKUPS_DIRNAME,
        "artifacts": root / ARTIFACTS_DIRNAME,
        "db": root / STATE_DIRNAME / "jobops.db",
    }


def ensure_workspace(home: Optional[Path] = None) -> dict[str, Path]:
    paths = workspace_paths(home)
    for key in ("home", "secrets", "state", "backups", "artifacts"):
        paths[key].mkdir(parents=True, exist_ok=True)
    gitignore = paths["home"] / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
    return paths


def _merge_preferences(raw: Mapping[str, Any]) -> dict[str, Any]:
    prefs = dict(DEFAULT_PREFERENCES)
    for k, v in (raw or {}).items():
        prefs[k] = v
    # Cap semantics: never raise above 1 via profile alone without explicit policy bump.
    try:
        prefs["daily_submit_cap"] = min(1, max(1, int(prefs.get("daily_submit_cap") or 1)))
    except (TypeError, ValueError):
        prefs["daily_submit_cap"] = 1
    return prefs


def _merge_consent(raw: Mapping[str, Any]) -> dict[str, Any]:
    consent = dict(DEFAULT_CONSENT)
    for k, v in (raw or {}).items():
        consent[k] = v
    # Hard defaults: external side effects off unless explicitly true.
    for key in ("auto_submit_enabled", "outreach_send_enabled", "live_browser_submit_enabled"):
        consent[key] = bool(consent.get(key) is True)
    return consent


def _facts_from_markdown(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        elif s.startswith("* "):
            s = s[2:].strip()
        if s:
            lines.append(s)
    return lines[:100]


def load_candidate_profile(
    *,
    home: Optional[Path] = None,
    notes_path: Optional[Path] = None,
    allow_missing: bool = True,
) -> CandidateProfile:
    """
    Load verified candidate facts from the private workspace.

    Never fabricates personal biography. Missing profile → empty facts + missing_reasons.
    """
    paths = workspace_paths(home)
    profile = CandidateProfile(preferences=_merge_preferences({}), consent=_merge_consent({}))
    profile_path = paths["profile"]
    facts_path = Path(notes_path) if notes_path else paths["facts"]
    consent_path = paths["consent"]

    if not profile_path.is_file():
        profile.missing_reasons.append("candidate_profile_missing")
        if facts_path.is_file():
            profile.verified_facts = _facts_from_markdown(facts_path)
            profile.source_path = str(facts_path)
        if not allow_missing and not profile.verified_facts:
            raise FileNotFoundError(
                f"private candidate profile required at {profile_path}; run `jobops init`"
            )
        return profile

    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        profile.missing_reasons.append(f"candidate_profile_unreadable:{exc}")
        return profile

    if not isinstance(raw, dict):
        profile.missing_reasons.append("candidate_profile_invalid")
        return profile

    profile.loaded = True
    profile.source_path = str(profile_path)
    profile.display_name = str(raw.get("display_name") or "").strip()
    markers = raw.get("identity_markers") or []
    if isinstance(markers, list):
        profile.identity_markers = [str(m).strip().lower() for m in markers if str(m).strip()]
    if profile.display_name and not profile.identity_markers:
        profile.identity_markers = [p.lower() for p in profile.display_name.split() if p.strip()]
    urls = raw.get("resume_urls") or raw.get("source_urls") or []
    if isinstance(urls, list):
        profile.resume_urls = [str(u) for u in urls if isinstance(u, str) and u.startswith("http")]
    facts = raw.get("verified_facts") or raw.get("facts") or []
    if isinstance(facts, list):
        profile.verified_facts = [str(f).strip() for f in facts if str(f).strip()]
    if facts_path.is_file():
        extra = _facts_from_markdown(facts_path)
        for f in extra:
            if f not in profile.verified_facts:
                profile.verified_facts.append(f)
    profile.preferences = _merge_preferences(raw.get("preferences") or {})
    profile.portal_accounts = dict(raw.get("portal_accounts") or {})
    consent_raw = dict(raw.get("consent") or {})
    if consent_path.is_file():
        try:
            consent_raw.update(json.loads(consent_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            profile.missing_reasons.append("consent_unreadable")
    profile.consent = _merge_consent(consent_raw)

    if not profile.verified_facts:
        profile.missing_reasons.append("verified_facts_empty")
    if not profile.identity_markers:
        profile.missing_reasons.append("identity_markers_empty")
    return profile


def write_candidate_profile(
    profile: Mapping[str, Any],
    *,
    home: Optional[Path] = None,
) -> Path:
    paths = ensure_workspace(home)
    payload = {
        "display_name": str(profile.get("display_name") or ""),
        "identity_markers": list(profile.get("identity_markers") or []),
        "resume_urls": list(profile.get("resume_urls") or []),
        "verified_facts": list(profile.get("verified_facts") or []),
        "preferences": _merge_preferences(profile.get("preferences") or {}),
        "portal_accounts": dict(profile.get("portal_accounts") or {}),
        "consent": _merge_consent(profile.get("consent") or {}),
        "policy_version": POLICY_VERSION,
    }
    path = paths["profile"]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    consent_path = paths["consent"]
    consent_path.write_text(json.dumps(payload["consent"], indent=2) + "\n", encoding="utf-8")
    return path


def identity_markers_present(extracted_text: str, markers: Sequence[str]) -> bool:
    """True when all configured identity markers appear in PDF extract (case-insensitive)."""
    lowered = (extracted_text or "").lower()
    cleaned = [m.strip().lower() for m in markers if m and str(m).strip()]
    if not cleaned:
        return False
    return all(m in lowered for m in cleaned)


def workspace_status(home: Optional[Path] = None) -> dict[str, Any]:
    paths = workspace_paths(home)
    profile = load_candidate_profile(home=home, allow_missing=True)
    return {
        "jobops_home": str(paths["home"]),
        "profile_exists": paths["profile"].is_file(),
        "facts_exists": paths["facts"].is_file(),
        "consent_exists": paths["consent"].is_file(),
        "db_path": str(paths["db"]),
        "profile_loaded": profile.loaded,
        "fact_count": len(profile.verified_facts),
        "missing_reasons": profile.missing_reasons,
        "auto_submit_enabled": bool(profile.consent.get("auto_submit_enabled")),
        "outreach_send_enabled": bool(profile.consent.get("outreach_send_enabled")),
        "system_layer_root": str(ROOT),
        "isolation_ok": str(paths["home"].resolve()) != str(ROOT.resolve()),
    }

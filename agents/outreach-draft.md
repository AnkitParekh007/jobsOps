# Outreach drafts (F06) — draft-only

You prepare **outreach drafts** for the strongest eligible / shortlisted roles. You do **not** send email.

## Hard rules

1. **No auto-send.** Ever. Status stays `draft` until a human sends (or explicitly records sent).
2. **Approval required** before any future send capability. Default is drafts-only indefinitely.
3. **Verified public contacts only** (O01). No inventing emails or LinkedIn handles.
4. **Genuine referrals only** (O02) with recorded consent.
5. At most **10** draft outreach notes per run.
6. One follow-up draft may be prepared after **5–7 business days** with no reply (O04). Suppress on `declined` / `opted_out`.

## Capabilities

| Cap | Behavior |
|---|---|
| O01 Contact Researcher | Public verified contacts only; else record the gap |
| O02 Referral Mapper | Prior connections with consent only |
| O03 Outreach Writer | Personalized drafts → ledger + Drive role folder |
| O04 Follow-up Planner | Timed draft queue; human sends |

## Steps

1. Read `ranked-shortlist.json` / ready roles and any prior outreach artifacts.
2. For each candidate (≤10): confirm a verified public contact. If missing → gap row, skip draft.
3. Write drafts via harness helper or structured JSON conforming to `outreach-draft.schema.json`:
   - `status`: `draft`
   - `auto_send`: `false`
   - `approval_required`: `true`
4. Store draft text under the org/role Drive folder (`lib/drive_artifacts.py` paths).
5. Do **not** open Gmail compose to send. Do **not** mark `sent` unless the user already sent it.

## Output

- `runs/<run_id>/outreach-drafts.json` (list of OutreachDraft payloads)
- Ledger artifacts `outreach_draft` when the harness invokes `lib/outreach_drafts.py`
- Gaps recorded when contact cannot be verified

## Forbidden

- Auto-send / SMTP / Gmail send
- Invented contacts
- Raising status to `sent` without user evidence
- Running as a concurrent LLM frontier alongside discovery (event-triggered / post-rank only)

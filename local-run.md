# Local run

Provider-neutral local harness. Chrome/browser is only needed if controlled submit is explicitly enabled.

## Fast multi-agent discovery

`./run` (or `jobops run`) dispatches **HTTP-only** lane×country workers **in parallel** (target **15** matches each), merges shards, then runs a **frontier** agent via `lib/agent_runtime.py`.

- Workers: no browser/Playwright; WebFetch/curl only; write `runs/<run_id>/shards/*.json`
- Default discovery floor: **40** (`HANDOFF_FLOOR` to override)
- Runtime: `JOBOPS_RUNTIME=auto|cursor|claude_code|codex|antigravity|deterministic`
- Frontier: report + at most one submit when explicitly authorized; HTTP expand only if floor unmet
- Failed/timed-out workers → `exhausted: false`

Submit at most one application per day, and only when policy + consent + env gates allow. Do not relax gates to spend the floor.

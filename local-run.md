# Local Mac run

This run is on Ankit Parekh’s Mac. Chrome is only needed if the frontier submits.

## Fast multi-agent discovery

`./run` dispatches **HTTP-only** lane×country workers **in parallel** (target **15** matches each), merges shards, then runs a **frontier** agent.

- Workers: no browser/Playwright; WebFetch/curl only; write `runs/<run_id>/shards/*.json`
- Default discovery floor: **40** (`HANDOFF_FLOOR` to override)
- Frontier: report + at most one submit; HTTP expand only if floor unmet

Submit at most one application. Do not relax gates to spend the floor.

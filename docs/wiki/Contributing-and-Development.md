# Contributing / Development

Start with [CONTRIBUTING.md](../../CONTRIBUTING.md) and [AGENTS.md](../../AGENTS.md).

## Development loop

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
jobops doctor
jobops run --workflow discovery --preview
```

## Expectations

1. Prefer deterministic components; call LLMs only for ambiguous extraction, explanations, tailored writing, or authorized research.
2. Every task needs owner, I/O, idempotency key, evaluation gate, retry policy, durable state.
3. Tests should cover crash/retry/idempotency, malicious posting content, sponsorship uncertainty, identity mismatch, duplicate requisitions, and post-click network failure.
4. Never commit real resumes, tokens, cookies, or another person's private details.
5. Do not represent screenshot-only or placeholder logic as production integration.
6. Do not self-merge release or production-readiness claims.

## PR checklist (short)

- [ ] Problem, scope, linked issue / phase
- [ ] Contract / permission / migration impact noted
- [ ] Deterministic + negative tests
- [ ] Commands actually run + CI
- [ ] Residual risks listed; external actions remain gated off by default

## Code of conduct / support

- [CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md)
- [SUPPORT.md](../../SUPPORT.md)
- [SECURITY.md](../../SECURITY.md)

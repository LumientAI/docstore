# Contributing

Thanks for considering a contribution. This is a small project; the goal is to
keep it small. Most contributions should fit one of: a bug fix with a
regression test, a new operator/format the existing primitives support, or
documentation that captures a non-obvious decision.

For larger changes (new commands, new agent types, new file formats), please
open an issue first to confirm fit before writing code.

## Development setup

```bash
git clone https://github.com/LumientAI/docstore
cd docstore
uv sync --all-extras       # installs runtime + dev deps from uv.lock
cp .env.example .env       # then add ANTHROPIC_API_KEY
```

Verify your environment:

```bash
uv run pytest              # 46 tests, no LLM calls
uv run ruff check .        # lint
docstore --help            # CLI is on PATH
```

## Workflow

1. Branch from `master`: `git checkout -b feature/<short-name>` or `fix/<short-name>`.
2. Write the change and at least one test that would have failed before it.
3. Run `uv run pytest` and `uv run ruff check .` locally. Both must be green
   before opening a PR — CI runs the same commands across
   `{ubuntu, macos} × {3.11, 3.12, 3.13}` and will block merge otherwise.
4. Open a PR with a clear description of what changed and why. Reference the
   issue if there is one.
5. Keep commits focused. One commit per logical change is preferred. Squash on
   merge if you ended up with fixup commits during review.

## Conventions

- **Read [AGENTS.md](AGENTS.md) first** — it documents the load-bearing
  invariants (cache key shape, `schema_fields` persistence, validator opt-in,
  `temperature=0` ordering). Breaking these silently breaks features.
- **No comments for what code does** — names should carry that. Comments are
  for *why* something non-obvious is the way it is.
- **Tests live in `tests/`.** Store-, schema-, and parser-layer tests don't
  call the LLM. Tests that require a live API key should be marked clearly
  (no convention yet — propose one if you need it).
- **Match existing patterns**: new CLI commands take `--store` and use the
  `_resolve_store_for_path` helper if they accept a path argument.
- **Don't add backwards-compat shims** for changes within this repo. If you
  rename a field or change a key, update everything that reads it in the same
  PR.

## Reporting bugs

Open an issue at https://github.com/LumientAI/docstore/issues with:

- The command you ran and the full output (including the traceback if any).
- Your Python version (`python --version`) and OS.
- A minimal reproducer if you can — even a tiny `.txt` invoice that triggers
  the bug helps.

For bugs in the extracted data quality (the LLM got a field wrong), include
the source document and the cached JSON from `.docstore/`.

## Releasing

Versioning is via [setuptools-scm](https://github.com/pypa/setuptools-scm)
reading git tags. To cut a release:

```bash
git tag v0.2.0
git push origin v0.2.0
# CI/CD picks up the tag, builds, publishes.
```

Update [CHANGELOG.md](CHANGELOG.md): move the `[Unreleased]` section under a new dated heading before tagging.

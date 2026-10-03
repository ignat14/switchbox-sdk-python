# AGENTS.md

## Scope

This repository contains the zero-runtime-dependency `switchbox-flags` SDK and the separately packaged OpenFeature adapter in `providers/openfeature/`. Support Python 3.10 and newer; CI exercises 3.10, 3.11, 3.12, and 3.14.

## Setup and checks

Run commands from the repository root unless noted otherwise.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip install -e providers/openfeature
ruff check .
python -m pytest -v --cov=switchbox --cov-report=term-missing --cov-fail-under=80
python -m pytest providers/openfeature/tests -q
```

Format changed Python files with `ruff format <paths>` and check them with `ruff format --check <paths>`. CI currently runs `ruff check .`, not a whole-tree formatter check, so avoid unrelated formatting churn.

Build the distributions with:

```sh
python -m pip install build
python -m build
(cd providers/openfeature && python -m build)
```

Before handing off a change, run the checks relevant to it; evaluator, model, fixture, client, or provider changes require both test suites and the linter.

## Core invariants

- Keep the core `switchbox-flags` package dependency-free at runtime. Code under `switchbox/` must use the Python standard library. Development tools belong in the dev dependency declarations in `pyproject.toml`. The OpenFeature provider is a separate distribution and may depend on `switchbox-flags` and `openfeature-sdk`.
- Keep `switchbox/evaluator.py` deterministic and side-effect-free: no network or file I/O, clocks, randomness, shared mutable state, telemetry, or callbacks. Evaluation must remain local, preserve the documented order and fail-safe defaults, and contain malformed-input errors rather than raising.
- Preserve cross-SDK behavior: JavaScript-style coercion, rule grouping and ordering, strict result types, and `sha256(user_id:flag_key) % 100` rollout bucketing are compatibility contracts. Exercise the real `FlagConfig.from_dict` parse path when testing evaluation changes.
- Keep `providers/openfeature/switchbox_openfeature/provider.py` as a translation layer. It must delegate all evaluation to `Switchbox`, while retaining context, lifecycle, missing-flag, and type-error mappings.
- Preserve thread safety. `FlagCache` and `TelemetryAggregator` protect shared state with locks; draining telemetry must stay atomic. Polling and telemetry workers must stop cleanly, failures and user callbacks must not break evaluation, and worker-owned state must not become cross-thread state without synchronization. Add concurrency coverage for new shared mutable state.

## Fixtures and tests

- `tests/fixtures/cdn-json/` and `tests/fixtures/parity/parity_vectors.json` are synchronized cross-SDK contract copies. Do not hand-edit them in isolation. Coordinate contract changes with the corresponding public JavaScript SDK copies; CI checks these copies for drift.
- `tests/fixtures/telemetry/value_reprs.json` likewise pins telemetry representation across the Python and JavaScript SDKs. Keep both implementations and their tests aligned when it changes.
- This repository does not contain the fixture synchronization script referenced by historical test comments. Do not add a repository-local sync command to instructions unless the script is added here.
- Keep tests offline and deterministic. Mock both config-fetch and telemetry HTTP calls, and close clients or use their context manager so background threads do not leak.

## Release-sensitive files

- `pyproject.toml` is the source of the core package version and dependency metadata. `switchbox/_version.py` reads installed distribution metadata; do not hard-code a second version there. Keep `uv.lock` synchronized with metadata changes.
- `providers/openfeature/pyproject.toml` versions the provider independently and controls its bounded core and OpenFeature compatibility ranges.
- `.github/workflows/publish.yml` publishes core tags matching `v*.*.*`; `.github/workflows/publish-openfeature.yml` publishes provider tags matching `openfeature-v*.*.*`. Both release paths build on Python 3.14, and the core release path runs lint and tests first.
- Update `README.md` and `providers/openfeature/README.md` when public behavior, install requirements, defaults, or examples change.

---
phase: 01-foundation-ingest
plan: 01
subsystem: infra
tags: [docker-compose, fastapi, postgres, pgvector, searxng, firecrawl, telegram]
requires: []
provides:
  - Docker Compose topology for Postgres, API, bot, SearXNG, and Firecrawl services
  - Python dependency pins for Phase 1 backend and bot services
  - API and bot Dockerfiles with separate service entrypoints
  - Environment template and ignore rules that keep local secrets out of git
  - Initial app, bot, migration, and SearXNG directory scaffold
affects: [phase-01-foundation-ingest, infra, ingest, bot, grounding]
tech-stack:
  added: [FastAPI, SQLAlchemy, asyncpg, pgvector, python-telegram-bot, APScheduler, OpenAI SDK, httpx, Pillow, Docker Compose]
  patterns: [single-worker API container, separate bot service, env-substituted secrets, internal grounding services]
key-files:
  created: [.gitignore, .dockerignore, .env.example, requirements.txt, Dockerfile.api, Dockerfile.bot, docker-compose.yml, searxng/settings.yml]
  modified: []
key-decisions:
  - "API host port is bound to 127.0.0.1:8000 to avoid exposing the ingest surface beyond localhost/Tailscale routing."
  - "Firecrawl is included as internal Compose services with API, worker, Redis, and Playwright sidecars; no Firecrawl host port is exposed."
patterns-established:
  - "Runtime secrets are referenced via environment substitution and kept out of committed Compose files."
  - "API and bot containers share the same Python dependency file but use separate Dockerfiles and commands."
requirements-completed: [INFRA-01, INFRA-03, INFRA-05]
duration: 8min
completed: 2026-05-26
---

# Phase 01 Plan 01: Docker Infrastructure Stack Summary

**Docker Compose scaffold for the FastAPI API, Telegram bot, Postgres+pgvector, SearXNG, and Firecrawl grounding services with local-only API binding and secret-safe env templates.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-26T10:08:10Z
- **Completed:** 2026-05-26T10:16:16Z
- **Tasks:** 8
- **Files modified:** 15

## Accomplishments

- Created the project skeleton for `app/`, `bot/`, and Alembic migrations.
- Added pinned Python dependencies and container images for the API and bot services.
- Added a single `docker-compose.yml` with Postgres+pgvector, API, bot, SearXNG, and internal Firecrawl services.
- Added `.env.example`, `.gitignore`, and `.dockerignore` so real `.env` contents remain local only.

## Task Commits

1. **Task 1: Create directory skeleton** - `20f4eec` (feat)
2. **Task 2: Create requirements.txt** - `8c18892` (chore)
3. **Task 3: Create .gitignore and .dockerignore** - `251c8ef` (chore)
4. **Task 4: Create .env.example** - `775327a` (chore)
5. **Task 5: Create Dockerfile.api** - `82a738f` (feat)
6. **Task 6: Create Dockerfile.bot** - `68306a8` (feat)
7. **Task 7: Create docker-compose.yml** - `52c9942` (feat)
8. **Task 8: Create SearXNG settings.yml** - `2d1ea37` (feat)

## Files Created/Modified

- `.gitignore` - Excludes local secrets, caches, uploads, virtualenvs, and generated Python files.
- `.dockerignore` - Keeps local git/planning/dev artifacts and secrets out of Docker build context.
- `.env.example` - Documents required placeholder env vars without real secrets.
- `requirements.txt` - Pins 19 Python runtime dependencies.
- `Dockerfile.api` - Builds API container, installs curl, runs Alembic, then starts Uvicorn with one worker.
- `Dockerfile.bot` - Builds bot container and runs `python -m bot.main`.
- `docker-compose.yml` - Defines Postgres, API, bot, SearXNG, Firecrawl API/worker/Redis/Playwright, and named volumes.
- `searxng/settings.yml` - Enables SearXNG JSON output for grounding.
- `app/**/__init__.py`, `bot/__init__.py` - Establish Python package layout.
- `migrations/versions/.gitkeep` - Keeps the empty Alembic versions directory in git.

## Verification

- `docker compose config` exited `0`.
- `find app bot migrations -name "__init__.py" | sort` listed all expected package markers.
- `requirements.txt` has 19 lines and includes all required package pins.
- `.env.example` has 6 placeholder variables.
- `Dockerfile.api` contains `--workers 1`.
- `Dockerfile.bot` contains `python -m bot.main`.
- `git ls-files .env --error-unmatch` confirmed `.env` is not tracked.

## Decisions Made

- Used Firecrawl's current `ghcr.io/firecrawl/firecrawl:latest` and `ghcr.io/firecrawl/playwright-service:latest` images for the internal Firecrawl service set.
- Kept Firecrawl and SearXNG internal-only; only the API maps a host port, and it is bound to `127.0.0.1`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Tracked empty Alembic versions directory**
- **Found during:** Task 1 (Create directory skeleton)
- **Issue:** Git does not track empty directories, so `migrations/versions/` would disappear after checkout despite being part of the required scaffold.
- **Fix:** Added `migrations/versions/.gitkeep`.
- **Files modified:** `migrations/versions/.gitkeep`
- **Verification:** `test -d migrations/versions` passed after commit.
- **Committed in:** `20f4eec`

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** The deviation preserves the intended scaffold without adding runtime scope.

## Issues Encountered

- An initial `requirements.txt` patch landed in the primary checkout instead of the isolated worktree. It was removed immediately before commit; primary checkout status returned to only the pre-existing `.env` and `sample_images/` untracked files.

## Known Stubs

None from the stub scan. The API and bot Python entrypoints referenced by the Dockerfiles are intentionally created by later Phase 1 plans.

## Authentication Gates

None.

## Next Phase Readiness

- The infra scaffold is ready for the schema/model and FastAPI entrypoint plans.
- Compose parsing works now; full container startup still depends on later plans adding `app.main`, `bot.main`, and Alembic configuration.

## Self-Check: PASSED

- Verified all created scaffold and summary files exist.
- Verified all eight task commits are present in git history.
- Re-ran `docker compose config` successfully.

---
*Phase: 01-foundation-ingest*
*Completed: 2026-05-26*

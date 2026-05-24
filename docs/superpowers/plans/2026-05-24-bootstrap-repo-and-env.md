# Bootstrap Repo And Env Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize this directory as a publishable public GitHub repo named `AutoMeal`, add safe ignore rules, and bootstrap local env files with a strong API secret.

**Architecture:** Keep bootstrap artifacts minimal and explicit. Git metadata and GitHub remote are created first, then local-only secret handling is separated from committed example config via `.gitignore` and `.env.example`.

**Tech Stack:** `git`, GitHub CLI (`gh`), shell utilities, markdown docs

---

### Task 1: Create Safe Repo Metadata

**Files:**
- Create: `.gitignore`
- Modify: `.env` (local only, gitignored)
- Test: local shell checks

- [ ] **Step 1: Write the ignore rules**

```gitignore
.DS_Store
.env
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/
uploads/
*.pyc
```

- [ ] **Step 2: Verify the repo does not already contain conflicting tracked secret files**

Run: `git status --short`
Expected: either `fatal: not a git repository` before init, or a clean list of untracked project files

- [ ] **Step 3: Generate a strong API secret for local development**

```bash
openssl rand -hex 32
```

- [ ] **Step 4: Write `.env` with placeholders and the generated secret**

```dotenv
DATABASE_URL=postgresql+asyncpg://mealtracker:mealtracker@postgres:5432/mealtracker
MEALTRACKER_API_SECRET=<generated secret>
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
UPLOAD_DIR=./uploads
APP_TIMEZONE=Asia/Dubai
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
SEARXNG_BASE_URL=
FIRECRAWL_BASE_URL=
```

- [ ] **Step 5: Run local checks**

Run: `test -f .gitignore && test -f .env`
Expected: command exits successfully

### Task 2: Publish GitHub Repository

**Files:**
- Modify: `.git/`
- Test: local shell checks and GitHub CLI output

- [ ] **Step 1: Initialize git in the project root**

```bash
git init
git branch -M main
```

- [ ] **Step 2: Create the public repository with GitHub CLI**

```bash
gh repo create AutoMeal --public --source=. --remote=origin
```

- [ ] **Step 3: Verify the remote**

Run: `git remote -v`
Expected: `origin` points to `github.com:masterbatcoderman10/AutoMeal.git` for fetch and push

- [ ] **Step 4: Verify the GitHub repo is reachable**

Run: `gh repo view masterbatcoderman10/AutoMeal --json name,visibility,url`
Expected: JSON shows `AutoMeal`, `PUBLIC`, and the repo URL

### Task 3: Commit Safe Bootstrap Artifacts

**Files:**
- Create: `.env.example`
- Modify: `docs/superpowers/specs/2026-05-24-phase-1-vertical-slice-design.md`
- Test: `git status`, `git check-ignore`

- [ ] **Step 1: Write `.env.example` without real secrets**

```dotenv
DATABASE_URL=postgresql+asyncpg://mealtracker:mealtracker@postgres:5432/mealtracker
MEALTRACKER_API_SECRET=replace-me
TELEGRAM_BOT_TOKEN=replace-me
TELEGRAM_CHAT_ID=replace-me
UPLOAD_DIR=./uploads
APP_TIMEZONE=Asia/Dubai
OPENROUTER_API_KEY=replace-me
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
SEARXNG_BASE_URL=
FIRECRAWL_BASE_URL=
```

- [ ] **Step 2: Verify `.env` is ignored and `.env.example` is trackable**

Run: `git check-ignore -v .env && git check-ignore .env.example || true`
Expected: `.env` matches `.gitignore`; `.env.example` is not ignored

- [ ] **Step 3: Record the plan/spec docs and safe bootstrap files in git**

```bash
git add .gitignore .env.example docs/superpowers/specs/2026-05-24-phase-1-vertical-slice-design.md docs/superpowers/plans/2026-05-24-bootstrap-repo-and-env.md AGENTS.md CLAUDE.md PROJECT.md
```

- [ ] **Step 4: Commit the bootstrap setup**

```bash
git commit -m "chore: initialize public repo bootstrap"
```

- [ ] **Step 5: Verify working tree state**

Run: `git status --short`
Expected: `.env` remains untracked/ignored; tracked files are committed

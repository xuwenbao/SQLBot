# AGENTS.md

## Cursor Cloud specific instructions

### Architecture Overview

SQLBot is an AI-powered ChatBI system with four components:

| Service | Tech | Port | Start Command |
|---------|------|------|---------------|
| Backend API | Python 3.11 / FastAPI | 8000 | `cd backend && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload` |
| MCP Server | Python 3.11 / FastAPI | 8001 | `cd backend && .venv/bin/uvicorn main:mcp_app --host 0.0.0.0 --port 8001` |
| Frontend | Vue 3 / Vite / TypeScript | 5173 | `cd frontend && npx vite --host 0.0.0.0` |
| G2-SSR | Node.js 18 / AntV G2 | 3000 | `cd g2-ssr && node app.js` |
| PostgreSQL | PostgreSQL 16 + pgvector | 5432 | `sudo pg_ctlcluster 16 main start` |

### Important Gotchas

- **Torch CPU version**: The `pyproject.toml` has both `cpu` and `cu128` extras for torch. Always use `uv sync --extra cpu` to install the CPU version. Using plain `uv run` may re-sync and install the CUDA version, which fails without GPU drivers. Prefer using `.venv/bin/python` or `.venv/bin/uvicorn` directly instead of `uv run`.
- **Frontend `npm run dev` fails**: The `dev` script runs `vue-tsc -b && vite`, but the codebase has pre-existing TypeScript errors. Use `npx vite --host 0.0.0.0` directly to start the dev server.
- **Node.js version**: Use Node.js 18 (via nvm: `nvm use 18`). The g2-ssr `node-canvas` package requires native build libraries (`libcairo2-dev`, `libpango1.0-dev`, etc.).
- **Embedding model**: Set `EMBEDDING_ENABLED=False` and `TABLE_EMBEDDING_ENABLED=False` env vars when starting the backend to skip downloading the ~400MB embedding model. The app functions without it (embedding features will be disabled).
- **Default credentials**: Login as `admin` / `SQLBot@123456`.
- **PostgreSQL setup**: DB name `sqlbot`, user `root`, password `Password123@pg`. The pgvector extension must be installed.
- **Backend lint**: The lint script `scripts/lint.sh` targets `app` directory, but the actual directory is `apps`. Use `ruff check apps common main.py` instead.
- **No automated tests**: The repo has test infrastructure (`scripts/test.sh`) but no actual test files.

### Running Lint

- **Backend**: `cd backend && .venv/bin/ruff check apps common main.py`
- **Frontend**: `cd frontend && npx eslint . --ext .vue,.js,.ts,.jsx,.tsx`

### Running DB Migrations

```bash
cd backend && .venv/bin/alembic upgrade head
```

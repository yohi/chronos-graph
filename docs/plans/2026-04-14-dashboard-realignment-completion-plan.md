# Dashboard Realignment Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 1 and Phase 3 of the dashboard realignment spec by fixing configuration errors, ensuring tests pass, configuring frontend production builds, and setting up Docker Compose & E2E tests.

**Architecture:** 
- Config uses `local-model` by default and connects to PostgreSQL on port 5435 locally.
- Frontend uses Vite for building a production SPA, which the backend will serve via StaticFiles fallback.
- Docker Compose orchestrates the full stack including the new `chronos-dashboard` service.

**Tech Stack:** Python, FastAPI, React, Vite, Playwright, Docker

---

### Task 1: Fix Settings Validation and DB Connection

**Files:**
- Modify: `.env`

- [ ] **Step 1: Update .env configuration**

Replace `EMBEDDING_PROVIDER=openai` with `EMBEDDING_PROVIDER=local-model` and `POSTGRES_PORT=5432` with `POSTGRES_PORT=5435` in `.env`.

```bash
sed -i 's/EMBEDDING_PROVIDER=openai/EMBEDDING_PROVIDER=local-model/' .env
sed -i 's/POSTGRES_PORT=5432/POSTGRES_PORT=5435/' .env
```

- [ ] **Step 2: Run configuration tests**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS without validation errors.

- [ ] **Step 3: Run integration tests**

Ensure containers are running (`docker compose up -d postgres neo4j redis`).
Run: `pytest tests/integration/test_postgres_integration.py -v`
Expected: PASS without database connection errors.

- [ ] **Step 4: Commit**

```bash
git add .env
git commit -m "fix: update environment configuration for local testing"
```

---

### Task 2: Build Frontend for Production

**Files:**
- Modify: `frontend/package.json` (indirectly via install)
- Generate: `frontend/dist/*`

- [ ] **Step 1: Install frontend dependencies**

```bash
cd frontend && npm install && cd ..
```

- [ ] **Step 2: Build the frontend**

```bash
cd frontend && npm run build && cd ..
```

- [ ] **Step 3: Verify build output**

Run: `ls -la frontend/dist/index.html`
Expected: File exists and has a non-zero size.

- [ ] **Step 4: Commit**

Since `frontend/dist/` is ignored by git, we only need to commit any lockfile updates if there were any.

```bash
git add frontend/package-lock.json || true
git commit -m "chore: build frontend for production" || true
```

---

### Task 3: Add Dashboard Service to Docker Compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add chronos-dashboard service**

Append the following to the `services` block in `docker-compose.yml`:

```yaml
  chronos-dashboard:
    build:
      context: .
      dockerfile: .devcontainer/Dockerfile
    user: root
    volumes:
      - .:/workspaces/chronos-graph
    working_dir: /workspaces/chronos-graph
    command: ["python", "-m", "context_store.dashboard.api_server"]
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - NEO4J_URI=bolt://neo4j:7687
      - REDIS_URL=redis://redis:6379
      - DASHBOARD_HOST=0.0.0.0
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
```

- [ ] **Step 2: Verify docker compose format**

Run: `docker compose config -q`
Expected: Returns with exit code 0 (no errors).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add chronos-dashboard service to docker compose"
```

---

## Task 4: Introduce Playwright E2E Tests

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/dashboard.spec.ts`

- [ ] **Step 1: Install Playwright**

```bash
cd frontend
npm install -D @playwright/test
npx playwright install --with-deps chromium
cd ..
```

- [ ] **Step 2: Create Playwright Configuration**

Create `frontend/playwright.config.ts`:

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
```

- [ ] **Step 3: Create E2E Test**

Create `frontend/e2e/dashboard.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

test('dashboard loads and displays summary', async ({ page }) => {
  // Wait for the app to load
  await page.goto('/');
  
  // Verify main title is visible
  await expect(page.locator('text=System Overview')).toBeVisible();
  
  // Verify stats cards are present
  await expect(page.locator('text=Active Memories')).toBeVisible();
});
```

- [ ] **Step 4: Verify E2E Test execution (Failing without server)**

Run: `cd frontend && npx playwright test e2e/dashboard.spec.ts ; cd ..`
Expected: Fails because the server is not running yet.

- [ ] **Step 5: Run tests against the running server (Pass)**

Start the application:
```bash
docker compose up -d chronos-dashboard
# wait a few seconds for it to boot
sleep 5
```

Run: `cd frontend && npx playwright test e2e/dashboard.spec.ts ; cd ..`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/playwright.config.ts frontend/e2e/dashboard.spec.ts
git commit -m "test: add playwright E2E test for dashboard"
```

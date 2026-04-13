# Dashboard Realignment and Finalization Plan (2026-04-13)

**Goal:** 設計書（`2026-04-10-dashboard-web-ui-design.md`）と現在の実装の乖離を解消し、ダッシュボード機能をプロダクション品質で完成させる。

**Architecture:** 
- Frontend: Zustand + React Query + API Client 層の構築。
- Backend: FastAPI による SPA フォールバックルーティングの実装。
- Infrastructure: Docker Compose による統合環境の構築。

---

## Phase 1: 環境の修復と基盤整備

現在の実行を妨げている設定エラーおよび接続エラーを解消する。

### Task 1.1: Settings バリデーションエラーの修正
- **Files:** `.env` (または `.env.example`), `src/context_store/config.py`
- **Step 1:** `EMBEDDING_PROVIDER` の値を `local` から `local-model` に修正する。
- **Step 2:** `pytest tests/unit/test_config.py` でバリデーションが通ることを確認。

### Task 1.2: PostgreSQL 接続エラーの解消
- **Files:** `docker-compose.yml`, `tests/integration/conftest.py`
- **Step 1:** DB ユーザー `context_store` のパスワード設定が `.env` と一致しているか確認し、不一致を修正。
- **Step 2:** `pytest tests/integration/test_postgres_integration.py` を実行し、認証エラーが解消されたことを確認。

### Task 1.3: フロントエンド・ディレクトリ構造の作成
- **Files:** `frontend/src/` 配下
- **Step 1:** `src/api/`, `src/stores/`, `src/hooks/`, `src/types/` ディレクトリを作成する。

---

## Phase 2: フロントエンド・アーキテクチャの正規化

直接的な `fetch` を排し、設計通りの状態管理と API 通信を実装する。

### Task 2.1: API クライアントと Zustand ストアの実装
- **Files:** `frontend/src/api/client.ts`, `frontend/src/stores/statsStore.ts`, `frontend/src/stores/graphStore.ts`
- **Step 1:** 設計書 §5.2 に基づき、相対パス `/api` を使用する API クライアントを実装。
- **Step 2:** `DashboardStats` 等のスキーマに合わせた Zustand ストアを実装。

### Task 2.2: Dashboard および NetworkView の修正
- **Files:** `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/NetworkView.tsx`
- **Step 1:** `useState`/`useEffect` による直接 `fetch` を Zustand ストアの action 呼び出しに置き換える。
- **Step 2:** `/api/stats`（誤）を `/api/stats/summary`（正）に変更し、レスポンススキーマの不一致を解消。

---

## Phase 3: プロダクション機能の補完

デプロイおよび運用に必要な機能を実装する。

### Task 3.1: SPA フォールバックと静的配信の実装
- **Files:** `src/context_store/dashboard/api_server.py`
- **Step 1:** `StaticFiles` をマウントし、`/api/*` 以外の GET リクエストを `index.html` へ流す catch-all ルートを追加する。

### Task 3.2: Docker Compose へのサービス追加
- **Files:** `docker-compose.yml`
- **Step 1:** `chronos-dashboard` サービスを追加し、127.0.0.1:8000 でホスト外から遮断する設定を入れる。

### Task 3.3: Playwright E2E テストの導入
- **Files:** `frontend/e2e/dashboard.spec.ts`
- **Step 1:** 最小限のハッピーパス（ダッシュボード表示確認）を検証する E2E テストを追加。

---

## Phase 4: 最終検証 (Verification)

### Task 4.1: 全テストスイートの実行
- `pytest tests/`
- `npm run lint` (frontend)
- `tsc --noEmit` (frontend)

### Task 4.2: 手動動作確認
- ダッシュボード上での統計表示。
- Network View でのグラフ描画とノードクリック。
- リアルタイムログのストリーミング確認。

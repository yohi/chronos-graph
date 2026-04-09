# Chronos Graph Dashboard - Web UI 設計書

> **作成日**: 2026-04-10
> **ブランチ**: `feat/dashboard`
> **ステータス**: Approved

## 1. 概要

ChronosGraph は MCP ベースの AI エージェント向け長期記憶システムだが、現在は CLI/MCP プロトコル経由の操作のみ対応している。
本設計書は、記憶グラフの可視化、リアルタイムイベント監視、システム状態の把握を実現する Web UI ダッシュボードの設計を定義する。

### 1.1 確定した技術選定

| 項目 | 選定技術 | 理由 |
|------|----------|------|
| フロントエンド | React + TypeScript + Vite | 高速な開発体験、型安全性 |
| グラフ描画 | Cytoscape.js | ネットワークトポロジに最適化、レイアウトアルゴリズム内蔵 |
| 状態管理 | Zustand | 軽量、ボイラープレートが少ない、プロジェクト規模に最適 |
| スタイリング | Tailwind CSS | ユーティリティファースト、ダークモード対応容易 |
| バックエンド API | FastAPI | 既存 Orchestrator を直接ラップ、WebSocket 対応 |
| 監視対象 | サーバーリソース + 記憶データイベント | 両方組み合わせで最大限の可視性を提供 |
| 配置場所 | `dashboard/` (プロジェクトルート直下) | バックエンド (`src/`) と明確に分離 |

### 1.2 MoSCoW 優先度

| 優先度 | 機能 |
|--------|------|
| **Must Have** | インタラクティブノード・エッジグラフ、リアルタイムログストリーミング、システムリソース監視 |
| **Should Have** | グラフフィルタリング/検索、カスタマイズ可能なレイアウトアルゴリズム、ダーク/ライトモード |
| **Could Have** | 時系列データ再生、PDF/画像エクスポート |
| **Won't Have** | 統合 IDE 機能、重いサーバーサイド処理 |

---

## 2. アーキテクチャ

### 2.1 全体構成

```text
┌──────────────────┐     HTTP/WS      ┌────────────────────┐
│  React Frontend  │ <─────────────> │  FastAPI Bridge     │
│  (Vite + TS)     │  REST + WebSocket│  (api_server.py)    │
│  dashboard/      │                  │  src/.../dashboard/ │
└──────────────────┘                  └────────┬───────────┘
                                               │ Direct import
                                      ┌────────▼───────────┐
                                      │   Orchestrator      │
                                      │   (既存コード)       │
                                      └────────┬───────────┘
                                   ┌───────────┼───────────┐
                                SQLite/PG   Neo4j/SQLite  Redis/InMem
```

### 2.2 設計方針

- **FastAPI が Orchestrator を直接 import**: MCP プロトコルブリッジは不要。同一 Python プロセス内で Orchestrator のメソッドを呼び出す
- **独立プロセス**: ダッシュボードは `chronos-dashboard` コマンドで起動。既存 MCP サーバー (`context-store`) には影響なし
- **共有ストレージ**: 両プロセスとも同じ SQLite ファイル (WAL モード) または PostgreSQL/Neo4j に接続
- **認証**: MVP では省略。`127.0.0.1` にバインドしてローカルアクセスのみ許可

---

## 3. バックエンド API 設計

### 3.1 ディレクトリ構造

```text
src/context_store/dashboard/
    __init__.py
    api_server.py          # FastAPI app, lifespan, CORS, uvicorn main
    schemas.py             # Pydantic response models
    log_collector.py       # logging.Handler + ring buffer + asyncio.Queue
    system_monitor.py      # psutil ベースのリソース収集
    websocket_manager.py   # WebSocket 接続管理 + ブロードキャスト
    routes/
        __init__.py
        graph.py           # /api/graph/*
        memories.py        # /api/memories/*
        stats.py           # /api/stats/*
        system.py          # /api/system/*
        logs.py            # /api/logs/*
```

### 3.2 REST エンドポイント

| Method | Path | Description | Backend Source |
|--------|------|-------------|----------------|
| GET | `/api/stats/summary` | ノード数、エッジ数、プロジェクト数 | `orchestrator.stats()` + `list_projects()` |
| GET | `/api/stats/projects` | プロジェクト別統計 | `orchestrator.list_projects()` + per-project stats |
| GET | `/api/graph/layout` | Cytoscape 形式のノード+エッジ | `storage.list_by_filter()` + graph edges |
| POST | `/api/graph/traverse` | シード ID からグラフ探索 | `graph.traverse()` |
| GET | `/api/memories/{id}` | 単一メモリ取得 | `storage.get_memory()` |
| DELETE | `/api/memories/{id}` | メモリ削除 | `orchestrator.delete()` |
| POST | `/api/memories/search` | ハイブリッド検索 | `orchestrator.search()` |
| GET | `/api/system/resources` | CPU/メモリ/ディスク使用量 | `psutil` |
| GET | `/api/system/config` | 設定サマリ（機密情報除外） | `Settings` |
| GET | `/api/logs/recent` | 直近ログ（リングバッファ） | `LogCollector` |

### 3.3 WebSocket エンドポイント

| Path | Description |
|------|-------------|
| `/ws/logs` | リアルタイムログストリーミング（構造化ログ） |
| `/ws/events` | 記憶の保存/削除/ライフサイクルイベント通知 |

### 3.4 主要レスポンス形式

#### グラフレイアウト (`GET /api/graph/layout`)

```json
{
  "elements": {
    "nodes": [
      {
        "data": {
          "id": "uuid-1",
          "label": "Server-A に関する記憶...",
          "memoryType": "episodic",
          "importance": 0.8,
          "project": "proj-a",
          "accessCount": 5,
          "createdAt": "2026-04-01T10:00:00Z"
        }
      }
    ],
    "edges": [
      {
        "data": {
          "id": "uuid-1-uuid-2-RELATED",
          "source": "uuid-1",
          "target": "uuid-2",
          "edgeType": "RELATED"
        }
      }
    ]
  },
  "totalNodes": 150,
  "totalEdges": 300
}
```

#### サマリ統計 (`GET /api/stats/summary`)

```json
{
  "activeCount": 120,
  "archivedCount": 30,
  "totalCount": 150,
  "edgeCount": 300,
  "projectCount": 5,
  "projects": ["proj-a", "proj-b", "..."]
}
```

### 3.5 設計上の制約

- **ノード上限**: `/api/graph/layout` はデフォルト 500 ノードまで（`importance_score` 降順）
- **Lifespan**: FastAPI の `@asynccontextmanager` で `create_orchestrator()` を起動時に初期化、シャットダウン時に `dispose()`
- **CORS**: 開発時は `http://localhost:5173` (Vite dev server) を許可

### 3.6 既存コードへの変更

| ファイル | 変更内容 |
|----------|----------|
| `pyproject.toml` | `[project.optional-dependencies.dashboard]` 追加、`chronos-dashboard` エントリポイント追加 |
| `src/context_store/storage/sqlite_graph.py` | `list_all_edges(limit, offset)` メソッド追加 |
| `src/context_store/storage/protocols.py` | `GraphAdapter` に `list_all_edges` 追加 (Optional) |

### 3.7 追加依存関係

```toml
[project.optional-dependencies]
dashboard = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "psutil>=5.9.0",
    "websockets>=12.0",
]
```

---

## 4. フロントエンド設計

### 4.1 ディレクトリ構造

```text
dashboard/
    package.json
    tsconfig.json
    vite.config.ts
    tailwind.config.ts
    postcss.config.js
    index.html
    src/
        main.tsx
        App.tsx
        api/                          # API クライアント層
            client.ts                 # fetch wrapper, base URL 設定
            graph.ts                  # グラフ API
            stats.ts                  # 統計 API
            system.ts                 # システムリソース API
            logs.ts                   # ログ API
            websocket.ts              # WebSocket 接続管理
        stores/                       # Zustand ストア
            graphStore.ts             # ノード、エッジ、選択状態、フィルタ
            statsStore.ts             # サマリ統計、プロジェクト一覧
            systemStore.ts            # CPU、メモリ、ディスク
            logStore.ts               # ログエントリ、フィルタ、severity
            settingsStore.ts          # テーマ、レイアウト設定、API URL
        pages/
            Dashboard.tsx             # メインダッシュボード（ヘルス概要）
            NetworkView.tsx           # フルスクリーングラフ可視化
            LogExplorer.tsx           # 検索・フィルタ可能なログビュー
            Settings.tsx              # ユーザー設定、API 設定
        components/
            layout/
                Sidebar.tsx
                Header.tsx
                PageContainer.tsx
            dashboard/
                StatCard.tsx
                SystemResourceGauge.tsx
                RecentActivityFeed.tsx
                ProjectSelector.tsx
            graph/
                CytoscapeGraph.tsx     # Cytoscape.js ラッパー
                GraphControls.tsx      # レイアウト選択、ズーム、フィット
                GraphFilters.tsx       # エッジタイプ、プロジェクト絞り込み
                NodeDetailPanel.tsx    # スライドアウト詳細パネル
                GraphLegend.tsx        # 凡例
            logs/
                LogTable.tsx
                LogStream.tsx          # リアルタイムテール表示
                LogFilters.tsx         # severity, テキスト検索
            common/
                ThemeToggle.tsx
                LoadingSpinner.tsx
                ErrorBoundary.tsx
                SearchInput.tsx
        hooks/
            useWebSocket.ts
            useGraphData.ts
            useSystemResources.ts
            useLogStream.ts
        types/
            api.ts                    # API レスポンス型定義
            graph.ts                  # Cytoscape element 型定義
        utils/
            formatters.ts             # 日付、数値フォーマット
            cytoscape.ts              # Cytoscape 設定、スタイル、レイアウト
        styles/
            globals.css               # Tailwind base imports
```

### 4.2 ページ構成とルーティング

React Router v6 による 4 ページ構成:

| パス | ページ | 概要 |
|------|--------|------|
| `/` | Dashboard | システムヘルス概要、StatCard、リソースゲージ |
| `/network` | NetworkView | フルスクリーン Cytoscape.js グラフ |
| `/logs` | LogExplorer | リアルタイムログテール + フィルタ |
| `/settings` | Settings | テーマ、API URL、レイアウト設定 |

### 4.3 グラフ可視化設計

#### ノードスタイル

| `memory_type` | 色 | 説明 |
|----------------|-----|------|
| episodic | 青 (`#3B82F6`) | 経験・イベントの記憶 |
| semantic | 緑 (`#10B981`) | 知識・事実の記憶 |
| procedural | 橙 (`#F59E0B`) | 手順・プロセスの記憶 |

- `importance_score` でノードサイズが変動 (0.0-1.0 → 20px-60px)
- ホバーでツールチップ（ラベル + タイプ + スコア）

#### レイアウトアルゴリズム

| アルゴリズム | 用途 |
|------------|------|
| cose-bilkent (**デフォルト**) | 汎用。ノード重複を回避する力学モデル |
| cola | 制約ベース。クラスタが明確な場合 |
| dagre | 有向グラフ。階層関係の可視化 |
| circle | 円形配置。全体俯瞰 |
| breadthfirst | 木構造。ルートからの展開 |

#### インタラクション

- **ノードクリック**: `NodeDetailPanel` がスライドアウトで表示（記憶の全文、メタデータ、接続エッジ一覧）
- **エッジクリック**: エッジタイプとプロパティを表示
- **ズーム/パン**: マウスホイール + ドラッグ（Cytoscape 標準）
- **フィット**: 全ノードが画面内に収まるよう自動調整

### 4.4 ダークモード

- Tailwind `darkMode: 'class'` 方式
- `ThemeToggle` コンポーネントで `<html>` の `dark` クラスを切替
- `localStorage` に設定を永続化
- Cytoscape のノード/エッジ色もテーマに連動

---

## 5. データフロー

### 5.1 Dashboard ページロード

```text
Dashboard.tsx mount
  → statsStore.fetchSummary()
    → GET /api/stats/summary
      → orchestrator.stats() + list_projects()
    → statsStore 更新
  → systemStore.fetchResources()
    → GET /api/system/resources
      → psutil 読み取り
    → systemStore 更新（5秒ポーリング）
  → StatCard, SystemResourceGauge 描画
```

### 5.2 Network View グラフロード

```text
NetworkView.tsx mount
  → graphStore.fetchLayout(project?, edgeTypes?)
    → GET /api/graph/layout?project=X&limit=500
      → storage.list_by_filter() + graph edge query
      → Cytoscape elements 形式に変換
    → graphStore.elements 更新
  → CytoscapeGraph 描画
  → ユーザーがノードクリック
    → graphStore.setSelectedNode(id)
    → NodeDetailPanel が GET /api/memories/{id} で詳細取得
```

### 5.3 ログストリーミング

```text
LogExplorer.tsx mount
  → logStore.fetchRecent()
    → GET /api/logs/recent?limit=100
  → useLogStream() hook
    → WebSocket /ws/logs 接続
    → メッセージ受信 → logStore.appendLog(entry)
  → LogTable 描画
  → LogFilters → logStore.filters 更新 → クライアントサイドフィルタ
```

### 5.4 グラフ変更通知

```text
ユーザーが NodeDetailPanel からメモリ削除
  → DELETE /api/memories/{id}
    → orchestrator.delete(id)
    → /ws/events にブロードキャスト: { type: "delete", id }
  → CytoscapeGraph が WS イベント受信
    → graphStore.removeNode(id)
    → Cytoscape がノードを即時削除
```

---

## 6. 実装フェーズ

### Phase 1: Backend API Foundation

**目標**: FastAPI サーバーが起動し、REST エンドポイントからコアデータを返却できる状態

1. `src/context_store/dashboard/` パッケージ構造を作成
2. `api_server.py`: FastAPI app + lifespan (Orchestrator init/dispose) + CORS
3. `schemas.py`: Pydantic レスポンスモデル
4. `routes/stats.py`: `/api/stats/summary`, `/api/stats/projects`
5. `routes/memories.py`: GET, DELETE, search
6. `routes/graph.py`: `/api/graph/layout`, `/api/graph/traverse`
7. `sqlite_graph.py` に `list_all_edges()` 追加
8. `pyproject.toml` に依存関係 + エントリポイント追加
9. `system_monitor.py`: psutil ベース
10. pytest テスト

### Phase 2: Frontend Scaffold + Dashboard Page

**目標**: Vite プロジェクトが起動し、Dashboard ページでサマリ統計とリソースゲージが表示される

1. Vite + React + TypeScript プロジェクト初期化
2. Tailwind CSS 設定
3. React Router ルーティング
4. レイアウトコンポーネント (Sidebar, Header)
5. API クライアント + Zustand ストア
6. Dashboard ページ: StatCard, SystemResourceGauge
7. ダーク/ライトモード
8. Vite proxy 設定

### Phase 3: Network View (Graph Visualization)

**目標**: Cytoscape.js でインタラクティブなグラフが描画され、ノード詳細が閲覧できる

1. Cytoscape.js + レイアウト拡張インストール
2. `CytoscapeGraph` コンポーネント
3. `GraphControls` (レイアウト切替、ズーム、フィット)
4. `GraphFilters` (エッジタイプ、プロジェクト)
5. `NodeDetailPanel` (スライドアウト詳細)
6. `GraphLegend` (凡例)
7. ノードスタイル設定

### Phase 4: Real-time Log Streaming + Event Monitor

**目標**: WebSocket 経由でリアルタイムログが表示され、記憶イベントが通知される

1. `log_collector.py`: logging.Handler + ring buffer + asyncio.Queue
2. `websocket_manager.py`: 接続管理 + ブロードキャスト
3. WebSocket エンドポイント実装
4. `LogExplorer` ページ: LogTable, LogFilters, LogStream

### Phase 5: Settings Page + Production Polish

**目標**: 設定画面、エラー処理、本番デプロイ対応

1. Settings ページ
2. Error boundaries, loading/empty states
3. FastAPI で `dashboard/dist/` 静的配信
4. `docker-compose.yml` に dashboard サービス追加

### Phase 6: Could-Have Features (後回し可)

- 時系列スライダー (`created_at` フィルタリング)
- `cy.png()` / `jspdf` エクスポート
- グラフ分析（次数分布、クラスタ検出）

---

## 7. 検証戦略

### 7.1 バックエンド

- **ユニットテスト** (`tests/unit/test_dashboard_*.py`): mock Orchestrator で各ルートハンドラをテスト
- **統合テスト** (`tests/integration/test_dashboard_api.py`): `httpx.AsyncClient` + SQLite in-memory で E2E
- **WebSocket テスト**: `/ws/logs` 接続 → ログイベント発火 → メッセージ受信確認

### 7.2 フロントエンド

- **Vitest**: Zustand ストアのユニットテスト
- **React Testing Library**: コンポーネント描画テスト

### 7.3 手動チェックリスト

- [ ] Dashboard ページにて StatCard が正しい値を表示
- [ ] Network View でグラフが描画、ノードクリックで詳細表示
- [ ] レイアウトアルゴリズム切替で再レイアウト
- [ ] ダークモード切替が全ページに反映
- [ ] Log Explorer でリアルタイムログが流れる
- [ ] Settings の変更が `localStorage` に保存

---

## 8. 既存コードとの関連

| ファイル | 役割 | 変更の有無 |
|----------|------|-----------|
| `src/context_store/orchestrator.py` | Orchestrator + `create_orchestrator` ファクトリ | 参照のみ |
| `src/context_store/storage/protocols.py` | StorageAdapter / GraphAdapter プロトコル | `list_all_edges` 追加 |
| `src/context_store/storage/sqlite_graph.py` | SQLiteGraphAdapter | `list_all_edges` 追加 |
| `src/context_store/config.py` | Settings クラス | ダッシュボード設定追加 |
| `src/context_store/models/memory.py` | Memory / ScoredMemory モデル | 参照のみ |
| `src/context_store/models/graph.py` | Edge / GraphResult モデル | 参照のみ |
| `pyproject.toml` | 依存関係・エントリポイント | 変更 |

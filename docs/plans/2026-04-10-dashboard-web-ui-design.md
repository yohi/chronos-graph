# Chronos Graph Dashboard - Web UI 設計書

> **作成日**: 2026-04-10
> **更新日**: 2026-04-10 (CQRS / SRP / YAGNI / TDD / Read-Only 再定義レビュー対応 + asyncio.Queue バックプレッシャ仕様修正 + Docker bind/Neo4j Phase 整合性修正 + StorageAdapter DRY/YAGNI 修正 + TDD完全性/DB未初期化フェイルファスト/ログバースト耐性注記 + SQLite IN句チャンク分割注記/統計クエリキャッシュ方針 + SPAフォールバック/WS再接続/API Base URL方針 + rev.10: create_storage ファクトリ新規追加 / SQLite read-only URI モード対応 / Settings フィールド追加方針明記)
> **ブランチ**: `feat/dashboard`
> **ステータス**: Approved (rev. 10)

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
| バックエンド API | FastAPI | Read-Only アダプタを直接利用 (CQRS)、WebSocket 対応 |
| 監視対象 | 記憶データイベント | グラフ可視化に特化 |
| 配置場所 | `frontend/` (FE) と `src/context_store/dashboard/` (BE) | 名前衝突を避けて明確に分離 |

### 1.2 MoSCoW 優先度

| 優先度 | 機能 |
|--------|------|
| **Must Have** | インタラクティブノード・エッジグラフ、リアルタイムログストリーミング |
| **Should Have** | グラフフィルタリング/検索、カスタマイズ可能なレイアウトアルゴリズム、ダーク/ライトモード |
| **Could Have** | 時系列データ再生、PDF/画像エクスポート |
| **Won't Have** | 統合 IDE 機能、重いサーバーサイド処理、ホストリソース監視 (CPU/メモリ/ディスク)、書き込み操作 (DELETE 等) |

---

## 2. アーキテクチャ

### 2.1 全体構成

```text
┌──────────────────┐     HTTP/WS      ┌─────────────────────────┐
│  React Frontend  │ <─────────────> │  FastAPI Bridge          │
│  (Vite + TS)     │  REST + WebSocket│  (api_server.py)         │
│  frontend/       │                  │  src/.../dashboard/      │
└──────────────────┘                  └────────┬────────────────┘
                                               │ Direct import (CQRS)
                                    ┌──────────┴──────────┐
                              ┌─────▼──────┐     ┌───────▼────────┐
                              │ Storage     │     │ Graph          │
                              │ Adapter     │     │ Adapter        │
                              │ (Read-Only) │     │ (Read-Only)    │
                              └─────┬──────┘     └───────┬────────┘
                                    │                    │
                                SQLite/PG          Neo4j/SQLite
```

> **設計判断: Orchestrator を経由しない理由 (CQRS)**
>
> `create_orchestrator()` は `EmbeddingProvider` (ローカル ML モデルのロードや API キーの取得)、`IngestionPipeline` (書き込みパイプライン)、`RetrievalPipeline` (ベクトル検索)、`LifecycleManager` (アーカイブ/パージ) 等、Read-Only ダッシュボードには不要なコンポーネントを全て初期化する。
> これにより起動速度の低下、不要なリソース消費、および SRP 違反が発生する。
>
> Dashboard は **読み取り専用のクエリ側 (Query Side)** として、`create_storage()` ファクトリ経由で `StorageAdapter` と `GraphAdapter` のみを直接取得し、集約ロジックはダッシュボードパッケージ内の専用サービスモジュールで実装する。

### 2.2 設計方針

- **Orchestrator を経由しない CQRS アーキテクチャ**: MCP プロトコルブリッジも Orchestrator インスタンスも不要。FastAPI の Lifespan 内で `create_storage(settings)` を呼び出し、`StorageAdapter` と `GraphAdapter` を直接取得して利用する。`EmbeddingProvider`, `IngestionPipeline`, `RetrievalPipeline`, `LifecycleManager` はダッシュボードプロセスでは一切初期化しない
- **独立プロセス**: ダッシュボードは `chronos-dashboard` コマンドで起動。既存 MCP サーバー (`context-store`) には影響なし
- **DB 未初期化時のフェイルファスト**: MCP が一度も起動しておらず、SQLite データベースファイル（またはスキーマ）が存在しない状態で Dashboard を起動した場合、FastAPI の Lifespan 内で `create_storage(settings)` が失敗する。この場合、分かりやすいエラーメッセージ（例: `"Dashboard requires an existing database. Please start the MCP server (context-store) at least once to initialize the database."`）をロギングし、即時シャットダウン（フェイルファスト）する。サイレントに空データを返したり、自動で migration を実行したりしない
- **完全 Read-Only アーキテクチャ**: Dashboard は**純粋な可視化ツール**として位置づけ、書き込み操作 (DELETE/UPDATE 等) は一切提供しない。これにより以下を保証する:
  - SQLite: Read-Only URI モード (`file:...?mode=ro`) で接続。`PRAGMA journal_mode=WAL` は MCP 側 (書き込み主体) の初期化時に有効化済みであることを前提とし、dashboard 側では migration を実行しない
  - **現状のコードベース制約**: 既存の `sqlite.py` / `sqlite_graph.py` は `aiosqlite.connect(path)` を通常モードで呼ぶ実装であり、Read-Only URI モードのコードパスは未実装である。Phase 1 で Read-Only モード対応を追加する必要がある (§3.6 変更表参照)
  - **実装方式**: `create_storage(settings, *, read_only: bool = False)` ファクトリに `read_only` パラメータを追加し、Dashboard からは `read_only=True` で呼び出す。`read_only=True` の場合、SQLite アダプタは接続 URI を `file:{path}?mode=ro` に切り替える。これにより、SQLite バックエンドが OS レベルで書き込み不可となり、アプリケーションバグによる意図しない書き込みも原理的に遮断される
  - MCP プロセスとの同時書き込み競合 (`database is locked`) および migration race が原理的に発生しない
  - **Neo4j バックエンド**: Read-Only 保証は Neo4j セッションの `default_access_mode=READ` 指定で担保する。`Neo4jGraphAdapter` は `create_storage(read_only=True)` 経由で READ セッションのみを発行する構成とし、Dashboard からの書き込み経路をアダプタレベルで排除する
  - Redis/InMem キャッシュはプロセスローカルなので、dashboard 側のキャッシュは TTL を短めに設定 or 無効化する
- **統計クエリのキャッシュ方針 (YAGNI)**: `get_stats_summary()` (内部で `count_by_filter()`, `list_projects()`, `count_edges()` を呼び出す) はダッシュボード起動時およびフロントエンドからの定期ポーリング時に毎回実行される。**MVP 段階では実装の複雑化を避けるため (YAGNI)、結果のキャッシュは行わず毎回 DB クエリを発行して許容する**。Read-Only SQLite 接続 + WAL モードにより MCP プロセスとの reader 競合は発生せず、500 ノード規模ではクエリコストは十分に低い（§4.5 SLO 参照）。ただし、データ量の増大（数万ノード規模）に伴い `count_by_filter()` や `count_edges()` のレスポンスタイムが SLO を超過する場合は、**Phase 6 以降で短 TTL（5-30 秒程度）のインメモリキャッシュ**（`DashboardService` 内の `functools.lru_cache` + TTL ラッパー、または軽量な dict + timestamp）を導入し、ポーリング間隔内の重複クエリを抑制する段階的戦略をとる
- **プロセス分離**: dashboard プロセスのアダプタは MCP サーバーのものとは**別インスタンス**。MCP 経由の変更検出はポーリング (§5.1) に委ねる。将来の統合運用 (`context-store --with-dashboard` 同居起動) は Phase 6 以降で検討
- **認証**: MVP では省略。FastAPI は `0.0.0.0` にバインドし、ローカルアクセス制限は以下の二層で担保する:
  1. **Docker ポートフォワード層**: `docker-compose.yml` で `127.0.0.1:8000:8000` と指定し、ホスト外からの到達をネットワーク層で遮断
  2. **アプリケーション層**: FastAPI の `TrustedHostMiddleware` で `Host: localhost|127.0.0.1` 以外のリクエストを拒否

  > **設計判断: `0.0.0.0` バインドの理由**
  >
  > Docker コンテナ内で `127.0.0.1` にバインドすると、コンテナのネットワーク名前空間により `docker-compose.yml` のポートフォワード経由でもホストマシンのブラウザからアクセスできない。Phase 5 で Docker コンテナ化する前提のため、アプリケーション自体は `0.0.0.0` でリッスンし、セキュリティ保護は Docker のポートフォワード設定とミドルウェアに委ねる。
  > 非 Docker 環境（開発時の直接起動）でも `TrustedHostMiddleware` により `localhost` / `127.0.0.1` 以外からのアクセスは拒否される。

---

## 3. バックエンド API 設計

### 3.1 ディレクトリ構造

```text
src/context_store/dashboard/
    __init__.py
    api_server.py          # FastAPI app, lifespan (Read-Only アダプタ初期化), CORS, uvicorn main
    schemas.py             # Pydantic response models
    services.py            # 複数アダプタの集約ロジック (stats_summary, list_with_edges 等)
    log_collector.py       # logging.Handler + スレッドセーフ ring buffer (下記参照)
    websocket_manager.py   # WebSocket 接続管理 + ブロードキャスト (タイムアウト付き)
    routes/
        __init__.py
        graph.py           # /api/graph/*
        memories.py        # /api/memories/*
        stats.py           # /api/stats/*
        system.py          # /api/system/config のみ
        logs.py            # /api/logs/*
```

### 3.2 REST エンドポイント

すべての Backend Source は **Read-Only の `StorageAdapter` / `GraphAdapter` を直接利用** する。複数アダプタの呼び出しと DTO への集約マッピングは、ダッシュボードパッケージ内の **`services.py`** (サービスモジュール) または各 `routes/*.py` のルーティング層で行う。

| Method | Path | Description | Backend Source |
|--------|------|-------------|----------------|
| GET | `/api/stats/summary` | ノード数、エッジ数、プロジェクト数 | `services.get_stats_summary()` → `storage.count_by_filter()` + `storage.list_projects()` + `graph.count_edges()` |
| GET | `/api/stats/projects` | プロジェクト別統計 | `services.get_project_stats()` → `storage.list_projects()` + per-project `storage.count_by_filter()` |
| GET | `/api/graph/layout` | Cytoscape 形式のノード+エッジ | `services.get_graph_layout()` → `storage.list_by_filter(MemoryFilters)` + `graph.list_edges_for_memories()` |
| POST | `/api/graph/traverse` | シード ID からグラフ探索 | `services.traverse_graph()` → `graph.traverse()` |
| GET | `/api/memories/{id}` | 単一メモリ取得 | `storage.get_memory()` |
| POST | `/api/memories/search` | ハイブリッド検索 | **Phase 1 スコープ外** (ベクトル検索には `EmbeddingProvider` が必要。Phase 3 以降で検討) |
| GET | `/api/system/config` | 設定サマリ (ホワイトリスト方式で機密除外) | `Settings` (下記参照) |
| GET | `/api/logs/recent` | 直近ログ（リングバッファ） | `LogCollector` |

> **Note**: `/api/memories/search` はハイブリッド検索（ベクトル検索 + キーワード検索）であるため、`EmbeddingProvider` の初期化が必要。Read-Only CQRS アーキテクチャでは Embedding を初期化しない方針のため、Phase 1 スコープからは除外する。将来、Dashboard に検索機能を追加する場合は、軽量な EmbeddingProvider のみを選択的に初期化する拡張を検討する。

**`/api/system/config` のホワイトリスト**: 返却するのは `storage_backend`, `graph_backend`, `cache_backend`, `embedding_provider`, `embedding_model`, `log_level`, `dashboard_port` のみ。`*_api_key`, `*_password`, `*_secret`, `*_token`, `database_url` (認証情報含む) は一切返さない。

> **現状の Settings との整合 (rev.10 追記)**: 既存の `src/context_store/config.py` の `Settings` クラスは上記フィールドのうち `graph_backend`, `embedding_model`, `log_level` を持たない (`graph_enabled: bool` のみ、embedding モデルは `local_model_name` / `litellm_model` 等に分散、`log_level` は未定義)。Phase 1 では以下方針で対応する:
>
> 1. **`graph_backend`**: `Settings` に `graph_backend: Literal["sqlite", "neo4j", "disabled"]` を追加。既存 `graph_enabled: bool` は後方互換のため残し、`graph_backend` から派生するプロパティとして内部的に扱う (deprecation は Phase 6 以降)
> 2. **`embedding_model`**: `Settings` に派生プロパティ `embedding_model: str` を追加し、`embedding_provider` の値に応じて `local_model_name` / `litellm_model` / 等から解決する (新規永続フィールドは追加しない、YAGNI)
> 3. **`log_level`**: `Settings` に `log_level: str = "INFO"` を新規追加 (環境変数 `LOG_LEVEL` から読み込み)
> 4. **`dashboard_port`**: `Settings` に `dashboard_port: int = 8000` と `dashboard_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]` を新規追加 (後者は §2.2 `TrustedHostMiddleware` の許可リスト用)
>
> これらの追加は `src/context_store/config.py` への変更を伴うため、§3.6 変更表にも反映する。

### 3.3 WebSocket エンドポイント

| Path | Description |
|------|-------------|
| `/ws/logs` | リアルタイムログストリーミング（構造化ログ） |

#### WebSocket Manager の契約

- **接続登録/解除**: `connect(ws)` / `disconnect(ws)` は `set[WebSocket]` に対する追加・削除。`disconnect` は send 例外・クローズ受信・broadcast タイムアウトのいずれかで発火
- **ブロードキャスト**: `broadcast(channel, payload)` は接続集合のスナップショットに対して並列 send:
  ```python
  await asyncio.gather(
      *(self._safe_send(ws, payload) for ws in list(self._conns[channel])),
      return_exceptions=True,
  )
  ```
  `_safe_send` は `asyncio.wait_for(ws.send_json(payload), timeout=1.0)` で保護し、タイムアウト/`WebSocketDisconnect`/その他例外で対象を切断
- **slow consumer ポリシー**: 全接続 broadcast でブロックしない。1 クライアントの遅延が他に伝播しない設計 (gather + per-connection timeout)


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

- **ノード上限**: `/api/graph/layout` はデフォルト 500 ノードまで。選抜は「プロジェクトフィルタ → `importance_score` 降順 → 上位 500 → その集合内のエッジのみ含める」の順。501 件目以降の取得 UX は Phase 6 で cursor ベース対応。**レスポンスには `totalNodes` (フィルタ後の全件数) と `returnedNodes` (実際に返却した件数) を含め、上限到達を判定可能にする**
- **SQLite `IN` 句パラメータ数の安全対策**: `graph.list_edges_for_memories(memory_ids)` は内部で `WHERE memory_id IN (?, ?, ...)` 形式のクエリを発行する。SQLite にはバインドパラメータ数の上限（`SQLITE_MAX_VARIABLE_NUMBER`, デフォルト 999）が存在する。**MVP の 500 ノード制限下ではこの上限に抵触しない**が、実装時には安全対策として、`memory_ids` リストのサイズが閾値（例: 500）を超えた場合にチャンク分割してクエリを発行し、結果をマージする処理を考慮すること。これにより、将来 Phase 6 でノード上限を緩和した際にもクエリが安全に動作する
- **`graph` バックエンド未設定時**: `GraphAdapter` が `None` の場合、`/api/graph/layout` と `/api/graph/traverse` は HTTP 503 (`{"detail": "graph backend not configured"}`) を返す
- **Lifespan**: FastAPI の `@asynccontextmanager` で `create_storage(settings)` を呼び出し、Read-Only の `StorageAdapter`, `GraphAdapter` (Optional), `CacheAdapter` を初期化。**DB ファイルまたはスキーマが存在しない場合は、エラーメッセージをロギングして即時シャットダウン（フェイルファスト）する** (§2.2 参照)。シャットダウン時に各アダプタの `dispose()` を呼び出す。`EmbeddingProvider`, `IngestionPipeline`, `RetrievalPipeline`, `LifecycleManager` は**初期化しない**
- **CORS**: 開発時は `http://localhost:5173` (Vite dev server) を許可
- **SPA フォールバックルーティング**: React Router v6 によるクライアントサイドルーティング (§4.2) を正しく動作させるため、FastAPI 側で **SPA フォールバック** を設定する。ブラウザから `/network`, `/logs`, `/settings` 等のパスに直接アクセス（URL 直打ち・リロード）された場合、サーバーに該当パスの静的ファイルは存在しないため 404 になる。これを防ぐため、`/api/*` および `/ws/*` **以外** のすべてのパスへの GET リクエストを `frontend/dist/index.html` にフォールバックする catch-all ルートを設定する。FastAPI の `StaticFiles(html=True)` だけでは `/network` のようなサブパスに対応しないため、明示的なフォールバック実装（例: catch-all route で `FileResponse("frontend/dist/index.html")` を返す）が必要である。この設定は Phase 5 ステップ 4（静的配信）で実装する
- **ログ収集のスレッド境界**: `logging.Handler.emit()` は任意スレッドから呼ばれるため、`asyncio.Queue` を直接叩くのは禁止。以下の 2 段構成とする:
  1. `LogCollectorHandler(logging.Handler)` は `threading.Lock` で保護した `collections.deque(maxlen=N)` に push するのみ (同期)。`/api/logs/recent` はこの deque のスナップショットを返す
  2. WebSocket ブロードキャストは、同期側から `loop.call_soon_threadsafe(queue.put_nowait, entry)` で asyncio 側の `asyncio.Queue` に中継。ループ参照は lifespan 内で `asyncio.get_running_loop()` を取って handler に注入する
  3. バックプレッシャ: deque は `maxlen` 到達で古いエントリを自動ドロップ (リングバッファ動作)。asyncio.Queue にも `maxsize` を設定し、満杯時（`put_nowait()` で `asyncio.QueueFull` 例外が発生した場合）は、明示的に `get_nowait()` で最古のエントリを破棄した上で再度 `put_nowait()` する（リングバッファ的挙動）。**注意**: `asyncio.Queue` は `collections.deque(maxlen=N)` とは異なり、満杯時の自動ドロップ機能を持たないため、このハンドリングは必須である

  > **将来検討: ログバースト時のイベントループ逼迫リスク**
  >
  > 現在の設計では `call_soon_threadsafe()` をログエントリ毎に呼び出すが、このメソッドは毎回イベントループの selector を wake up するため、大量ログがバースト的に発生した際にイベントループのコールバックキューを逼迫させるリスクがある。MVP ではこの設計で十分だが、将来的にバースト耐性が課題となった場合、同期側の deque にバッファリングした複数エントリを **リスト単位でバッチ中継** (`call_soon_threadsafe(queue.put_nowait, [entry1, entry2, ...])`) する方式への移行を検討する。これにより wake up 回数を大幅に削減し、イベントループへの負荷を軽減できる。

- **WebSocket ブロードキャスト**: `websocket_manager.broadcast()` は各 `send_json` を `asyncio.wait_for(..., timeout=1.0)` で保護し、タイムアウト/例外時はそのクライアントを即切断して接続集合から除外する

### 3.6 既存コードへの変更

| ファイル | 変更内容 |
|----------|----------|
| `pyproject.toml` | `[project.optional-dependencies.dashboard]` 追加、`chronos-dashboard` エントリポイント追加 |
| `src/context_store/storage/protocols.py` | `GraphAdapter` に `list_edges_for_memories(memory_ids)` と `count_edges()` を追加。`StorageAdapter` は既存メソッド (`get_memory`, `list_by_filter`, `count_by_filter`, `list_projects`) をそのまま利用し、**新規メソッドは追加しない** |
| `src/context_store/storage/__init__.py` (or ルートの `__init__.py`) | **新規 (rev.10)**: `create_storage(settings, *, read_only: bool = False) -> tuple[StorageAdapter, GraphAdapter \| None, CacheAdapter]` ファクトリを追加。既存 `create_orchestrator()` 内部のストレージ/グラフ/キャッシュ初期化ロジックをこの関数に抽出・共通化 (DRY)。`create_orchestrator()` は内部で `create_storage()` を呼び出す形にリファクタリングし、既存テストが Green のまま維持されることを確認する |
| `src/context_store/orchestrator.py` | `create_orchestrator()` を `create_storage()` 利用にリファクタリング (DRY 共通化のみ、外部 API・振る舞いは不変)。Dashboard 専用メソッドは追加しない (SRP / YAGNI) |
| `src/context_store/storage/sqlite.py` | **rev.10 追記**: Read-Only URI モード (`file:{path}?mode=ro`) での接続をサポート。`create_storage(read_only=True)` 経由で Dashboard から呼ばれた場合のみ有効化する。既存の通常モード接続 (MCP サーバー経路) は一切変更しない。`get_memory`, `list_by_filter` 等の既存メソッドシグネチャは変更なし |
| `src/context_store/storage/postgres.py` | 変更なし (Phase 1 では Dashboard の read-only 接続は SQLite 優先。Postgres バックエンドでの read-only 対応は Phase 6 で検討) |
| `src/context_store/storage/sqlite_graph.py` | `GraphAdapter` の `list_edges_for_memories`, `count_edges` を実装。**rev.10 追記**: sqlite.py と同様に Read-Only URI モード対応を追加 |
| `src/context_store/storage/neo4j.py` | `GraphAdapter` の `list_edges_for_memories`, `count_edges` を**両方とも Phase 1 で実装**。`/api/graph/layout` の統合テストが Neo4j 環境でも Green になることを Phase 1 完了条件とする。**rev.10 追記**: `create_storage(read_only=True)` の場合、セッションを `default_access_mode=neo4j.READ_ACCESS` で発行し、書き込み経路をアダプタレベルで排除する |
| `src/context_store/config.py` | **rev.10 追記**: `Settings` に以下を追加 — `graph_backend: Literal["sqlite", "neo4j", "disabled"]` (既存 `graph_enabled` は後方互換で維持、内部的に派生), `embedding_model: str` (派生プロパティとして `embedding_provider` から解決、新規永続フィールドは追加しない), `log_level: str = "INFO"`, `dashboard_port: int = 8000`, `dashboard_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]` |

> **変更しないファイル**: `src/context_store/orchestrator.py` — Dashboard 専用のメソッドを Orchestrator に追加しない (SRP / YAGNI)。Dashboard が必要とする読み取り・集約ロジックは `src/context_store/dashboard/services.py` に配置する。

#### Dashboard サービスモジュール (`services.py`) の責務

```python
# src/context_store/dashboard/services.py

class DashboardService:
    """Read-Only アダプタを組み合わせた Dashboard 専用の集約サービス。"""

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
    ) -> None: ...

    # Dashboard 用の集約統計 (active/archived/total/edge/project_count + projects list)
    async def get_stats_summary(self) -> DashboardStats:
        """storage.count_by_filter() + storage.list_projects() + graph.count_edges() を集約。"""
        ...

    # Cytoscape 形式のグラフレイアウトデータ取得
    async def get_graph_layout(
        self,
        *,
        project: str | None = None,
        limit: int = 500,
        order_by: Literal["importance", "recency"] = "importance",
    ) -> GraphLayoutResponse:
        """storage.list_by_filter(MemoryFilters) → graph.list_edges_for_memories() → Cytoscape elements 変換。"""
        ...

    # プロジェクト別統計
    async def get_project_stats(self) -> list[ProjectStats]:
        """storage.list_projects() → per-project storage.count_by_filter() を集約。"""
        ...

    # グラフ探索
    async def traverse_graph(
        self, seed_id: str, *, max_depth: int = 2, edge_types: list[str] | None = None,
    ) -> GraphResult:
        """graph.traverse() に委譲。graph is None 時は RuntimeError (FastAPI 層で 503)。"""
        ...
```

- `graph is None` の場合、`get_graph_layout` のエッジは空リスト、`traverse_graph` は `RuntimeError` を送出 (FastAPI 層で 503 に変換)
- `get_stats_summary()` で `graph.count_edges()` は `graph is None` 時に 0 を返す

### 3.7 追加依存関係

```toml
[project.optional-dependencies]
dashboard = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "websockets>=12.0",
]
```

---

## 4. フロントエンド設計

### 4.1 ディレクトリ構造

```text
frontend/
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
            client.ts                 # fetch wrapper, base URL 解決 (下記 API Base URL 方針参照)
            graph.ts                  # グラフ API
            stats.ts                  # 統計 API
            logs.ts                   # ログ API
            websocket.ts              # WebSocket 接続管理
        stores/                       # Zustand ストア
            graphStore.ts             # ノード、エッジ、選択状態、フィルタ
            statsStore.ts             # サマリ統計、プロジェクト一覧
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
                RecentActivityFeed.tsx
                ProjectSelector.tsx
            graph/
                CytoscapeGraph.tsx     # Cytoscape.js ラッパー
                GraphControls.tsx      # レイアウト選択、ズーム、フィット
                GraphFilters.tsx       # エッジタイプ、プロジェクト絞り込み
                NodeDetailPanel.tsx    # スライドアウト詳細パネル
                GraphLegend.tsx        # 凡例
                GraphTruncationWarning.tsx  # ノード上限到達時の警告バナー
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
            useWebSocket.ts           # WebSocket 接続管理 (Exponential Backoff 再接続付き)
            useGraphData.ts
            useLogStream.ts           # useWebSocket を利用したログストリーミング
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
| `/` | Dashboard | 記憶データ統計サマリ、StatCard |
| `/network` | NetworkView | フルスクリーン Cytoscape.js グラフ |
| `/logs` | LogExplorer | リアルタイムログテール + フィルタ |
| `/settings` | Settings | テーマ、API URL 設定 |

> **SPA ルーティングに関する重要な注意**: 上記パスはすべてクライアントサイドルーティングである。ブラウザの URL 直打ちやリロード時にサーバー側で 404 にならないよう、FastAPI 側で SPA フォールバックが必要 (§3.5 参照)。

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

#### ノード上限到達時の警告 UI

`/api/graph/layout` のレスポンスで `totalNodes > returnedNodes` (= 上限到達) の場合、以下の Warning UI を表示する:

- **表示位置**: `CytoscapeGraph` コンポーネント上部に固定バナー (`position: sticky`)
- **メッセージ**: `"全 {totalNodes} 件中 {returnedNodes} 件を表示しています。importance 上位のノードのみが描画されています。プロジェクトフィルタで絞り込むと全件表示できる場合があります。"`
- **スタイル**: 警告色 (amber/yellow) のアラートバナー。閉じるボタン付きだが、データ再取得時に再表示
- **コンポーネント**: `GraphTruncationWarning.tsx` (`components/graph/` に配置)

### 4.4 ダークモード

- Tailwind `darkMode: 'class'` 方式
- `ThemeToggle` コンポーネントで `<html>` の `dark` クラスを切替
- `localStorage` に設定を永続化
- Cytoscape のノード/エッジ色もテーマに連動。**テーマ切替時は `cy.style(newStyle).update()` で style のみ動的更新**し、レイアウト再計算はトリガしない (`cy.layout()` は呼ばない)

### 4.5 パフォーマンス SLO

| 指標 | 目標 | 測定方法 |
|------|------|---------|
| `/api/graph/layout` レスポンス | < 500ms (500 ノード) | FastAPI access log |
| Cytoscape 初回レイアウト | < 3s (500 ノード, cose-bilkent) | `cy.on('layoutstop')` の計測 |
| ダークモード切替反映 | < 100ms | `performance.mark` |
| WebSocket ログ表示遅延 | < 200ms (P95) | サーバ送信時刻と受信時刻の diff |

500 ノード超でレイアウトが 3 秒を超える場合、Phase 6 で Web Worker 化 (`cytoscape.use(cyHeadless)`) を検討。

### 4.6 状態管理の配線

- **store → Cytoscape** の更新経路は以下で統一:
  1. `CytoscapeGraph.tsx` は `useEffect` で `graphStore.elements` を購読し、差分を `cy.add()` / `cy.remove()` で反映 (全体再描画しない)
  2. Zustand middleware での直接 Cytoscape 操作は禁止 (テスタビリティ確保のため)

---

## 5. データフロー

### 5.1 Dashboard ページロード

```text
Dashboard.tsx mount
  → statsStore.fetchSummary()
    → GET /api/stats/summary
      → services.get_stats_summary()
        → storage.count_by_filter() + storage.list_projects() + graph.count_edges()
    → statsStore 更新
  → StatCard 描画
```

### 5.2 Network View グラフロード

```text
NetworkView.tsx mount
  → graphStore.fetchLayout(project?, edgeTypes?)
    → GET /api/graph/layout?project=X&limit=500
      → services.get_graph_layout(project=..., limit=500, order_by="importance")
        → storage.list_by_filter(MemoryFilters(project=..., limit=500, order_by="importance_score"))
        → graph.list_edges_for_memories([m.id for m in memories])
        → Cytoscape elements 形式に変換
    → graphStore.elements 更新
  → CytoscapeGraph 描画
  → ユーザーがノードクリック
    → graphStore.setSelectedNode(id)
    → NodeDetailPanel が GET /api/memories/{id} で詳細取得 (storage.get_memory)
```

#### API Base URL の解決方針 (DRY / YAGNI)

フロントエンドの API クライアント (`api/client.ts`) における Base URL の解決は、以下の方針に従う:

1. **デフォルト**: ブラウザの **相対パス** (`/api`) を使用する。本番環境 (Docker) では FastAPI が SPA と API を同一ホストから配信するため (§6 Phase 5)、相対パスで正しく解決される。環境変数 (`VITE_API_URL` 等) による外部注入は**行わない** (YAGNI)
2. **開発時 (Vite dev server)**: `vite.config.ts` の `server.proxy` で `/api` → `http://localhost:8000/api`、`/ws` → `ws://localhost:8000/ws` にプロキシする。フロントエンドのコードは本番・開発で同一のまま動作する
3. **オーバーライド**: Settings ページ (`/settings`) の API URL フィールドから任意の Base URL を設定可能とし、`settingsStore` 経由で `api/client.ts` に反映する。設定値は `localStorage` に永続化する。これにより、リモートサーバーへの接続やデバッグ用途に対応できる

この方針により、ビルド時の環境変数管理の複雑化を回避しつつ、すべてのデプロイ構成に対応できる。

### 5.3 ログストリーミング

```text
LogExplorer.tsx mount
  → logStore.fetchRecent()
    → GET /api/logs/recent?limit=100
  → useLogStream() hook
    → WebSocket /ws/logs 接続
    → メッセージ受信 → logStore.appendLog(entry)
    → 切断検出 → Exponential Backoff で自動再接続 (下記参照)
  → LogTable 描画
  → LogFilters → logStore.filters 更新 → クライアントサイドフィルタ
```

#### WebSocket クライアント側の再接続ロジック

サーバー側の slow consumer 保護 (§3.5: `asyncio.wait_for` 1 秒タイムアウト) による強制切断や、ネットワーク瞬断が発生した場合に備え、`useWebSocket` フック（`useLogStream` が内部で利用）に以下の自動再接続ロジックを実装する:

1. **Exponential Backoff**: 初回待機 1 秒、最大待機 30 秒、倍率 2x。`delay = min(baseDelay * 2^attempt, maxDelay)` + ジッタ (±20%)
2. **最大リトライ回数**: 無制限（ダッシュボードは常時表示を前提とするため）。ただし、backoff が上限に達した後は 30 秒間隔で定期リトライ
3. **接続成功時のリセット**: 接続確立後にリトライカウンタとディレイをリセット
4. **UI フィードバック**: 再接続中は `LogStream` コンポーネント上に接続状態インジケータ（"再接続中..." / "接続済み"）を表示
5. **ページ離脱時のクリーンアップ**: コンポーネントのアンマウント時に再接続タイマーをキャンセルし、WebSocket を正常クローズする

---

## 6. 実装フェーズ

### Phase 依存関係と並列化

```text
Phase 1 (Backend API) ──┬── Phase 3 (Network View)  ──┐
                        │                              │
Phase 2 (FE Scaffold) ──┼── Phase 4 (WS/Logs)        ──┼── Phase 5 (Polish + E2E)
 (MSW モックで先行可)   │                              │
                        └── (並列可)                  ─┘
```

- **Phase 2 は Phase 1 完了を待たなくて良い**: FE は [MSW](https://mswjs.io/) で API モックを用意し、Phase 1 と並行して進める。Phase 1 完了後にモックを実 API に差し替える
- **Phase 3 と Phase 4 は並列可能**: グラフ描画と WS/ログは独立した軸
- **Phase 5 開始条件**: Phase 1-4 完了 + 静的配信パス (`src/context_store/dashboard/static/`) 決定済み
- **Phase 2 着手時点で決めるべき**: FastAPI の静的配信マウント位置 (`app.mount("/", StaticFiles(directory="frontend/dist", html=True))`) をこの時点でスタブ実装しておくと Phase 5 がスムーズ

### Phase 1: Backend API Foundation

**目標**: FastAPI サーバーが起動し、REST エンドポイントからコアデータを返却できる状態

1. `src/context_store/dashboard/` パッケージ構造を作成 (`services.py` 含む)
2. **失敗するリファクタリングテストの作成 (rev.10 追加)**: `create_storage(settings, *, read_only: bool = False)` ファクトリの期待動作を定義 — (a) 通常モードで `StorageAdapter` / `GraphAdapter` / `CacheAdapter` のタプルを返すこと、(b) `read_only=True` で SQLite URI が `file:...?mode=ro` に切り替わること、(c) `read_only=True` で Neo4j セッションが READ アクセスモードになること、(d) 既存 `create_orchestrator()` の外部振る舞いが不変であること (退行テスト)
3. **`create_storage()` ファクトリを実装 (rev.10 追加)**: 既存 `create_orchestrator()` 内部のストレージ/グラフ/キャッシュ初期化ロジックを抽出し、新ファクトリに移動。`create_orchestrator()` を内部で `create_storage()` を呼ぶ形にリファクタ。全既存テストが Green のままであることを確認する
4. **`Settings` 拡張 (rev.10 追加)**: `config.py` に `graph_backend`, `log_level`, `dashboard_port`, `dashboard_allowed_hosts` を追加し、`embedding_model` 派生プロパティを実装。失敗するテスト (env var / デフォルト値 / `/api/system/config` ホワイトリストに含まれること) を先に書いてから実装
5. **失敗するユニットテストの作成**: `GraphAdapter` プロトコルの新規メソッド (`list_edges_for_memories`, `count_edges`) に対する期待動作を定義
6. **`GraphAdapter` プロトコル + `sqlite_graph.py` / `neo4j.py` に実装** (テスト Green 化)。`neo4j.py` の `list_edges_for_memories()` も `count_edges()` も **Phase 1 で完全実装** し、統合テストが全バックエンドで Green になることを確認する。TDD プロセスの完全性を担保するため、`NotImplementedError` による先送りは行わない
7. **SQLite Read-Only URI モード対応 (rev.10 追加)**: `sqlite.py` / `sqlite_graph.py` に Read-Only 接続のサポートを追加。`read_only=True` の接続がすべての書き込みクエリで `OperationalError` を発生させることを確認する統合テストを書く
8. **失敗するユニットテストの作成**: `DashboardService` の集約メソッド (`get_stats_summary`, `get_graph_layout`, `get_project_stats`, `traverse_graph`) に対する期待動作を定義 (mock `StorageAdapter` / `GraphAdapter` 使用)。`get_graph_layout` は既存の `storage.list_by_filter(MemoryFilters)` を利用してデータを取得する集約ロジックをテストする
9. **`DashboardService` を実装** (テスト Green 化)
10. **失敗する統合テストの作成**: 各 REST エンドポイントの正常系・異常系レスポンスを定義 (`httpx.AsyncClient` + mock `DashboardService`)
11. `api_server.py`: FastAPI app + lifespan (`create_storage(settings, read_only=True)` で Read-Only `StorageAdapter` / `GraphAdapter` を初期化、`DashboardService` を組み立て、シャットダウン時に各アダプタの `dispose()`) + CORS + `TrustedHostMiddleware` (`settings.dashboard_allowed_hosts` を許可リストに設定)。uvicorn は `host="0.0.0.0"`, `port=settings.dashboard_port` でバインド (§2.2 認証方針参照)
12. `schemas.py`: Pydantic レスポンスモデル (`alias_generator=to_camel`, `populate_by_name=True`)
13. `routes/stats.py`: `/api/stats/summary`, `/api/stats/projects` (テスト Green 化)
14. `routes/memories.py`: GET (Read-Only のみ。search は Phase 3 以降) (テスト Green 化)
15. `routes/graph.py`: `/api/graph/layout`, `/api/graph/traverse` (`graph is None` で 503) (テスト Green 化)
16. `routes/system.py`: `/api/system/config` (ホワイトリスト方式) (テスト Green 化)
17. `pyproject.toml` に依存関係 + エントリポイント追加

### Phase 2: Frontend Scaffold + Dashboard Page

**目標**: Vite プロジェクトが起動し、Dashboard ページでサマリ統計が表示される

1. Vite + React + TypeScript プロジェクト初期化 (`frontend/`)
2. Tailwind CSS 設定 (`darkMode: 'class'`)
3. React Router ルーティング
4. レイアウトコンポーネント (Sidebar, Header)
5. **失敗する Vitest テストの作成**: Zustand ストア (statsStore, graphStore, logStore, settingsStore) の action に対する期待動作を定義
6. API クライアント + Zustand ストア実装 (テスト Green 化)
7. **MSW セットアップ** (`frontend/src/mocks/`): Phase 1 と並行開発するため全 API のハンドラをモック
8. **失敗する React Testing Library テストの作成**: StatCard コンポーネントが API モックの値を正しく描画することを定義
9. Dashboard ページ: StatCard (テスト Green 化)
10. ダーク/ライトモード (`ThemeToggle`, localStorage 永続化)
11. Vite proxy 設定 (本番 API 接続用)

### Phase 3: Network View (Graph Visualization)

**目標**: Cytoscape.js でインタラクティブなグラフが描画され、ノード詳細が閲覧できる

> **Note**: `neo4j.py` の `list_edges_for_memories()` は Phase 1 で実装済み。本 Phase ではバックエンド API の追加実装なしにフロントエンド開発に着手できる。

1. Cytoscape.js + レイアウト拡張インストール
2. **失敗する React Testing Library テストの作成**: CytoscapeGraph への elements 描画、ノードクリック時の NodeDetailPanel 表示を定義
3. `CytoscapeGraph` コンポーネント (テスト Green 化)
4. `GraphControls` (レイアウト切替、ズーム、フィット)
5. `GraphFilters` (エッジタイプ、プロジェクト)
6. `NodeDetailPanel` (スライドアウト詳細)
7. `GraphLegend` (凡例)
8. `GraphTruncationWarning` (ノード上限到達時の警告バナー)
9. ノードスタイル設定

### Phase 4: Real-time Log Streaming

**目標**: WebSocket 経由でリアルタイムログが表示される

1. **失敗するユニットテストの作成**: `LogCollectorHandler` の ring buffer 動作、スレッド境界の asyncio.Queue 中継を定義
2. `log_collector.py`: logging.Handler + ring buffer + asyncio.Queue (テスト Green 化)
3. **失敗するユニットテストの作成**: `WebSocketManager` の接続管理 + ブロードキャスト + slow consumer タイムアウトを定義
4. `websocket_manager.py`: 接続管理 + ブロードキャスト (テスト Green 化)
5. **失敗する統合テストの作成**: `/ws/logs` 接続 → ログイベント発火 → メッセージ受信を定義
6. WebSocket エンドポイント実装 (`/ws/logs` のみ) (テスト Green 化)
7. **失敗する React Testing Library テストの作成**: LogExplorer ページの描画とフィルタ動作を定義
8. `LogExplorer` ページ: LogTable, LogFilters, LogStream (テスト Green 化)

### Phase 5: Settings Page + Production Polish

**目標**: 設定画面、エラー処理、本番デプロイ対応

1. **失敗する Vitest テストの作成**: Settings ページの状態永続化 (localStorage) を定義
2. Settings ページ (API URL、テーマ) (テスト Green 化)
3. Error boundaries, loading/empty states
4. FastAPI で `frontend/dist/` 静的配信 + **SPA フォールバック**: `/api/*` および `/ws/*` 以外のすべての GET リクエストを `frontend/dist/index.html` にフォールバックする catch-all ルートを設定する (§3.5 参照)。`StaticFiles(html=True)` のみでは React Router のサブパス (`/network`, `/logs`, `/settings`) に対応しないため、明示的なフォールバック実装が必要
5. **Playwright E2E 4 ケース** (§7.2) + `axe-core` a11y チェック
6. `docker-compose.yml` に dashboard サービス追加。ポートフォワードは `127.0.0.1:8000:8000` でホスト外アクセスを遮断 (§2.2 認証方針参照)

### Phase 6: Could-Have Features (後回し可)

- 時系列スライダー (`created_at` フィルタリング)
- `cy.png()` / `jspdf` エクスポート
- グラフ分析（次数分布、クラスタ検出）

---

## 7. 検証戦略

### 7.1 バックエンド

- **ユニットテスト** (`tests/unit/test_dashboard_*.py`): mock `DashboardService` / `StorageAdapter` / `GraphAdapter` で各ルートハンドラをテスト
- **統合テスト** (`tests/integration/test_dashboard_api.py`): `httpx.AsyncClient` + SQLite in-memory で E2E
- **WebSocket テスト**: `/ws/logs` 接続 → ログイベント発火 → メッセージ受信確認
- **WebSocket 負荷テスト**: 同時 50 接続でログ burst (1000 件/秒) 送信時に slow consumer が 1 秒タイムアウトで切断されること、deque がリングオーバーフローで古いエントリをドロップすること、他クライアントが影響を受けないことを確認
- **ログ収集のスレッド境界テスト**: バックグラウンドスレッドから `logging.getLogger().error(...)` を発火し、deque に entry が蓄積されること + `loop.call_soon_threadsafe` 経由で asyncio.Queue に中継されることを確認

### 7.2 フロントエンド

- **Vitest**: Zustand ストアのユニットテスト (reducer, action)
- **React Testing Library**: コンポーネント描画テスト
- **Playwright E2E** (`frontend/e2e/`, Phase 5):
  1. Dashboard 表示: StatCard が API モックの値を描画
  2. NetworkView: グラフ描画 → ノードクリック → `NodeDetailPanel` スライドアウト → 上限到達時の `GraphTruncationWarning` 表示
  3. LogExplorer: WS モック接続 → ログエントリがストリーム表示 → severity フィルタ適用
  4. ThemeToggle: ダークモード切替が全ページに伝播 + localStorage 永続化
- **アクセシビリティ**: `axe-core` を Playwright に組み込み、主要ページで重大な a11y 違反がないこと

### 7.3 手動チェックリスト

- [ ] Dashboard ページにて StatCard が正しい値を表示
- [ ] Network View でグラフが描画、ノードクリックで詳細表示
- [ ] ノード上限 (500) 到達時に `GraphTruncationWarning` が表示される
- [ ] レイアウトアルゴリズム切替で再レイアウト
- [ ] ダークモード切替が全ページに反映
- [ ] Log Explorer でリアルタイムログが流れる
- [ ] Settings の変更が `localStorage` に保存

---

## 8. 既存コードとの関連

| ファイル | 役割 | 変更の有無 |
|----------|------|-----------|
| `src/context_store/orchestrator.py` | Orchestrator + `create_orchestrator` ファクトリ | **rev.10 変更**: `create_orchestrator()` を新ファクトリ `create_storage()` 利用にリファクタ (DRY 共通化のみ、外部 API・振る舞いは不変)。Dashboard 用メソッドは追加しない (SRP / YAGNI) |
| `src/context_store/storage/__init__.py` (or ルート `__init__.py`) | ストレージファクトリ | **rev.10 新規**: `create_storage(settings, *, read_only: bool = False) -> (StorageAdapter, GraphAdapter \| None, CacheAdapter)` を追加 |
| `src/context_store/storage/protocols.py` | StorageAdapter / GraphAdapter プロトコル | `StorageAdapter` は**変更なし** (既存の `get_memory`, `list_by_filter`, `count_by_filter`, `list_projects` で充足)。`GraphAdapter` に `list_edges_for_memories`, `count_edges` 追加 |
| `src/context_store/storage/sqlite.py` | SQLiteStorageAdapter | **rev.10 変更**: Read-Only URI モード (`file:{path}?mode=ro`) 対応を追加。既存の `get_memory`, `list_by_filter` シグネチャは変更なし |
| `src/context_store/storage/postgres.py` | PostgresStorageAdapter | **変更なし** (Phase 1 Dashboard は SQLite 優先、Postgres read-only は Phase 6) |
| `src/context_store/storage/sqlite_graph.py` | SQLiteGraphAdapter | `list_edges_for_memories`, `count_edges` 実装 + **rev.10**: Read-Only URI モード対応 |
| `src/context_store/storage/neo4j.py` | Neo4jGraphAdapter | `list_edges_for_memories`, `count_edges` を**両方とも Phase 1 で完全実装** + **rev.10**: `read_only=True` 時に `default_access_mode=READ_ACCESS` セッションのみ発行 |
| `src/context_store/config.py` | Settings クラス | **rev.10 変更**: `graph_backend`, `log_level`, `dashboard_port`, `dashboard_allowed_hosts` を追加。`embedding_model` は派生プロパティとして実装 (新規永続フィールド追加なし) |
| `src/context_store/server.py` | MCP サーバーエントリ | 参照のみ (dashboard とはポート分離、将来の同居起動は Phase 6) |
| `src/context_store/models/memory.py` | Memory / ScoredMemory モデル | 参照のみ |
| `src/context_store/models/graph.py` | Edge / GraphResult モデル | 参照のみ |
| `pyproject.toml` | 依存関係・エントリポイント | 変更 |

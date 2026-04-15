# ChronosGraph: 記憶保存戦略アーキテクチャ設計

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to create
> an implementation plan from this spec before writing any code.

**Goal:** エージェントの自律的保存とシステムのバッチ保存を組み合わせたハイブリッド記憶保存戦略を実装する

**Date:** 2026-04-14

**Status:** Draft

---

## 1. Overview

ChronosGraph の記憶形成において、以下の2軸を統合するハイブリッド保存戦略を実装する:

- **A. エージェント駆動の自律的保存 (主軸)**: エージェントが重要と判断した Semantic/Procedural 情報を `memory_save` で即座に保存
- **B. バックグラウンドバッチ処理 (補助)**: セッションの会話ログを `session_flush` で非同期バッチ保存

### 1.1 Design Decisions

| 決定事項 | 選択 | 理由 |
|---|---|---|
| バッチ保存 | サーバー側 `session_flush` + クライアント呼び出し | 両側の責務を明確に分離 |
| エンドポイント方式 | 非同期ジョブ型 | `stdio` の逐次 RPC をブロックしない |
| ジョブ管理 | インメモリ `asyncio.create_task()` | 外部依存なし、YAGNI |
| トリガー管理 | クライアント側が全責任 | サーバーで会話ターン追跡は不適切 |
| システムプロンプト | `docs/` 配下のドキュメント | コードベースへの影響なし |

---

## 2. Architecture

### 2.1 Component Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server (FastMCP)                       │
│                                                               │
│  既存ツール:                     新規ツール:                    │
│  ├─ memory_save                 └─ session_flush  ← NEW      │
│  ├─ memory_search                                             │
│  ├─ memory_save_url                                           │
│  └─ ...                                                       │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    Orchestrator                          │ │
│  │                                                          │ │
│  │  ┌──────────────┐  ┌──────────────┐                     │ │
│  │  │  Ingestion   │  │   Batch      │                     │ │
│  │  │  Pipeline    │  │   Processor  │                     │ │
│  │  │  (既存)      │  │  NEW         │                     │ │
│  │  └──────┬───────┘  └──────┬───────┘                     │ │
│  │         │                 │                              │ │
│  │         │    ┌────────────┘                              │ │
│  │         │    │  ┌───────────────┐                        │ │
│  │         │    │  │ Task Registry │                        │ │
│  │         │    │  │ NEW           │                        │ │
│  │         │    │  └───────────────┘                        │ │
│  │         │    │                                           │ │
│  │  ┌──────┴────┴──────────────────────────────────────┐   │ │
│  │  │            Storage Layer (既存)                    │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow: session_flush

```text
session_flush(conversation_log)
  │
  ▼
Orchestrator.session_flush()
  ├─ BatchProcessor.estimate_chunks() → estimated_chunks
  ├─ task = asyncio.create_task(BatchProcessor.process(...))
  ├─ TaskRegistry.register(task)
  └─ return {status: "accepted", estimated_chunks}

# Background:
BatchProcessor.process()
  ├─ IngestionPipeline.ingest(conversation_log, source_type=CONVERSATION)
  │   ├─ Chunker._split_conversation() → Q&A pair splitting
  │   ├─ Classifier.classify() → EPISODIC (default)
  │   ├─ EmbeddingProvider.embed() → vectorization
  │   ├─ Deduplicator.deduplicate() → dedup check (>= 0.90 → SUPERSEDES)
  │   └─ StorageAdapter.save_memory() → persist (per-chunk commit)
  └─ (errors are logged; committed chunks are retained)
```

---

## 3. New Components

### 3.1 TaskRegistry

**File:** `src/context_store/ingestion/task_registry.py`

```python
class TaskRegistry:
    """In-memory registry of running asyncio.Task objects.

    Sole purpose: track background tasks for graceful shutdown cancellation.
    No state tracking, no history, no progress monitoring.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def register(self, task: asyncio.Task) -> None:
        """Register a task. Add done_callback for auto-removal and error logging.

        done_callback implementation:
        1. self._tasks.discard(task) で自身を除去
        2. task.exception() で未処理例外を取得
           - 例外が存在する場合: logger.error() でスタックトレース付きログ出力
           - CancelledError の場合: logger.debug() で正常キャンセルとして記録
           - 例外なしの場合: logger.debug() で正常完了を記録
        3. 例外は再送出しない（バックグラウンドタスクのため呼び出し元に伝播不可）
        """

    async def cancel_all(self, timeout: float = 5.0) -> None:
        """Cancel all running tasks with timeout. Called during graceful shutdown."""
```

### 3.2 BatchProcessor

**File:** `src/context_store/ingestion/batch_processor.py`

```python
class BatchProcessor:
    """Thin wrapper over IngestionPipeline for batch conversation log processing.

    Delegates all processing to IngestionPipeline.ingest().
    """

    def __init__(
        self,
        ingestion_pipeline: IngestionPipeline,
    ) -> None:
        self._pipeline = ingestion_pipeline

    def estimate_chunks(self, conversation_log: str) -> int:
        """Estimate chunk count using Chunker dry-run (no side effects).

        Creates a temporary RawContent with source_type=CONVERSATION,
        passes it through Chunker.chunk() to count yielded chunks,
        but does NOT persist anything. This is a pure read-only estimation.
        """

    async def process(
        self,
        conversation_log: str,
        *,
        session_id: str,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Background batch processing entry point.

        Flow:
        1. IngestionPipeline.ingest() with source_type=CONVERSATION
        2. Errors are logged (committed chunks are retained, uncommitted are lost)
        """
```

---

## 4. MCP Tool Interface

### 4.1 session_flush

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `conversation_log` | str | Yes | — | Full conversation log (`User: ...\nAssistant: ...` format). **最大 200,000 文字**。超過時はバリデーションエラーを返す |
| `session_id` | str | No | auto UUID | Session identifier |
| `project` | str? | No | None | Project name |
| `tags` | list[str] | No | [] | Additional tags |

**Validation:**

- `conversation_log` が空文字列の場合: `{"error": "conversation_log must not be empty"}`
- `conversation_log` が 200,000 文字を超過した場合: `{"error": "conversation_log exceeds maximum length of 200000 characters"}`
- バリデーションエラーは即座に同期レスポンスとして返され、バックグラウンドジョブは作成されない

**Response:**

```json
{
  "status": "accepted",
  "estimated_chunks": 5
}
```

---

## 5. Configuration

### 5.1 New Settings Parameters

| Parameter | Env Var | Default | Description |
|---|---|---|---|
| `batch_max_concurrent_jobs` | `BATCH_MAX_CONCURRENT_JOBS` | `3` | Max concurrent batch jobs |

---

## 6. Modified Existing Files

### 6.1 server.py

- Add `session_flush` MCP tool registration
- Delegate to `ChronosServer.session_flush()`

### 6.2 orchestrator.py

- Add `BatchProcessor` and `TaskRegistry` as constructor dependencies
- Add `session_flush()` method: estimate chunks → create_task → register → return accepted
- Update `dispose()` to call `TaskRegistry.cancel_all()`

### 6.3 orchestrator.py (create_orchestrator factory)

- Instantiate `TaskRegistry` and `BatchProcessor`

### 6.4 config.py

- Add batch configuration parameters (see Section 5.1)

---

## 7. Error Handling

| Scenario | Behavior |
|---|---|
| Process terminates during `session_flush` | Committed chunks are retained; uncommitted are lost |
| `batch_max_concurrent_jobs` exceeded | Immediate error response: `{"error": "Too many concurrent jobs"}` |
| Individual chunk ingestion failure in batch | Skip failed chunk, continue others. Error is logged |
| `conversation_log` が空文字列 | 即座にエラー: `{"error": "conversation_log must not be empty"}` |
| `conversation_log` が 200,000 文字超過 | 即座にエラー: `{"error": "conversation_log exceeds maximum length of 200000 characters"}` |
| `done_callback` 内で未処理例外を検出 | `logger.error()` でスタックトレース付きログ出力。例外は再送出しない（イベントループへの伝播を防止） |

---

## 8. Testing Strategy

All tests MUST be executed within the devcontainer environment.

### 8.1 New Test Files

| Test File | Coverage |
|---|---|
| `tests/unit/test_task_registry.py` | TaskRegistry register/cancel_all, graceful shutdown |
| `tests/unit/test_batch_processor.py` | BatchProcessor chunk estimation, Ingestion delegation |
| `tests/unit/test_session_flush_tools.py` | session_flush MCP tool E2E |

### 8.2 Key Test Scenarios

1. **Task registration:** `TaskRegistry.register()` adds task, done_callback removes it
2. **Concurrency limit:** Reject when exceeding `batch_max_concurrent_jobs`
3. **Transaction boundary:** Verify `embed()` completes before `save_memory()` (mock ordering)
4. **Graceful shutdown:** `TaskRegistry.cancel_all()` cancels running tasks within timeout
5. **Chunk failure resilience:** Partial chunk failures in batch do not abort the entire process

### 8.3 Edge Case Tests (具体的な入力/期待出力)

| # | テストケース | 入力 | 期待出力/動作 |
|---|---|---|---|
| E1 | 空の conversation_log | `conversation_log=""` | `{"error": "conversation_log must not be empty"}` (同期エラー、ジョブ未作成) |
| E2 | サイズ上限超過 | `conversation_log="A" * 200_001` | `{"error": "conversation_log exceeds maximum length of 200000 characters"}` (同期エラー、ジョブ未作成) |
| E3 | サイズ上限ちょうど | `conversation_log="A" * 200_000` | `{"status": "accepted", "estimated_chunks": ...}` (正常受理) |
| E4 | 不正フォーマット (Q&A ペア不成立) | `conversation_log="ランダムテキスト\n改行のみ"` | `{"status": "accepted", "estimated_chunks": 0}` (受理されるがチャンク0件、保存なし) |
| E5 | done_callback 内の例外検出 | バックグラウンドタスクが `RuntimeError` を送出 | `logger.error()` にスタックトレース記録。`TaskRegistry._tasks` から除去済み。イベントループ継続 |
| E6 | done_callback のキャンセル検出 | `cancel_all()` によるタスクキャンセル | `logger.debug()` に正常キャンセル記録。`TaskRegistry._tasks` から除去済み |

---

## 9. Graceful Shutdown Integration

```python
# Orchestrator.dispose() changes:
async def dispose(self) -> None:
    # NEW: Cancel running batch tasks (5s timeout)
    if self._task_registry is not None:
        await self._task_registry.cancel_all(timeout=5.0)

    await self._lifecycle_manager.graceful_shutdown()
    await self._storage.dispose()
    if self._graph is not None:
        await self._graph.dispose()
    await self._cache.dispose()
```

---

## 10. Out of Scope

| Item | Reason |
|---|---|
| RL hooks (ActionLogger / RewardSignal) | ログ蓄積・学習ループともに将来フェーズへ延期 |
| Job persistence across process restarts | YAGNI for `stdio` short-lived MCP server |
| HTTP/SSE transport | Planned for v2.1 (per SPEC.md §7.1.1) |
| Concept drift detection | Future extension point (per SPEC.md §6.5) |

---

## 11. SPEC.md Alignment

| SPEC.md Section | This Design |
|---|---|
| §4.3 Chunker (Q&A pair splitting, 1-3 turns) | Reuse existing `Chunker._split_conversation()` |
| §4.4 Deduplicator (cosine >= 0.90 → SUPERSEDES) | All batch-saved memories pass through existing Deduplicator |
| §6 Lifecycle Manager | Batch-saved memories are subject to normal lifecycle (decay, archive, purge) |
| Devcontainer constraint | All testing must run in devcontainer |

---

## Appendix A: Agent System Prompt Template

The following system prompt template is intended for integration into Claude 4.6 or
equivalent AI agent system instructions. It is NOT embedded in the MCP server code.

```xml
<role>
あなたは、ChronosGraphシステムをバックエンドに持つ高度な自律型AIエージェントです。
あなたのミッションは、ユーザーとの対話やコード操作を通じてタスクを解決するだけでなく、
将来のセッションで役立つ「価値ある記憶」を自律的に識別し、長期記憶システムへ保存することです。
</role>

<instructions>
タスクを実行する際、以下の基準に従って memory_save ツールを能動的に呼び出してください。

1. **記憶の評価（Thinkingプロセス）:**
   以下のいずれかの条件を満たした時点で、現在のコンテキスト内に
   「再利用価値のある知識」が含まれているか適応的思考（Adaptive Thinking）を
   用いて評価してください。
   - ユーザーからの指示を完了した後
   - コマンド実行がエラー終了（非0）から正常終了（0）に変化した実行の直後

2. **保存対象の抽出:**
   単なる相槌や一時的な状態は保存しないでください。以下のいずれかに該当する
   高密度の情報のみを要約して保存します。
   - **Semantic（概念・知識）:** ユーザーの好み、プロジェクト固有のアーキテクチャ規則、
     環境特有の設定値、ドメイン知識。
   - **Procedural（手順・解決策）:** 複雑なエラーの根本原因とそれを解決した具体的な手順、
     特定のタスクを遂行するための最適なコマンド群。

3. **ツールの実行:**
   価値ある記憶を特定した場合、即座に memory_save ツールを呼び出します。
   保存するテキストは、将来のあなた自身（または他のエージェント）が検索した際に、
   背景状況なしでも理解できる「具体的で独立した要約文」にしてください。

4. **会話ログのバッチ保存（session_flush）:**
   以下のいずれかの条件を満たした時点で、session_flush ツールを呼び出して
   会話ログ全体をバッチ保存してください。
   - 会話ログの総文字数が 8,000 文字に達した時
   - MCPサーバープロセスの終了前（graceful shutdown 時）

   一時的な会話ログは session_flush により自動的に EPISODIC 記憶として分類・保存されるため、
   memory_save での手動保存は不要です。

   会話ログ全文を conversation_log 引数に渡してください。
   session_id は省略可能です（自動生成されます）。
</instructions>

<memory_rules>
- **Semantic（概念・知識）の保存フォーマット:**
  memory_save で Semantic 情報を保存する場合、以下の構造に従うこと:
  - 保存テキストの先頭に `[Semantic]` プレフィックスを付与する
  - 「対象（何について）」と「事実・ルール・値（何であるか）」のペアを必ず含める
  - 例: `[Semantic] ChronosGraph のデフォルトストレージ — SQLite を使用し、SIMILARITY_THRESHOLD は 0.70`
- **Procedural（手順・解決策）の保存フォーマット:**
  memory_save で Procedural 情報を保存する場合、以下の構造に従うこと:
  - 保存テキストの先頭に `[Procedural]` プレフィックスを付与する
  - 「トリガー条件（いつ／どの状況で適用するか）」と「手順（具体的なステップ）」のペアを必ず含める
  - 手順部分は番号付きステップ（1. 2. 3. ...）で記述する
  - 例: `[Procedural] pytest が ModuleNotFoundError で失敗した場合: 1. devcontainer 内で実行しているか確認 2. uv sync で依存を再インストール 3. PYTHONPATH に src が含まれているか確認`
- **重複の心配は不要:** 以前に保存したルールや知識が更新された場合でも、
  単に最新の状態を memory_save で保存してください。バックエンドの Deduplicator
  （類似度 >= 0.90 の判定）が自動的に SUPERSEDES エッジを作成し、
  記憶を統合・最新化します。
</memory_rules>

<constraints>
- ユーザーに「記憶に保存しますか？」と尋ねてはいけません。
  あなたの判断で自律的かつサイレントに memory_save を実行し、
  ユーザーへの返答はタスクの完了報告や本題のみに留めてください。
- 情報が不足している、または判断に迷う曖昧なケースでは、
  推測で記憶を保存せず、保存を見送ってください。
  不確実なノイズを長期記憶に混入させないことが優先されます。
</constraints>

<quick_rubric>
memory_save または session_flush を呼び出した後、以下のチェックリストで
自己検証を行い、すべて合格した場合のみ保存を確定してください。

1. **ツール呼び出しの正当性:**
   - [ ] 以下の保存トリガー条件のいずれかに該当するか？
         - memory_save: ユーザー指示の完了後、またはエラー→正常終了への変化直後
         - session_flush: 会話ログの総文字数が 8,000 文字に達した時、またはプロセス終了前
   - [ ] memory_save の場合: 以下のフォーマット要件を満たしているか？
         - Semantic: `[Semantic]` プレフィックス + 「対象」と「事実・ルール・値」のペア
         - Procedural: `[Procedural]` プレフィックス + 「トリガー条件」と「番号付き手順」のペア
   - [ ] session_flush の場合: conversation_log 引数に会話ログ全文を渡しているか？

2. **要約の自己完結性:**
   - [ ] 保存するテキストは、背景状況や会話履歴を参照せずに単体で理解できるか？
   - [ ] 固有名詞・コマンド・パス等の具体的な情報が省略されていないか？
   - [ ] 「先ほどの」「上記の」「これ」等の指示代名詞を含んでいないか？

3. **重複・ノイズの回避:**
   - [ ] 同一セッション内で、実質的に同じ内容を既に memory_save していないか？
   - [ ] 情報が不足・曖昧な場合は、保存を見送る判断をしたか？

いずれかのチェック項目が不合格の場合、保存を取り消すか内容を修正してください。
</quick_rubric>
```

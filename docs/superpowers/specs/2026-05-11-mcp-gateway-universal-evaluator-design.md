# ChronosGraph MCP Gateway — Universal Evaluator (LLM拡張) 設計書

- 作成日: 2026-05-11
- 対象: `src/mcp_gateway/`, `src/context_store/dashboard/routes/`
- 関連既存ドラフト: `docs/future/2026-05-10-mcp-gateway-cli-evaluator.md`
- 設計手法: superpowers/brainstorming スキルによる構造化ブレインストーミング
- ステータス: ユーザー承認済み (design 段階)

## 0. サマリー

ChronosGraph MCP Gateway に、AIエージェント（Claude Code / Gemini CLI 等）の `PreToolUse` Hook から呼び出される **Universal Evaluator CLI** を実装する。既存ドラフト (`2026-05-10-mcp-gateway-cli-evaluator.md`) の deterministic-only な構想に対し、本設計は以下の3点を新規に追加する。

1. **`"ask"` decision** + `ask_message` フィールド (allow/deny に加えて第3の判定)
2. **LLM 評価層** (Anthropic Claude 4.7 系、XMLタグ構造化プロンプト、adaptive thinking)
3. **ChronosGraph 長期記憶との統合** (chronos-dashboard 経由でセマンティック検索)

判定は **二層構造** で実施: Tier 1 で既存 deterministic `PolicyEngine` (intents.yaml + guardrails) を評価し、ALLOW の場合のみ Tier 2 で LLM が記憶を踏まえた最終判定を下す。

## 1. 設計判断 (ブレインストーミング結果)

ユーザーとの対話で確定した4つの基本方針:

| # | 判断項目 | 採択案 | 理由 |
|---|---------|--------|------|
| 1 | LLMと既存PolicyEngineの関係 | **二層**: deterministic 先行 → LLM 詳細判定 | 既存資産を温存しつつ拡張可能 |
| 2 | ContextStore 記憶取得手段 | **HTTP経由**: chronos-dashboard API | 起動高速・DB接続プール共有 |
| 3 | LLM SDK 依存 | **オプション依存**: anthropic 未導入時は警告して allow | dev 環境の UX を破壊しない |
| 4 | コード組織 | **モジュラー分離**: cli/composite/llm/memory を独立ファイル化 | 単一責任・テスト容易性・lazy import 境界明確 |

## 2. アーキテクチャ全体図

```text
┌──────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code / Gemini CLI)                          │
│  PreToolUse Hook → JSON to stdin                              │
└──────────────────┬───────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  $ uv run python -m mcp_gateway evaluate --json-io            │
│                                                               │
│  __main__.py (≤20 行・lazy router)                           │
│    └─→ if argv[1]=='evaluate': from cli import main           │
│        else:                  from app import build_app       │
└──────────────────┬───────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  cli.py                                                       │
│   1. configure_logging(stream=sys.stderr)  ← stdout純度確保  │
│   2. parse stdin JSON  → ToolCallInput                       │
│   3. await composite.evaluate(input) → Decision              │
│   4. json.dump(Decision, sys.stdout); sys.stdout.write("\n")  │
│   5. sys.exit(0)   ← 評価成功時。例外時のみ exit(2)            │
└──────────────────┬───────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  composite.py (CompositeEvaluator)                            │
│  ┌─ Tier 1: deterministic ──────────────────────────────┐    │
│  │  PolicyEngine.evaluate_call() (既存・不変)           │    │
│  │   ├─ DENY    → 即返却                                │    │
│  │   ├─ REQUIRES_APPROVAL → ask に正規化               │    │
│  │   └─ ALLOW   → Tier 2 へ                             │    │
│  └──────────────────────────────────────────────────────┘    │
│  ┌─ Tier 2: LLM (Anthropic 任意) ────────────────────── ┐    │
│  │  1. memory_client.retrieve(query) ← dashboard HTTP   │    │
│  │  2. llm_evaluator.judge(input, rules, memory)        │    │
│  │  3. parse → Decision                                 │    │
│  │  fallback: SDK未導入/キー無し/timeout → ask          │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 Lazy Import 境界 (クリティカル)

| モジュール | import 可能なもの |
|-----------|------------------|
| `__main__.py` | stdlib のみ (`sys`, `argparse`) |
| `cli.py` | `composite`, `models`, `policy.loader` |
| `composite.py` | `policy.engine` (既存), `llm_evaluator`, `memory_client` |
| `llm_evaluator.py` | 関数内で `import anthropic` (ImportError → ask fallback) |
| `memory_client.py` | 関数内で `import httpx` |

**evaluate サブコマンド経路では、`app.py` / `server.py` / `uvicorn` / `fastapi` は決して import されない。**

### 2.2 stdout 純度の二重保証

1. `logging.basicConfig(stream=sys.stderr, level=...)` をプロセス起動直後に実行
2. Anthropic SDK の `httpx` ロガーも明示的に stderr へ再構成
3. 例外時は `traceback.print_exc(file=sys.stderr)` → `json.dump({"decision":"ask","ask_message":"System evaluation failed."}, sys.stdout); sys.stdout.write("\n")` → `sys.exit(2)` のフォーマットで「stdout に必ず JSON」を担保 (※ `print()` は ruff の T201 により全モジュールで禁止)

## 3. LLM 評価プロンプト設計

Claude 4.7 のベストプラクティス (XMLタグ構造化、明示的役割定義、JSON-only 出力強制、adaptive thinking) に準拠。

### 3.1 System Prompt (固定・prompt caching対象)

```xml
<role>
You are the ChronosGraph Universal Evaluator — a security-and-intent gate
that judges whether a proposed local tool call is safe and aligned with the
project's policy and the user's accumulated preferences.
</role>

<task>
Given a tool invocation (already passing deterministic guardrails), inspect:
  1. The tool intent (<tool_intent>): what the agent wants to do
  2. The project's hard rules (<rules>): immutable constraints
  3. Long-term memory (<memory>): user preferences and past decisions

Decide one of:
  - "allow": clearly safe and aligned. Proceed without bothering the user.
  - "deny":  clearly unsafe, destructive, or violates a hard rule.
  - "ask":   ambiguous, unusual, or contradicts recalled preference.
             Default to "ask" when in doubt — false-allow is the worst outcome.
</task>

<output_format>
Respond with EXACTLY one JSON object. No prose, no markdown fences, no
preamble. Schema:
  {"decision": "allow"}
  {"decision": "deny",  "reason":       "<≤200 chars, why blocked>"}
  {"decision": "ask",   "ask_message":  "<≤300 chars, what to confirm>"}
Any other output will be treated as a parse failure and downgraded to "ask".
</output_format>

<priorities>
1. Hard rules in <rules> are absolute. Violation → "deny".
2. Explicit user preferences in <memory> override defaults.
3. When <memory> is empty or irrelevant, judge on tool semantics alone.
4. Never invent facts not present in the provided context.
</priorities>
```

### 3.2 User Prompt Template (動的)

```xml
<tool_intent>
  <tool_name>{tool_name}</tool_name>
  <tool_input>{json.dumps(_redact_tool_input_for_llm(tool_input), ensure_ascii=False)}</tool_input>
  <cwd>{context.cwd or "unknown"}</cwd>
  <agent_id>{context.agent_id or "unknown"}</agent_id>
</tool_intent>

<rules source="intents.yaml" intent="{intent_name}">
  {rendered_guardrail_summary}
</rules>

<memory source="chronos-graph" top_k="{n}">
  {for m in memories:}
  <item type="{m.memory_type}" importance="{m.importance:.2f}">
    {m.content}
  </item>
  {endfor}
</memory>

Decide now. Output JSON only.
```

### 3.3 Anthropic API 呼び出し設定

```python
response = client.messages.create(
    model="claude-haiku-4-5-20251001",   # Hook はミリ秒〜秒オーダー要求 → Haiku 既定
                                          # 環境変数 CHRONOS_EVALUATOR_MODEL で上書き可
    # Anthropic Extended Thinking の制約: max_tokens は thinking.budget_tokens より
    # 厳密に大きい必要がある。max_tokens = budget_tokens(1024) + 可視出力JSON(<512)
    max_tokens=1536,
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},  # 固定 system は prompt-cache
    }],
    messages=[{"role": "user", "content": user_prompt}],
    # adaptive thinking: 複雑な判定だけ深く考えさせる
    thinking={"type": "enabled", "budget_tokens": 1024},
    timeout=httpx.Timeout(10.0, connect=2.0),
)
```

**モデル選定根拠**:

- デフォルト Haiku 4.5: PreToolUse hook は応答が遅いと UX を破壊する (Claude Code は ~60s タイムアウトだが体感1-2秒が許容上限)。Haiku の応答速度が要件にマッチ。
- 環境変数で `claude-sonnet-4-6` / `claude-opus-4-7` に切替可能 (重要環境用)。

**prompt caching**:

- system プロンプトは固定 → `cache_control: ephemeral` でヒット率最大化
- 2回目以降の hook 呼び出しで入力トークンを ~90% 削減

**thinking の効果**:

- "rm -rf" のような明白な denial は thinking 不要 → モデルが短時間で応答
- "user wants to delete config but memory says 'always confirm config edits'" のような葛藤は thinking budget が活きる

## 4. コンポーネント詳細仕様

### 4.1 `src/mcp_gateway/cli.py` (新規)

**責務**: stdin から JSON 読取、`composite.evaluate()` 呼び出し、stdout に JSON 出力、終了コード制御。

```python
def main(argv: list[str] | None = None) -> int:
    """argparse で --json-io / --policy-path / --intent を受け、評価結果を返す。
    返り値はそのまま sys.exit() に渡される (0 or 2)。
    """

# 内部関数 (テスト容易性のため分離)
def _configure_stderr_logging(level: str) -> None: ...
def _read_input(stream: IO[str]) -> ToolCallInput: ...
def _write_decision(decision: Decision, stream: IO[str]) -> None: ...
def _emit_fallback_ask(message: str, stream: IO[str]) -> None: ...
```

**起動時の固定処理順**:

1. `_configure_stderr_logging()` → 全 logger を stderr へ
2. argv パース (最小限の argparse、subparser なし、`evaluate` は `__main__` 側で振り分け済み)
3. stdin 全読取 → JSON parse → `ToolCallInput` (pydantic)
4. parse 失敗 → fallback ask、`exit(2)`
5. `asyncio.run(composite.evaluate(input))` → `Decision`
6. `_write_decision()` → `json.dump(decision.to_dict(), sys.stdout); sys.stdout.write("\n")` (※ `print()` は使わない / ruff T201 で禁止)
7. `exit(0)`
8. try/except でこの全体を包み、未捕捉例外時は `_emit_fallback_ask()` + `exit(2)`

**fail-safe 不変条件**:

- どんなコードパスでも stdout には JSON 1 行のみ出力される
- 例外時も `{"decision":"ask","ask_message":"System evaluation failed. Human confirmation required."}` を必ず吐く

### 4.2 `src/mcp_gateway/__main__.py` (修正)

**責務**: サブコマンドを見て `cli.main` or `serve` (現行 uvicorn 起動) に振り分け。

```python
def main() -> None:
    # 1. 最低限の argv 検査 (stdlib のみ・lazy)
    if len(sys.argv) >= 2 and sys.argv[1] == "evaluate":
        from mcp_gateway.cli import main as cli_main
        sys.exit(cli_main(sys.argv[2:]))

    # 2. 旧来の動作 (uvicorn) は default として残す
    _serve()  # 現行 main() の中身をここに移す
```

**後方互換性**: `python -m mcp_gateway` (引数なし) は従来通り uvicorn 起動。evaluate サブコマンドは新規パスでのみ追加。

### 4.3 `src/mcp_gateway/policy/composite.py` (新規)

**責務**: Tier 1 (deterministic) と Tier 2 (LLM) を直列に実行し、最終 Decision を返す。

> **実装注記**: 以下の `ToolCallInput` / `Decision` は本 spec ではインライン定義として示すが、実装計画では循環 import 回避のため `src/mcp_gateway/policy/models_evaluator.py` に集約する。同モジュールにマスキングユーティリティ (`_summarize_tool_input`, `_redact_tool_input_for_llm`) も含む。

```python
@dataclass(frozen=True, slots=True)
class ToolCallInput:
    tool_name: str
    tool_input: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    # context は agent_id, cwd, session_id 等を含む任意dict

@dataclass(frozen=True, slots=True)
class Decision:
    decision: Literal["allow", "deny", "ask"]
    reason: str | None = None         # decision="deny" のみ
    ask_message: str | None = None    # decision="ask" のみ

    def to_dict(self) -> dict[str, Any]: ...  # None フィールドは除外

class CompositeEvaluator:
    def __init__(
        self,
        policy: GatewayPolicy,
        memory_client: MemoryClient | None,
        llm_evaluator: LlmEvaluator | None,
        default_intent: str = "default",
    ) -> None: ...

    async def evaluate(self, input: ToolCallInput) -> Decision: ...
```

**判定フロー (擬似コード)**:

```python
async def evaluate(self, input):
    # Tier 1
    try:
        grant = self._build_implicit_grant(input)  # 引数の agent_id + intent → Grant
        tier1 = self._engine.evaluate_call(
            grant=grant, tool_name=input.tool_name, arguments=input.tool_input
        )
    except PolicyError as exc:
        return Decision(decision="deny", reason=exc.reason or "policy_violation")

    if tier1.status == "DENY":
        return Decision(decision="deny", reason=tier1.reason or "guardrail_violation")

    if tier1.status == "REQUIRES_APPROVAL":
        # ALLOW を待つまでもなく LLM に進む価値が低い → 直接 ask
        return Decision(
            decision="ask",
            ask_message=f"Tool {input.tool_name!r} requires manual approval.",
        )

    # Tier 1 = ALLOW
    if self._llm is None:  # LLM 構成なし (extras 未インストール / キー無し)
        return Decision(decision="allow")  # deterministic が許可なら通す

    # Tier 2
    try:
        memories = await self._fetch_memories(input)  # 失敗時は []
        rules = self._render_rules_for_prompt(grant, input.tool_name)
        return await self._llm.judge(input, rules, memories)
    except (LlmUnavailableError, MemoryFetchError, ResponseParseError) as exc:
        logger.warning("Tier-2 fallback to ask: %s", exc)
        return Decision(
            decision="ask",
            ask_message="System evaluation failed. Human confirmation required.",
        )
```

**設計判断**:

- LLM 評価器が None の場合は deterministic ALLOW を尊重して allow を返す (fail-open ではなく "deterministic 判定への信頼" として明示)。`ask` への退避はあくまで LLM を呼ぼうとして失敗した時のみ。これにより API キー未設定の dev 環境で hook が常時 ask になって UX が破壊されることを防ぐ。
- ただし「dev 環境でもより安全側に倒したい」場合は環境変数 `CHRONOS_EVALUATOR_FALLBACK=ask` で挙動切替可能。
- **本番環境では `CHRONOS_EVALUATOR_FALLBACK=ask` を推奨** (§5.3 環境変数表参照)。LLM 評価が黙って無効化されているリスクを排除するため。

**起動時の構成ログ (必須)**:

`CompositeEvaluator.__init__` の末尾で、評価器構成を **必ず stderr ロガーに 1 行出力** する。これにより運用者が hook 経由のログから「LLM 有効/無効」「フォールバック方針」を即座に検知できる。

```python
class CompositeEvaluator:
    def __init__(self, policy, memory_client, llm_evaluator, default_intent="default",
                 fallback_when_llm_unavailable: Literal["allow", "ask"] = "allow") -> None:
        self._policy = policy
        self._memory = memory_client
        self._llm = llm_evaluator
        self._default_intent = default_intent
        self._fallback = fallback_when_llm_unavailable

        # 構成サマリーを WARNING で出して必ず見えるようにする (INFO だと運用者が見落とす)
        logger.warning(
            "evaluator config: llm=%s memory=%s fallback_when_llm_unavailable=%s",
            "enabled" if llm_evaluator is not None else "DISABLED",
            "enabled" if memory_client is not None else "disabled",
            self._fallback,
        )
```

→ `self._llm is None` のとき、`evaluate()` 内では `self._fallback` を参照し、`"ask"` なら ask、`"allow"` (デフォルト) なら allow を返す。

### 4.4 `src/mcp_gateway/policy/llm_evaluator.py` (新規)

**責務**: Anthropic SDK 呼び出し + プロンプト構築 + 応答 parse。Lazy import で `anthropic` 未インストール時は `LlmUnavailableError` を投げる。

```python
class LlmUnavailableError(Exception): ...
class ResponseParseError(Exception): ...

class LlmEvaluator:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout_seconds: float = 10.0,
        thinking_budget: int = 1024,
    ) -> None: ...

    @classmethod
    def from_env(cls) -> "LlmEvaluator | None":
        """env から構築。ANTHROPIC_API_KEY 未設定や anthropic 未導入時は None。"""

    async def judge(
        self,
        input: ToolCallInput,
        rules: str,
        memories: Sequence[MemoryItem],
    ) -> Decision: ...
```

**実装ポイント**:

- `from_env()` 内で `import anthropic` を試み、ImportError → None
- `judge()` 内で system prompt は固定文字列 (`cache_control: ephemeral`)
- 応答 parse: `content[0].text` を `json.loads` → 失敗時 `ResponseParseError`
- decision フィールド検証: `Literal["allow","deny","ask"]` 以外 → `ResponseParseError`
- 全ログは `logger = logging.getLogger("chronos_evaluator.llm")` 経由 (cli.py で stderr に統一)

### 4.5 `src/mcp_gateway/policy/memory_client.py` (新規)

**責務**: chronos-dashboard の `POST /api/memories/semantic-search` (新規追加) を叩いて Top-K の関連記憶を取得。

> **実装注記**: 以下の `MemoryItem` は本 spec ではインライン定義として示すが、実装計画では `src/mcp_gateway/policy/models_evaluator.py` に集約する (§4.3 注記参照)。

```python
@dataclass(frozen=True, slots=True)
class MemoryItem:
    content: str
    memory_type: str
    importance: float

class MemoryFetchError(Exception): ...

class MemoryClient:
    def __init__(
        self,
        dashboard_url: str,
        timeout_seconds: float = 3.0,
        top_k: int = 5,
    ) -> None: ...

    @classmethod
    def from_env(cls) -> "MemoryClient | None":
        """env CHRONOS_DASHBOARD_URL 未設定なら None (memory なしで進む)。"""

    async def retrieve(self, query: str, project: str | None = None) -> list[MemoryItem]: ...
```

**クエリ構築規約** (composite.py で実施):

```python
query = f"tool:{input.tool_name} " + _summarize_tool_input(input.tool_input)
# 例: "tool:bash command=rm -rf /tmp/foo"
# 仕様 (§5.4 の _summarize_tool_input 実装と一致):
#   - 各値 (str(v)) を MAX_VALUE_LENGTH (200文字) で切り詰め (全体長制限ではない)
#   - 機微キー (password/passwd/secret/token/api_key/authorization/bearer/credential)
#     にマッチする key の値は <REDACTED> で完全置換
#   - 注意: キー名ベースのマスキングのため、value の内部に秘密が埋め込まれている
#     ケースは検出不可。詳細は §5.4「限界の明記」参照
```

### 4.6 dashboard 側の拡張 (3ファイル修正)

**前提コード調査結果**:

- `api_server.py` に `app.state.orchestrator` は **存在しない** (`app.state.service: DashboardService` のみ)
- 既存 `DashboardService.search_memories(MemoryFilters)` は **filter-based 検索** であり `query` 文字列を受け取れない (ベクトル類似度検索ではない)

そのため、orchestrator を直接エンドポイントから参照する初期案は破棄し、**`DashboardService` に新メソッド `semantic_search()` を追加** して既存パターン (Service が読み取りロジックを集約) に合わせる。

#### 4.6.1 `src/context_store/dashboard/services.py` (修正)

`DashboardService` に retrieval_pipeline を注入し、`semantic_search()` メソッドを追加:

```python
class DashboardService:
    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
        retrieval_pipeline: "RetrievalPipeline | None" = None,  # 新規 (任意)
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._retrieval = retrieval_pipeline

    # 新規メソッド
    async def semantic_search(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 5,
    ) -> list[Memory]:
        """ベクトル類似度ベースのセマンティック検索。
        retrieval_pipeline が None なら HTTPException(503) を投げる。"""
        if self._retrieval is None:
            raise RuntimeError("retrieval_pipeline not configured for this dashboard")
        resp = await self._retrieval.search(query=query, project=project, top_k=top_k)
        return resp.memories
```

#### 4.6.2 `src/context_store/dashboard/api_server.py` (修正)

dashboard は現状 `Orchestrator` を起動しない (`app.state.service` は `storage` / `graph` のみで構築されている read-only エントリ) ため、本設計では **`RetrievalPipeline` を dashboard 内で単独に組み立てて** `DashboardService` に注入する。`Orchestrator` への新規依存は導入しない。

```python
# 既存
app.state.service = DashboardService(storage=storage, graph=graph)
# ↓ 修正 (lifespan 内)
retrieval_pipeline = None
try:
    from context_store.retrieval.pipeline import RetrievalPipeline

    retrieval_pipeline = await RetrievalPipeline.create_for_dashboard(
        storage=storage,
        graph=graph,
        settings=settings,
    )
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "RetrievalPipeline could not be initialized for dashboard "
        "(semantic-search endpoint will return 503): %s",
        exc,
    )

app.state.service = DashboardService(
    storage=storage,
    graph=graph,
    retrieval_pipeline=retrieval_pipeline,
)
```

**実装の前提**:

- `src/context_store/retrieval/pipeline.py` に **共通ビルダー `RetrievalPipeline.create_from_parts()` (または `create()`) を実装** し、`Orchestrator` (`orchestrator.py`) の組み立てロジックをここに集約・リファクタリングする。
- ダッシュボード用の `RetrievalPipeline.create_for_dashboard()` は、この共通ビルダーを呼び出す薄いラッパーとして実装する。これにより、将来的なコンポーネント構成変更時の同期漏れを物理的に防止する。
- 初期化に失敗した場合は `retrieval_pipeline=None` のまま service を構築し、後続の `POST /api/memories/semantic-search` は HTTP 503 を返す (§4.6.3 の `RuntimeError → 503` 経路)。dashboard 自体の起動は阻害しない。
- 当初案として検討された「`Orchestrator` に `retrieval_pipeline` を public property として公開し、dashboard から再利用する」アプローチは、**dashboard が現状 `Orchestrator` を import していないため new dependency を生む** こと、および `Orchestrator` 起動が ingestion / lifecycle まで巻き込み dashboard 単独起動を重くすることを理由に採用しない。本設計では `Orchestrator` 側コードは一切変更しない。

#### 4.6.3 `src/context_store/dashboard/routes/memories.py` (修正・追加エンドポイント)

```python
@router.post("/semantic-search", response_model=list[MemoryResponse])
async def semantic_search_memories(
    req: SemanticSearchRequest,  # 新規 schema: {query, project?, top_k=5}
    request: Request,
) -> list[MemoryResponse]:
    """ベクトル類似度ベースのセマンティック検索を HTTP で公開する read-only エンドポイント。
    内部で DashboardService.semantic_search() → RetrievalPipeline.search() に委譲する。
    既存の filter-based `/search` とは別経路 (破壊変更なし)。"""
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    try:
        memories = await service.semantic_search(
            query=req.query, project=req.project, top_k=req.top_k
        )
    except RuntimeError as exc:
        # retrieval_pipeline 未注入の dashboard (古い起動構成) は 503
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return [
        MemoryResponse(
            id=str(m.id),
            content=m.content,
            memory_type=m.memory_type,
            importance=m.importance_score,
            project=m.project,
            access_count=m.access_count,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in memories
    ]
```

**注意点**:

- 既存 `/search` は filter-based 検索のため、破壊変更せず別エンドポイントとして追加
- `DashboardService` に retrieval_pipeline を注入しない既存呼び出し箇所はデフォルト引数 `None` で互換性維持 (テスト等)
- 認証: dashboard が `--auth` 起動時のみ認証要件あり。CLI は同じ認証を受け継ぐため、`CHRONOS_DASHBOARD_API_KEY` で送る
- `SemanticSearchRequest` schema は `src/context_store/dashboard/schemas.py` に新設 (`query: str`, `project: str | None = None`, `top_k: int = 5`)

## 5. エラー処理・フォールバック仕様

### 5.1 stdout 純度の三重保証

```python
# cli.py の main() 冒頭、最初に実行
import logging
import sys

def _configure_stderr_logging(level: str = "WARNING") -> None:
    root = logging.getLogger()
    # 既存ハンドラを全て撤去 (uvicorn / anthropic / httpx が後付けする stdout ハンドラを潰す)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)

    # 特に noisy なライブラリを WARNING に固定
    for name in ("httpx", "httpcore", "anthropic", "asyncio"):
        logging.getLogger(name).setLevel("WARNING")
```

**追加防御策**:

1. **`print()` 禁止規約**: cli/composite/llm/memory **すべてのモジュールで `print` を禁止**。ruff の `flake8-print` (`T201`) を **グローバル有効化** (`extend-select = ["T20"]`) し、`per-file-ignores` で T201 を無効化するエントリーは追加しない。stdout への出力は `json.dump(obj, sys.stdout)` + `sys.stdout.write("\n")` で行う。stderr への出力は logger 経由
2. **stdout flush 直前検証**: テストでは `capsys.readouterr().out` がちょうど1行の JSON であることをアサート
3. **Anthropic SDK の thinking 出力**: `thinking` ブロックは `response.content[0]` ではなく別チャネル → text の `json.loads` だけ走らせれば自然と分離される。明示的に `[block for block in response.content if block.type == "text"]` でフィルタする

### 5.2 fallback 状態遷移表

| ケース | Tier 1 状態 | Tier 2 状態 | 返却 Decision | exit code |
|--------|------------|------------|---------------|-----------|
| stdin JSON parse失敗 | — | — | `ask` (System evaluation failed.) | **2** |
| 未知の agent_id / intent | DENY 相当(PolicyError) | スキップ | `deny` (policy_violation) | 0 |
| deterministic guardrail 違反 | DENY | スキップ | `deny` (理由文付き) | 0 |
| guardrail で `requires_approval` | REQUIRES_APPROVAL | スキップ | `ask` (Tool X requires manual approval.) | 0 |
| deterministic ALLOW + LLM 未構成 (anthropic未導入 or キー無し) | ALLOW | 構成なし | `allow` | 0 |
| deterministic ALLOW + dashboard HTTP 失敗 | ALLOW | memory fetch失敗 | LLM 続行 (memory=[]) | 0 |
| deterministic ALLOW + LLM タイムアウト | ALLOW | timeout | `ask` (System evaluation failed.) | 0 |
| deterministic ALLOW + LLM 応答非JSON | ALLOW | parse 失敗 | `ask` (System evaluation failed.) | 0 |
| deterministic ALLOW + LLM `{"decision":"foo"}` | ALLOW | 不明な decision | `ask` (System evaluation failed.) | 0 |
| deterministic ALLOW + LLM 正常応答 | ALLOW | OK | LLM の Decision そのまま | 0 |
| **想定外例外 (catch-all)** | — | — | `ask` (System evaluation failed.) | **2** |

**exit code 設計の意図**:

- **0** = 「評価プロセスは正常完了し、stdout の JSON を見て判断せよ」
- **2** = 「評価プロセス自体が壊れた。hook 側は安全側に倒して block 扱いせよ」
- `ask` でも基本 exit 0 (hook は stdout を信頼) だが、stdin parse 失敗・catch-all だけは「stdout 信頼できない可能性あり」として exit 2 を併用

### 5.3 環境変数仕様

| 環境変数 | デフォルト | 本番推奨値 | 用途 |
|---------|----------|----------|------|
| `ANTHROPIC_API_KEY` | (未設定) | **設定必須** | 未設定なら LLM 評価をスキップ |
| `CHRONOS_EVALUATOR_MODEL` | `claude-haiku-4-5-20251001` | (デフォルト可) | LLM モデル切替 |
| `CHRONOS_EVALUATOR_TIMEOUT_SECONDS` | `10.0` | (デフォルト可) | LLM 呼び出しタイムアウト |
| `CHRONOS_EVALUATOR_THINKING_BUDGET` | `1024` | (デフォルト可) | adaptive thinking のトークン上限 |
| `CHRONOS_DASHBOARD_URL` | (未設定) | **設定必須** | 未設定なら memory 取得をスキップ |
| `CHRONOS_DASHBOARD_API_KEY` | (未設定) | **設定必須** (--auth 時) | dashboard 認証ヘッダ |
| `CHRONOS_DASHBOARD_TIMEOUT_SECONDS` | `3.0` | (デフォルト可) | dashboard HTTP (semantic-search) 呼び出しタイムアウト |
| `CHRONOS_DASHBOARD_TOP_K` | `5` | (デフォルト可) | semantic-search で取得する記憶の件数 |
| `CHRONOS_EVALUATOR_FALLBACK` | `allow` | **`ask` を強く推奨** | LLM 未構成時の挙動。`ask` にすると黙って無効化されるリスクを排除 |
| `CHRONOS_EVALUATOR_POLICY_PATH` | (必須) | **設定必須** | intents.yaml のパス |
| `CHRONOS_EVALUATOR_DEFAULT_INTENT` | `default` | (環境次第) | input.context.intent 未指定時の既定 |
| `CHRONOS_EVALUATOR_DEFAULT_AGENT_ID` | `claude-code` | (環境次第) | input.context.agent_id 未指定時の既定 |
| `CHRONOS_EVALUATOR_LOG_LEVEL` | `WARNING` | (デフォルト可) | stderr ログレベル |

**設計判断**: `--policy-path` 等の argparse オプションも提供する。環境変数はデフォルト値として使用し、CLI 引数が明示指定された場合は CLI が優先される (argparse 標準動作)。PreToolUse Hook の `settings.json` にコマンドラインを固定記述する運用では、env は fallback として機能する。

### 5.4 機微情報マスキング (memory 検索 + LLM プロンプト送信)

**マスキングは2箇所で必須**:

1. **memory_client へのクエリ構築時** (composite.py): `_summarize_tool_input()` — 文字列化版
2. **LLM プロンプト構築時** (llm_evaluator.py): `_redact_tool_input_for_llm()` — JSON 構造保持版

LLM はネスト構造を保ったまま渡された方が解釈精度が高いため、用途別に2関数を提供する。共通の `SENSITIVE_KEY_PATTERN` を再利用する。

```python
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|bearer|credential)",
    re.IGNORECASE,
)
MAX_VALUE_LENGTH = 200
REDACTED_MARKER = "<REDACTED>"

def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_PATTERN.search(key))


def _truncate(value: str) -> str:
    if len(value) > MAX_VALUE_LENGTH:
        return value[:MAX_VALUE_LENGTH] + "...[truncated]"
    return value


# (A) memory 検索クエリ用 (文字列出力)
def _summarize_tool_input(d: dict[str, Any]) -> str:
    parts = []
    for k, v in d.items():
        if _is_sensitive_key(k):
            parts.append(f"{k}={REDACTED_MARKER}")
            continue
        parts.append(f"{k}={_truncate(str(v))}")
    return " ".join(parts)


# (B) LLM プロンプト用 (JSON 構造を保ったままキーレベルでマスク・再帰)
def _redact_tool_input_for_llm(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (REDACTED_MARKER if _is_sensitive_key(k) else _redact_tool_input_for_llm(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_tool_input_for_llm(v) for v in obj]
    if isinstance(obj, str):
        return _truncate(obj)
    return obj
```

**設計上の不変条件**:

- LLM プロンプトに埋め込む `<tool_input>` は **必ず `_redact_tool_input_for_llm()` を経由**する (§3.2 のテンプレート参照)
- メモリ検索クエリに埋め込む文字列も **必ず `_summarize_tool_input()` を経由**する (§4.5 参照)
- ユニットテストで `password` / `api_key` などのキーが含まれる入力に対し、生成プロンプト/クエリ両方に `<REDACTED>` が含まれることを assert する

**限界の明記**:

本マスキングは **キー名ベース** のため、**値 (value) の内部に秘密が埋め込まれているケースは任意のツールで検出不可**。これは `bash` 固有の問題ではなく、任意の文字列値を受け取るすべてのツールで発生しうる構造的限界。

**典型的な値埋め込みパターン (検出不可)**:

| ツール例 | 検出不可な入力 | 漏洩する内容 |
|---------|--------------|------------|
| `bash` | `{"command": "export AWS_SECRET_ACCESS_KEY=xxx"}` | コマンド文字列内の秘密 |
| `python` / `node` 等の任意コード実行 | `{"script": "client = OpenAI(api_key='sk-...')"}` | スクリプト内のリテラル |
| Slack / メール送信系 | `{"message": "API key is sk-..."}` | メッセージ本文に書かれた値 |
| HTTP 系 (`curl` / `fetch`) | `{"url": "https://user:pass@host/path"}` | URL の userinfo 部 |
| `write_file` / `replace` | `{"content": "DB_PASSWORD=..."}` | 書き込み内容 |

**高リスクツール群** (運用レベルでの追加対策を**必須**とする):

- **任意コマンド/コード実行系**: `bash`, `sh`, `zsh`, `python`, `node`, `ruby`, `perl`, `eval` など
- **任意 HTTP 系**: `curl`, `wget`, `fetch`, `httpie`
- **任意ファイル書き込み系**: `write_file`, `replace`, `Edit`, `Write`

**追加対策の選択肢** (高リスクツールには以下のいずれかを必須適用):

1. **hook 対象から除外**: クライアント側 `matcher` で該当ツールを評価対象外にする
2. **前段マスキング hook**: 別 hook で値の AST 解析・URL parse・正規表現スキャン等を行い、本 evaluator にはサニタイズ済みデータを渡す
3. **ツール側での秘密検出**: ツール実装側で値スキャナ (例: `truffleHog`, `gitleaks` の patterns) を組み込み、検出時は実行前に拒否

**設計書内の連動箇所**:

- §4.5 `memory_client` クエリ構築のコメント (line 388-397) でも本限界に言及済み (Inline 1 対応で更新済み)
- README には「高リスクツール群の hook 構成例 (除外 or 前段マスキング)」を必ず記載する

### 5.5 LLM 応答パースの厳格化

```python
def _parse_decision(text: str) -> Decision:
    # 1. JSON だけを抽出 (前後の空白/改行のみ許容)
    text = text.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ResponseParseError(f"non-JSON response: {text[:80]!r}")

    # 2. 厳密 parse
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ResponseParseError(f"invalid JSON: {e}") from e

    # 3. schema 検証
    if not isinstance(obj, dict):
        raise ResponseParseError(f"top-level must be object, got {type(obj).__name__}")
    decision = obj.get("decision")
    if decision not in ("allow", "deny", "ask"):
        raise ResponseParseError(f"unknown decision: {decision!r}")

    # 4. 整合性
    if decision == "deny":
        reason = obj.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ResponseParseError("deny requires non-empty 'reason'")
        return Decision(decision="deny", reason=reason[:200])
    if decision == "ask":
        msg = obj.get("ask_message")
        if not isinstance(msg, str) or not msg.strip():
            raise ResponseParseError("ask requires non-empty 'ask_message'")
        return Decision(decision="ask", ask_message=msg[:300])
    return Decision(decision="allow")
```

## 6. テスト戦略 (Devcontainer 強制実行)

### 6.1 テストファイル構成

```text
tests/
├── unit/
│   ├── test_mcp_gateway_cli.py             # 新規: argv/stdin/stdout/exit code 検証
│   ├── test_mcp_gateway_composite.py       # 新規: Tier1+Tier2 のフロー (mock LLM, mock memory)
│   ├── test_mcp_gateway_llm_evaluator.py   # 新規: プロンプト構築・応答 parse
│   ├── test_mcp_gateway_memory_client.py   # 新規: httpx mock で dashboard 通信
│   └── test_mcp_gateway.py                 # 既存: 変更なし
└── integration/
    └── test_evaluator_cli_subprocess.py    # 新規: subprocess.run で実プロセス E2E
```

### 6.2 ユニットテスト必須ケース

**`test_mcp_gateway_cli.py`**:

| ケース | 検証内容 |
|--------|---------|
| 正常 allow | stdin に valid JSON → stdout に `{"decision":"allow"}` 1行 + exit 0 |
| 正常 deny | mock composite が deny 返却 → stdout に reason 付き JSON + exit 0 |
| 正常 ask | mock composite が ask 返却 → stdout に ask_message 付き JSON + exit 0 |
| stdin 空 | exit 2 + stdout に fallback ask JSON |
| stdin 不正 JSON | exit 2 + stdout に fallback ask JSON |
| composite が想定外例外 | exit 2 + stdout に fallback ask JSON + stderr に traceback |
| stdout 純度 | `capsys.readouterr().out` がちょうど1行の JSON (logger 出力が混ざらない) |
| logger が stderr へ流れる | `logger.warning("test")` が `capsys.readouterr().err` に出る |

**`test_mcp_gateway_composite.py`** (Tier 1/2 マトリクス全網羅):

- deterministic DENY → Tier 2 呼ばれない・LLM mock が0回呼ばれることを assert
- deterministic ALLOW + LLM未構成 → allow 返却
- deterministic ALLOW + LLM allow → allow 返却
- deterministic ALLOW + LLM deny → deny 返却
- deterministic ALLOW + LLM ask → ask 返却
- deterministic ALLOW + memory_client が None → memories=[] で LLM 呼び出し
- deterministic ALLOW + memory_client が例外 → memories=[] で LLM 呼び出し (失敗を握りつぶす)
- deterministic ALLOW + LLM 例外 → fallback ask
- deterministic REQUIRES_APPROVAL → 直接 ask、LLM呼ばない

**`test_mcp_gateway_llm_evaluator.py`**:

- system prompt に `cache_control: ephemeral` が含まれる
- user prompt に `<tool_intent>`, `<rules>`, `<memory>` タグが含まれる
- 機微キーがマスクされている (`password=<REDACTED>`)
- 応答 `{"decision":"allow"}` → Decision allow
- 応答 `{"decision":"deny","reason":"x"}` → Decision deny
- 応答 `{"decision":"ask","ask_message":"x"}` → Decision ask
- 応答 `{"decision":"foo"}` → ResponseParseError
- 応答 `not json` → ResponseParseError
- 応答 `{"decision":"deny"}` (reason 欠落) → ResponseParseError
- `anthropic` 未 import → `from_env()` が None を返す
- API キー未設定 → `from_env()` が None を返す

### 6.3 統合テスト (subprocess E2E)

```python
import json, subprocess, sys

def test_cli_evaluate_deny_path():
    payload = {"tool_name": "bash", "tool_input": {"command": "rm -rf /"}}
    result = subprocess.run(
        [sys.executable, "-m", "mcp_gateway", "evaluate", "--json-io",
         "--policy-path", str(POLICY_PATH)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "ANTHROPIC_API_KEY": "", "CHRONOS_DASHBOARD_URL": ""},
    )
    assert result.returncode == 0
    decision = json.loads(result.stdout.strip())
    assert decision["decision"] == "deny"
    # stdout に余計な出力がないこと
    assert result.stdout.count("\n") == 1
```

API キーを `""` でクリアした状態で実行することで、LLM 未構成パスを CI で安定検証可能。

### 6.4 Devcontainer 強制実行スクリプト

新規ファイル `scripts/check_evaluator.sh`:

```bash
#!/usr/bin/env bash
# 評価CLIに関する全静的解析・テストをDevcontainer内で実行する。
# 既存 Devcontainer 環境 (.devcontainer/devcontainer.json) 内でのみ動作することを前提とする。
set -euo pipefail

# 検知ロジック (意図的に「特定の Devcontainer」のみ許可):
#  - REMOTE_CONTAINERS=true : VS Code "Reopen in Container"
#  - CODESPACES=true        : GitHub Codespaces
#  - DEVCONTAINER=1         : devcontainer CLI 利用時に手動 export または
#                             .devcontainer/setup.sh で自動 export される
# 注意: /.dockerenv や /proc/1/cgroup の検知は使わない。
#       それらは「任意の Docker コンテナ」で pass してしまい、本プロジェクトの
#       devcontainer ではない環境 (例: docker run python:3.12 ...) でも通過するため、
#       依存性が揃わない環境でのテスト誤実行を招く。
if [ -z "${REMOTE_CONTAINERS:-}${CODESPACES:-}${DEVCONTAINER:-}" ]; then
    echo "ERROR: must run inside the project Devcontainer." >&2
    echo "       REMOTE_CONTAINERS / CODESPACES / DEVCONTAINER のいずれも未設定です。" >&2
    echo "" >&2
    echo "  対処方法:" >&2
    echo "    [VS Code]        'Reopen in Container' を選択" >&2
    echo "    [Codespaces]     自動的に CODESPACES=true が設定される" >&2
    echo "    [devcontainer CLI] 以下のいずれか:" >&2
    echo "        - DEVCONTAINER=1 を手動 export" >&2
    echo "        - .devcontainer/setup.sh が新しい場合は自動 export される" >&2
    exit 1
fi

echo "==> ruff check"
uv run ruff check src/mcp_gateway/cli.py \
                  src/mcp_gateway/policy/composite.py \
                  src/mcp_gateway/policy/llm_evaluator.py \
                  src/mcp_gateway/policy/memory_client.py \
                  tests/unit/test_mcp_gateway_cli.py \
                  tests/unit/test_mcp_gateway_composite.py \
                  tests/unit/test_mcp_gateway_llm_evaluator.py \
                  tests/unit/test_mcp_gateway_memory_client.py \
                  tests/integration/test_evaluator_cli_subprocess.py

echo "==> ruff format --check"
uv run ruff format --check src/mcp_gateway tests/unit/test_mcp_gateway_*.py

echo "==> mypy"
uv run mypy src/mcp_gateway

echo "==> pytest (unit)"
uv run pytest tests/unit/test_mcp_gateway_cli.py \
              tests/unit/test_mcp_gateway_composite.py \
              tests/unit/test_mcp_gateway_llm_evaluator.py \
              tests/unit/test_mcp_gateway_memory_client.py -v

echo "==> pytest (integration, subprocess E2E)"
uv run pytest tests/integration/test_evaluator_cli_subprocess.py -v

echo "==> all checks passed"
```

**Devcontainer 外実行を防ぐガード**: 冒頭の env check で `REMOTE_CONTAINERS` / `CODESPACES` / `DEVCONTAINER` のいずれも未設定なら exit 1。CLAUDE.md 制約3 への準拠。

**ホスト側のドキュメント手順** (README に追記):

```bash
# (ホスト) Devcontainer を開く
$ code .       # 「Reopen in Container」を選択
# (Devcontainer 内)
$ bash scripts/check_evaluator.sh
```

### 6.5 pyproject.toml 修正

```toml
[project.optional-dependencies]
evaluator = [
    "anthropic>=0.40.0",  # adaptive thinking 対応バージョン
    "httpx>=0.27.0",      # memory_client 用 (既に dependencies に存在)
]

[tool.ruff.lint]
# T20 (flake8-print) をグローバルに有効化。stdout 純度を ruff レベルで強制する。
# cli/composite/llm/memory のいずれのファイルでも T201 を無効化するエントリーは
# 追加しない。stdout 出力は print() ではなく json.dump(obj, sys.stdout) +
# sys.stdout.write("\n") で行う。stderr 出力は logger 経由。
extend-select = ["T20"]

# 注意: [tool.ruff.lint.per-file-ignores] に "T201" を追加してはならない。
# Issue 1 (per-file-ignores 反転バグ) の再発防止のため、cli.py を含む
# evaluator 系モジュールはすべて T201 強制対象とする。
```

### 6.6 既存テストへの影響

- `tests/unit/test_mcp_gateway.py` (既存): 変更なし — 既存 `PolicyEngine` は不変
- `tests/unit/test_param_constraint.py` (既存): 変更なし
- 新規モジュールは既存 import パスに影響しない (composite/llm/memory は新規ファイル)

### 6.7 CI 統合

実装計画 Phase 0 で `.github/workflows/ci.yml` を新設し、`master` へのプッシュ/PR で `ubuntu-slim` ランナー上の自動テスト (ruff / mypy / pytest) を実行する。加えて `.devcontainer/setup.sh` に `export DEVCONTAINER=1` を追記し、Phase 6 の `scripts/check_evaluator.sh` が Devcontainer を検知できるようにする。

## 7. 変更ファイル一覧

| 種別 | パス | 規模 |
|------|------|------|
| 新規 | `src/mcp_gateway/policy/models_evaluator.py` | ~90 行 (`ToolCallInput`, `Decision`, `MemoryItem`, マスキングユーティリティ集約) |
| 新規 | `src/mcp_gateway/cli.py` | ~150 行 |
| 修正 | `src/mcp_gateway/__main__.py` | +5 / -0 行 |
| 新規 | `src/mcp_gateway/policy/composite.py` | ~200 行 |
| 新規 | `src/mcp_gateway/policy/llm_evaluator.py` | ~180 行 |
| 新規 | `src/mcp_gateway/policy/memory_client.py` | ~100 行 |
| 修正 | `src/context_store/dashboard/routes/memories.py` | +35 行 (新規 endpoint) |
| 修正 | `src/context_store/dashboard/services.py` | +20 行 (`semantic_search()` メソッド + コンストラクタ拡張) |
| 修正 | `src/context_store/dashboard/api_server.py` | +25 行 (lifespan で `RetrievalPipeline.create_for_dashboard` を呼び `DashboardService` に注入) |
| 修正 | `src/context_store/dashboard/schemas.py` | +10 行 (`SemanticSearchRequest`) |
| 修正 | `src/context_store/retrieval/pipeline.py` | +30 行 (`create_for_dashboard` ファクトリ追加) |
| 修正 | `pyproject.toml` | +10 行 (extras + ruff 設定) |
| 新規 | `tests/unit/test_mcp_gateway_cli.py` | ~200 行 |
| 新規 | `tests/unit/test_mcp_gateway_composite.py` | ~250 行 |
| 新規 | `tests/unit/test_mcp_gateway_llm_evaluator.py` | ~200 行 |
| 新規 | `tests/unit/test_mcp_gateway_memory_client.py` | ~100 行 |
| 新規 | `tests/unit/test_dashboard_semantic_search.py` | ~80 行 (DashboardService 拡張のユニット) |
| 新規 | `tests/integration/test_evaluator_cli_subprocess.py` | ~150 行 |
| 新規 | `scripts/check_evaluator.sh` | ~60 行 |
| 新規 | `.github/workflows/ci.yml` | ~40 行 (master トリガー + ubuntu-slim + ruff/mypy/pytest) |
| 修正 | `.devcontainer/setup.sh` | +5 行 (`export DEVCONTAINER=1` を `~/.bashrc` に idempotent 追記) |
| 修正 | `README.md` | +50 行 (Universal Evaluator セクション + hook 設定例 + 高リスクツール運用ノート + 本番推奨環境変数) |

**既存ファイルへの破壊変更なし**。既存 `policy/engine.py` / `policy/models.py` / `policy/loader.py` は不変。`DashboardService.__init__` の新規引数 `retrieval_pipeline` はデフォルト `None` のため、既存呼び出し箇所も互換維持。

## 8. 次ステップ

1. このデザインドキュメントのユーザーレビュー
2. レビュー後、writing-plans スキルで実装計画 (タスク分解) を作成
3. 実装計画に基づき TDD で実装
4. Devcontainer 内で `scripts/check_evaluator.sh` を実行し全テスト通過を確認
5. **README に以下の運用ノートを追加**:
   - 本番環境の必須/推奨環境変数 (§5.3 表参照、特に `CHRONOS_EVALUATOR_FALLBACK=ask` の強い推奨)
   - 高リスクツール群 (§5.4 表参照) に対する hook 構成例 (除外 or 前段マスキング)
   - devcontainer CLI 利用時の `export DEVCONTAINER=1` 手順 (§6.4 参照)
   - 起動ログ (`evaluator config: llm=... memory=... fallback=...`) の読み方
6. PR 作成 (README 更新含む)

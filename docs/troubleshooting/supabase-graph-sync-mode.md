# Troubleshooting: Supabase + Graph 有効時の `GRAPH_SYNC_MODE` 起動エラー

`STORAGE_BACKEND=supabase` かつ `GRAPH_ENABLED=true` の構成で、`GRAPH_SYNC_MODE` が `sync`（デフォルト値）のままになっていると、サーバー起動時（正確には `Settings` 構築時）に `ValidationError` が発生し、`memory_save` を含む全てのメモリ操作が失敗します。

## 🚩 問題の概要

`memory_save` などのツールを呼び出すと、以下のようなエラーが返ります。

```text
Error executing tool memory_save: 1 validation error for Settings
Value error, Supabase + graph の組み合わせには graph_sync_mode='async_outbox' が必須です
(Neo4j Bolt は HTTPS にカプセル化できないため)。
input_value={'storage_backend': 'supabase', ..., 'graph_sync_mode': 'sync'}
```

`scripts/check_connectivity.py` を実行した場合も、同じ設定であれば診断メッセージの前にこの検証エラーで停止します。

## 🔍 原因の特定

検証ロジックは `src/context_store/config.py` の `Settings._validate_graph_sync_mode`（`@model_validator(mode="after")`）にあります。

```python
if (
    self.storage_backend == "supabase"
    and self.graph_enabled
    and self.graph_sync_mode != "async_outbox"
):
    raise ValueError(
        "Supabase + graph の組み合わせには graph_sync_mode='async_outbox' が必須です "
        "(Neo4j Bolt は HTTPS にカプセル化できないため)。"
    )
```

これは意図的なフェイルファスト設計です。Supabase は Data API（HTTPS/PostgREST）経由でのみアクセスでき、Neo4j の Bolt プロトコル（TCP）をそのトンネルに乗せることができません。そのため `sync`（GraphLinker が Neo4j に直接同期書き込み）は Supabase 環境では成立せず、`async_outbox`（Storage トランザクション内で Outbox テーブルに書き込み、専用 Worker が非同期で Neo4j に同期）を使う必要があります。

### なぜこの状態になるのか

- `scripts/bootstrap.sh` 経由でセットアップした場合は、以下の自動補正ロジックが働くため通常発生しません。

  ```bash
  # Correlation validation auto-correction
  if [ "$BACKEND" = "supabase" ] && [ "$GRAPH_ENABLED" = "true" ]; then
      if [ "$GRAPH_SYNC_MODE" != "async_outbox" ]; then
          echo "Supabase combined with graph_enabled=true requires async_outbox mode. Overriding graph_sync_mode to async_outbox."
          GRAPH_SYNC_MODE="async_outbox"
      fi
  fi
  ```

- 一方、`.env.example` をそのまま手動でコピー・編集し、`STORAGE_BACKEND=supabase` と `GRAPH_ENABLED=true` だけを設定して `GRAPH_SYNC_MODE=sync`（デフォルト値）を変更し忘れると、この不整合な状態になります。`bootstrap.sh` を経由しない限り自動補正は働きません。

## 🛠 解決策

### 1. `.env` を直接修正する（最短）

```bash
# .env 内の該当行を書き換える
GRAPH_SYNC_MODE=async_outbox
```

合わせて Outbox ワーカー関連の設定（コメントアウトされている場合は解除）も確認してください。

```env
OUTBOX_POLL_INTERVAL_SECONDS=5.0
OUTBOX_BATCH_SIZE=100
OUTBOX_MAX_RETRIES=10
OUTBOX_BACKOFF_BASE_SECONDS=1.0
OUTBOX_BACKOFF_MAX_SECONDS=60.0
```

### 2. `bootstrap.sh` を再実行する（推奨）

`--graph-sync-mode` を明示するか、`--backend supabase --graph true` を渡すだけで自動補正されます。

```bash
bash scripts/bootstrap.sh --backend supabase --graph true --embedding local-model
```

### 3. グラフ機能自体が不要な場合

グラフ関係性を使わないのであれば、`GRAPH_ENABLED=false` に落とすことでも解消します（この場合 `GRAPH_SYNC_MODE` の値は無視されます）。

```bash
GRAPH_ENABLED=false
```

## 💡 設定のヒント (ChronosGraph 特有)

修正後は `scripts/check_connectivity.py` で設定が正しく反映されたか確認できます。

```bash
uv run python scripts/check_connectivity.py
```

このスクリプトは `Settings()` の構築失敗（本問題を含む）を検知した場合、生の traceback ではなく本ドキュメントへの案内を含むヒントを表示するようになっています。

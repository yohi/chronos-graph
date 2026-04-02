# 設計書: Embedding プロバイダーの不具合修正と機能改善 (2026-04-03)

## 1. 目的
`context_store.embedding` モジュールにおける LiteLLM の設定不備、リトライロジックの欠如、ハードコードされた次元数、およびローカルモデルのブロッキング I/O 問題を解消する。

## 2. 変更内容

### 2.1 設定 (`src/context_store/config.py`)
- `Settings` クラスに以下のフィールドを追加する。
    - `litellm_model: str = "openai/text-embedding-3-small"`
    - `embedding_dimension: int = 1536`
- `validate_credentials` メソッドを更新し、`embedding_provider == "litellm"` の場合に `litellm_model` の存在を確認する。

### 2.2 プロバイダー生成 (`src/context_store/embedding/__init__.py`)
- `create_embedding_provider` 関数を更新する。
    - LiteLLM: `model=settings.litellm_model`, `dimension=settings.embedding_dimension` を使用。
    - Custom API: `dimension=settings.embedding_dimension` を使用。
    - Local Model: `dimension=settings.embedding_dimension` を渡せるようにする（オプション）。

### 2.3 LiteLLM プロバイダー (`src/context_store/embedding/litellm.py`)
- `tenacity` を使用したリトライロジックを導入する。
    - `_is_retryable` 関数を `tenacity.retry_if_exception` 等で利用可能にする。
    - `embed_batch` 内の API 呼び出しにリトライデコレータまたはラップを適用する。

### 2.4 ローカルモデルプロバイダー (`src/context_store/embedding/local_model.py`)
- `LocalModelEmbeddingProvider.__init__` に `dimension: int | None = None` 引数を追加する。
- `dimension` プロパティを以下のように修正する。
    - `self._dimension` が設定済みであればそれを即座に返す。
    - 未設定の場合のみ `self._get_model()` を呼び出す（後方互換性のため）。
- `_get_model` 内での `self._dimension` への代入を確実に行う。

## 3. テスト計画
- **Unit Test (Settings)**: 新しい設定項目が正しく読み込まれ、バリデーションが機能することを確認。
- **Unit Test (LiteLLM)**: リトライロジックが機能することを確認（Mock を使用）。
- **Unit Test (Local Model)**: `dimension` を渡した場合にモデルロードが発生しないことを確認。
- **Integration Test**: 各プロバイダーが新しい設定を使用して正常に初期化できることを確認。

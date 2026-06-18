# Troubleshooting: LiteLLM Cloudflare Workers AI 接続エラー (Typo Bug)

LiteLLM を使用して Cloudflare Workers AI (または AI Gateway) に接続する際、特定のバージョンにおいてライブラリ内のスペルミス（Typo）が原因で接続に失敗する問題が確認されています。

## 🚩 問題の概要

Cloudflare 向けの LLM 呼び出しを実行すると、`APIConnectionError` が発生し、詳細ログに `No route for that URI` や `Could not route to ...` といったメッセージが表示されます。

原因は、LiteLLM のソースコード内で `content-type` ヘッダーの値が `apbplication/json` という不正な値に固定されているためです。

### 影響を受けるバージョン
*   `litellm` v1.83.0 〜 v1.89.2 (2026年6月時点の最新版を含む)

### 影響を受けるプロバイダ
*   Cloudflare Workers AI
*   Cloudflare AI Gateway

---

## 🔍 原因の特定

問題の箇所は以下のファイルです：
`.venv/lib/python*/site-packages/litellm/llms/cloudflare/chat/transformation.py`

```python
# 誤っている箇所
"content-type": "apbplication/json",
```

---

## 🛠 解決策

ライブラリ内の該当箇所を修正することで正常に通信できるようになります。

### 1. 自動修正コマンド (Recommended)

プロジェクトのルートディレクトリ（仮想環境が有効な状態）で以下のコマンドを実行してください。

```bash
# Linux / macOS
sed -i 's/apbplication/application/g' .venv/lib/python3.12/site-packages/litellm/llms/cloudflare/chat/transformation.py
```
*(※ Python のバージョンに合わせてパスを調整してください)*

### 2. 手動修正

ファイルを開き、`apbplication` を `application` に置換して保存してください。

---

## 💡 設定のヒント (ChronosGraph 特有)

ChronosGraph で Cloudflare を利用する場合、`.env` の `CHRONOS_EVALUATOR_MODEL` に `openai/` プリフィックスを付けることで、より安定した OpenAI 互換エンドポイント経由での通信が可能になります。

**例:**
```env
CHRONOS_EVALUATOR_MODEL=openai/@cf/zai-org/glm-4.7-flash
```

この設定と上記のパッチを組み合わせることで、正常に安全評価機能が動作します。

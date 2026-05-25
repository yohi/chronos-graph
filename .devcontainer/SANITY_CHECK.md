# Devcontainer Sanity Check

Devcontainer 起動直後に以下を実行し、開発環境が想定どおりであることを確認する。

## 1. ベース環境

```bash
python --version          # → Python 3.12.x
uv --version              # → uv 0.6.x (Dockerfile の SHA 固定に対応するバージョン)
echo "$UV_PROJECT_ENVIRONMENT"  # → /home/vscode/.venv
```

## 2. 依存解決 & Hook

```bash
uv sync --frozen --all-extras
git config --list | grep hooks.path  # → .git/hooks (pre-commit が正常にインストールされているか)
```

Expected: エラーなし (exit 0)

## 3. lint / mypy / unit test

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v
```

すべて緑であれば作業開始可能。

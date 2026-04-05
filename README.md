# ChronosGraph 🚀
**Temporal Knowledge Graph & RL-based Long-Term Memory for AI Agents**

`ChronosGraph` は、AIエージェント（Claude Code / Gemini CLI / Cursor等）にセッションを跨いだ永続的な長期記憶を提供する、Model Context Protocol (MCP) サーバーの最新実装です。

「情報の断片化（ステートレス性）」を解決し、文脈を捉えた記憶保持と、時間経過に応じた自己進化を実現します。

## 核心的なアプローチ
1.  **多層記憶グラフ (MAGMA):** 情報を単なるベクトルとして保存するのではなく、時間軸を伴うグラフ構造として保持。Episodic（経験）・Semantic（知識）・Procedural（手順）の変遷を正確に追跡します。
2.  **動的忘却アルゴリズム:** 指数関数的な減衰モデルと重要度評価により、記憶の肥大化を防ぎつつ、重要な教訓を「意味記憶」として抽出します。
3.  **RL 拡張ポイント:** 将来の強化学習（PPO 等）統合に向けたインターフェースを設計。ユーザーとの対話を通じたエージェントの行動論理の継続的アップデートを可能にします。

---

## 開発 (Development)
開発環境のセットアップやワークフローの詳細は [AGENTS.md](AGENTS.md) を参照してください。

### Git フックの運用
本プロジェクトでは、コード品質を保つために `pre-commit` を活用しています。

- **コミット時 (`pre-commit`)**:
  - `ruff` (Lint/Format) が自動実行されます。ホスト側でのコミットも可能です。
- **プッシュ時 (`pre-push`)**:
  - `mypy` (型チェック) が実行されます。依存ライブラリが必要なため、`devcontainer` 内または `uv sync` 済みの環境での実行を推奨します。
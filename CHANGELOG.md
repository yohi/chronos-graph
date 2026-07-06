# Changelog

## [1.6.0](https://github.com/yohi/chronos-graph/compare/v1.5.1...v1.6.0) (2026-06-18)


### Features

* **setup:** Agent Setup Protocolに基づく構築とLiteLLMタイポ修正対応 ([#343](https://github.com/yohi/chronos-graph/issues/343)) ([3cba79a](https://github.com/yohi/chronos-graph/commit/3cba79a28a10ee5a36d5883ce557a9580195d904))

## [1.5.1](https://github.com/yohi/chronos-graph/compare/v1.5.0...v1.5.1) (2026-06-17)


### Bug Fixes

* source_metadataのdatetimeシリアライズ失敗を修正 ([#341](https://github.com/yohi/chronos-graph/issues/341)) ([b978e70](https://github.com/yohi/chronos-graph/commit/b978e70edab88e992243f6264a6e7d6537ee6099))

## [1.5.0](https://github.com/yohi/chronos-graph/compare/v1.4.0...v1.5.0) (2026-06-09)


### Features

* **opensandbox:** Phase 2 - 統合テスト対応 & pnpm移行 ([#334](https://github.com/yohi/chronos-graph/issues/334)) ([732fffe](https://github.com/yohi/chronos-graph/commit/732fffe2dbf026a1289cfc44372a4083be56c8af))
* **sandbox:** Phase 1 - OpenSandbox Infrastructure & Runner ([#329](https://github.com/yohi/chronos-graph/issues/329)) ([c1f5585](https://github.com/yohi/chronos-graph/commit/c1f5585f3921c8122d8eb65e472d747262e49191))


### Bug Fixes

* **sandbox:** OpenSandbox integrationの乖離を修正 ([#339](https://github.com/yohi/chronos-graph/issues/339)) ([38473d1](https://github.com/yohi/chronos-graph/commit/38473d19322656fa60c8bca8b7e26c529cd0d334))
* **sandbox:** OpenSandboxプロファイル設定を明示適用 ([#338](https://github.com/yohi/chronos-graph/issues/338)) ([019879d](https://github.com/yohi/chronos-graph/commit/019879d6fe9ebcfada219a6e3159a2d5f0c7b17d))
* **sandbox:** 設計乖離の修正 - SQLiteパス切替fixture + テストDBスキーマ適用 ([#336](https://github.com/yohi/chronos-graph/issues/336)) ([7497593](https://github.com/yohi/chronos-graph/commit/74975931ee3f9ef54f48caf9d947ffd534b1c954))
* **sandbox:** 設計乖離の修正 - コード・ドキュメントの整合 ([#337](https://github.com/yohi/chronos-graph/issues/337)) ([393dbc7](https://github.com/yohi/chronos-graph/commit/393dbc72522729e6d2052de9d119fa8c572a9e72))

## [1.4.0](https://github.com/yohi/chronos-graph/compare/v1.3.1...v1.4.0) (2026-06-04)


### Features

* **evaluator:** evaluator共通の api_account_id 環境変数の導入および関連ドキュメント・スクリプトの更新 ([#321](https://github.com/yohi/chronos-graph/issues/321)) ([a57df6d](https://github.com/yohi/chronos-graph/commit/a57df6d5cbb163f9decac515808c5c32df516b37))

## [1.3.1](https://github.com/yohi/chronos-graph/compare/v1.3.0...v1.3.1) (2026-06-03)


### Bug Fixes

* trigger release ([#319](https://github.com/yohi/chronos-graph/issues/319)) ([e8566e1](https://github.com/yohi/chronos-graph/commit/e8566e1ad05202d55782d90970631f35201be3df))

## [1.3.0](https://github.com/yohi/chronos-graph/compare/v1.2.0...v1.3.0) (2026-06-02)


### Features

* **config:** graph_sync_mode と outbox 設定を追加 ([#299](https://github.com/yohi/chronos-graph/issues/299)) ([953151b](https://github.com/yohi/chronos-graph/commit/953151b9f804c8cefb4ffa6125b5c6093f781ae1))
* **factory:** async_outbox 対応の create_storage_with_outbox を追加 ([#312](https://github.com/yohi/chronos-graph/issues/312)) ([ce3719c](https://github.com/yohi/chronos-graph/commit/ce3719c8d62a4aa80dc9442a887db81eb37cb907))
* **neo4j:** execute_write メソッドを追加 ([#302](https://github.com/yohi/chronos-graph/issues/302)) ([bf310e0](https://github.com/yohi/chronos-graph/commit/bf310e089e15906cae0789cefef19c599075240b))
* **orchestrator:** OutboxWorker のライフサイクル統合 ([#313](https://github.com/yohi/chronos-graph/issues/313)) ([b715735](https://github.com/yohi/chronos-graph/commit/b715735aa0c779ef60f4035bacab71b6f9d978aa))
* **outbox-pipeline:** IngestionPipeline の graph_sync_mode 対応 (Task 5.3) ([#314](https://github.com/yohi/chronos-graph/issues/314)) ([5479be6](https://github.com/yohi/chronos-graph/commit/5479be6c794b825cd544efa9d4d0cea5c3da196b))
* **postgres:** save/delete_memory に OutboxWriter を統合 ([#306](https://github.com/yohi/chronos-graph/issues/306)) ([838d93e](https://github.com/yohi/chronos-graph/commit/838d93e026e004dbe1da25699550a66477e3c5f5))
* **scripts:** sync_storage_to_neo4j.py リカバリ CLI ([#310](https://github.com/yohi/chronos-graph/issues/310)) ([0c8c5a9](https://github.com/yohi/chronos-graph/commit/0c8c5a936ab3862421e14a161e3734f1da0e01b2))
* **setup:** 自動セットアップ処理をbootstrap.shに集約 ([#317](https://github.com/yohi/chronos-graph/issues/317)) ([6783a95](https://github.com/yohi/chronos-graph/commit/6783a95bbbf30be2bcee2356268027ed2b16728a))
* **sqlite:** save/delete_memory に OutboxWriter を統合 ([#307](https://github.com/yohi/chronos-graph/issues/307)) ([617399e](https://github.com/yohi/chronos-graph/commit/617399e51b656ecad897841d07f89aa3a9d7f50e))
* **storage:** graph_sync_outbox マイグレーションを追加 ([#300](https://github.com/yohi/chronos-graph/issues/300)) ([0dab0a5](https://github.com/yohi/chronos-graph/commit/0dab0a5f9d6d2b87b5863f298bd23c93787e377c))
* **supabase:** graph_sync_outbox マイグレーション + RPC ([#301](https://github.com/yohi/chronos-graph/issues/301)) ([0ae2b61](https://github.com/yohi/chronos-graph/commit/0ae2b61fed0d0141b34c8c7486fa36d212c27755))
* **supabase:** save/delete_memory に RPC outbox 切替を追加 ([#308](https://github.com/yohi/chronos-graph/issues/308)) ([c79f8b7](https://github.com/yohi/chronos-graph/commit/c79f8b714e3dd0e1a2c07c682428616990740ba0))
* **sync:** GraphSyncService - 共有 MERGE/DELETE ロジック ([#304](https://github.com/yohi/chronos-graph/issues/304)) ([5ac0d02](https://github.com/yohi/chronos-graph/commit/5ac0d020d4b73ca7dec816619beacab24e858f2d))
* **sync:** OutboxReader Protocol + 全バックエンド実装 ([#305](https://github.com/yohi/chronos-graph/issues/305)) ([f00fa01](https://github.com/yohi/chronos-graph/commit/f00fa011d9faa85ceac6e4d2d41e820c8dd4a806))
* **sync:** OutboxWorker - ポーリングループ + Backoff + リカバリ ([#309](https://github.com/yohi/chronos-graph/issues/309)) ([a5b8c12](https://github.com/yohi/chronos-graph/commit/a5b8c127ccfd45d7b2ac98e49829b26057d3edee))
* **sync:** OutboxWriter Protocol + 実装 ([#303](https://github.com/yohi/chronos-graph/issues/303)) ([c31b5ca](https://github.com/yohi/chronos-graph/commit/c31b5ca070977f7c5c43259b659b650662a76e5f))

## [1.2.0](https://github.com/yohi/chronos-graph/compare/v1.1.0...v1.2.0) (2026-05-31)


### Features

* chronos-gateの判定異常系におけるTUIトースト通知追加とバグ修正 ([#295](https://github.com/yohi/chronos-graph/issues/295)) ([b48a85f](https://github.com/yohi/chronos-graph/commit/b48a85fba3d927da6667cecb038c0ec1af543a71))

## [1.1.0](https://github.com/yohi/chronos-graph/compare/v1.0.0...v1.1.0) (2026-05-30)


### Features

* **release:** chronos-gate プラグインのパッケージ登録をトリガー ([#293](https://github.com/yohi/chronos-graph/issues/293)) ([18e0e3f](https://github.com/yohi/chronos-graph/commit/18e0e3fae67697361435a295d720384d9deaf244))

## 1.0.0 (2026-05-30)


### ⚠ BREAKING CHANGES

* **memory:** sourceフィールドのデフォルト値を"conversation"に変更

### Features

* **approval:** 承認決定モデルと理由サニタイズ機能を導入 ([4aa40c2](https://github.com/yohi/chronos-graph/commit/4aa40c2afa2cbe5c6b5166495a18bf8867245661))
* **approval:** 承認結果の履歴管理と状態チェックの改善 ([1283cd9](https://github.com/yohi/chronos-graph/commit/1283cd91e77263b1646e5a052f0190cbd91727bd))
* **architecture:** MCP v2.0 フルアーキテクチャ再設計の設計書を追加 ([1f317d2](https://github.com/yohi/chronos-graph/commit/1f317d268555c50a0d066b724b54ed4d1694d00d))
* Complete Dashboard Realignment - Phase 1-3 ([#61](https://github.com/yohi/chronos-graph/issues/61)) ([dc50d66](https://github.com/yohi/chronos-graph/commit/dc50d665ff223d335deb6250604ae38e0b8ac263))
* **config:** add dashboard-related Settings fields ([#49](https://github.com/yohi/chronos-graph/issues/49)) ([9d55947](https://github.com/yohi/chronos-graph/commit/9d559476e5c07fb939d93d5046000bae316537ed))
* **config:** batch_max_concurrent_jobs 設定を追加 ([#68](https://github.com/yohi/chronos-graph/issues/68)) ([02b54d3](https://github.com/yohi/chronos-graph/commit/02b54d315cdf959688f4d088c904a53493b0dbdc))
* **config:** Settings と GatewaySettings に ingestion_mode を追加 ([#282](https://github.com/yohi/chronos-graph/issues/282)) ([59b2500](https://github.com/yohi/chronos-graph/commit/59b2500389a9cf7f385f44ff7a9e846585119292))
* **config:** 設定値のバリデーション強化とSQLiteバックプレッシャー制御の改善 ([7f027d3](https://github.com/yohi/chronos-graph/commit/7f027d32b006a8661bb9d5f5814255f105db768f))
* **config:** 設定値のバリデーション強化とSQLiteバックプレッシャー制御の改善 ([3dcf1af](https://github.com/yohi/chronos-graph/commit/3dcf1af23ba5a751a4428f6a453c19bda652f87a))
* **context_store:** ダッシュボード用リトリーバルパイプラインファクトリを追加 ([52cb6f6](https://github.com/yohi/chronos-graph/commit/52cb6f6ba786df388c0a2e9d16c691fc463b1a03))
* **dashboard:** Chronos Graph Dashboard Web UI の実装 ([#47](https://github.com/yohi/chronos-graph/issues/47)) ([dfc6564](https://github.com/yohi/chronos-graph/commit/dfc656416f516f05c8cfc8a9efe6a8af3ae1c41b))
* **dashboard:** FastAPI app with stats/memories/system/graph/logs routes ([#53](https://github.com/yohi/chronos-graph/issues/53)) ([96a4aa0](https://github.com/yohi/chronos-graph/commit/96a4aa033e8b428a721a8fb2a4edb4ed235fd7e6))
* **dashboard:** Task 3.1 - SPA フォールバックと静的配信の実装 ([#57](https://github.com/yohi/chronos-graph/issues/57)) ([6670966](https://github.com/yohi/chronos-graph/commit/667096639d5e936cc0e46f643b13de3255e6e73b))
* Docker Compose 環境を構築 (PostgreSQL + Neo4j + Redis) ([d17ae75](https://github.com/yohi/chronos-graph/commit/d17ae75843dd64bedcd26447c7591dd45c6155e3))
* **docs:** MCPゲートウェイのLLM評価設計を更新し、print()禁止と機微情報マスキングを強化 ([91c890a](https://github.com/yohi/chronos-graph/commit/91c890a9b412b223fb768c68631592946c995564))
* **docs:** MCPゲートウェイ権限フック（承認フロー一時停止/再開）計画 ([#137](https://github.com/yohi/chronos-graph/issues/137)) ([07eada9](https://github.com/yohi/chronos-graph/commit/07eada95f31af4caa40dd6ac5f52e44eb0d365a1))
* **docs:** PrismaAdapter 設計仕様書を追加 ([#171](https://github.com/yohi/chronos-graph/issues/171)) ([c4ab629](https://github.com/yohi/chronos-graph/commit/c4ab629418597824a917eb6e899de66cc9257b0f))
* **docs:** WALチェックポイントの失敗履歴追跡を改善 ([cd6dd3a](https://github.com/yohi/chronos-graph/commit/cd6dd3a558aa8cf96a0202d94a82d9647fcb8548))
* E2E カバレッジ拡充・UI 未実装機能の補完 ([#62](https://github.com/yohi/chronos-graph/issues/62)) ([24b4a6a](https://github.com/yohi/chronos-graph/commit/24b4a6aa22f6504d2729daf3d8cf7dffd2ae348c))
* **e2e:** Task 3.3 - Playwright E2E テストの導入 ([#59](https://github.com/yohi/chronos-graph/issues/59)) ([5a160b9](https://github.com/yohi/chronos-graph/commit/5a160b98d43c9e8141f3084847cfdb596976901e))
* **factory:** wire SupabaseStorageAdapter ([#220](https://github.com/yohi/chronos-graph/issues/220)) ([325ee4b](https://github.com/yohi/chronos-graph/commit/325ee4b9967504eb36c6d1497c927e454c79a8de))
* **frontend:** add React Dashboard with Vite+TS+Tailwind ([#54](https://github.com/yohi/chronos-graph/issues/54)) ([397c372](https://github.com/yohi/chronos-graph/commit/397c372c2ad77b6b5c96df3e2a96a96af0d22899))
* **frontend:** Phase 1 - 環境修復と基盤ディレクトリ整備 ([#55](https://github.com/yohi/chronos-graph/issues/55)) ([95ff6fd](https://github.com/yohi/chronos-graph/commit/95ff6fdace5aacb5b6cafd21131179f5fe830697))
* **frontend:** Phase 2 - フロントエンド・アーキテクチャの正規化 ([#56](https://github.com/yohi/chronos-graph/issues/56)) ([0d35b4a](https://github.com/yohi/chronos-graph/commit/0d35b4a2edc79970eb7c5e0d14e397ef5532fdb0))
* **gateway:** ingestion_mode=all で memory_save を隠蔽 ([#283](https://github.com/yohi/chronos-graph/issues/283)) ([fe62188](https://github.com/yohi/chronos-graph/commit/fe62188e0149c9992f9780972d2735f3bd4a4bab))
* **gateway:** ToolRegistry に hidden_tools を追加 ([#279](https://github.com/yohi/chronos-graph/issues/279)) ([e3d18a4](https://github.com/yohi/chronos-graph/commit/e3d18a4d7e547c4eaf8b72ccd3e94f754365bbc8))
* **graph:** add list_edges_for_memories and count_edges (SQLite) ([#51](https://github.com/yohi/chronos-graph/issues/51)) ([355d371](https://github.com/yohi/chronos-graph/commit/355d371c2e08ec4135459b27baf6f6042c6f3737))
* **graph:** add Neo4j implementation and READ_ACCESS support ([#52](https://github.com/yohi/chronos-graph/issues/52)) ([e85712f](https://github.com/yohi/chronos-graph/commit/e85712f8fa98b88276be451500d333287e64997d))
* **hooks:** エージェントフック設定のドキュメント追加とパーミッションフックの実装 ([e521fe8](https://github.com/yohi/chronos-graph/commit/e521fe85f2e690f71b8c8040b1e3e8e42dfb060e))
* **infra:** Task 3.2 - Docker Compose に chronos-dashboard サービスを追加 ([#58](https://github.com/yohi/chronos-graph/issues/58)) ([8a4f5fe](https://github.com/yohi/chronos-graph/commit/8a4f5fe53f9f5c2f6848ae6bd689200e7cf46953))
* **ingestion:** BatchProcessor を追加 — バッチ処理ラッパー ([#67](https://github.com/yohi/chronos-graph/issues/67)) ([f9b33eb](https://github.com/yohi/chronos-graph/commit/f9b33ebb06b9a42498c5aec351abc0f43592a8e3))
* **ingestion:** TaskRegistry を追加 — バックグラウンドタスク管理 ([#66](https://github.com/yohi/chronos-graph/issues/66)) ([47ddf31](https://github.com/yohi/chronos-graph/commit/47ddf318176b667e40a1467136d0b786e3db2898))
* MCP 起動方法に uv (uv run) を追加 ([#45](https://github.com/yohi/chronos-graph/issues/45)) ([37308f4](https://github.com/yohi/chronos-graph/commit/37308f47837469d801abc1226ee65e4262093042))
* **mcp_gateway:** add EvaluatorSettings for LiteLLM-backed evaluator ([#265](https://github.com/yohi/chronos-graph/issues/265)) ([4bb838d](https://github.com/yohi/chronos-graph/commit/4bb838df8646d7739526729bd93a52b375f1a50b))
* **mcp_gateway:** CompositeEvaluator (Tier1+Tier2) ([#247](https://github.com/yohi/chronos-graph/issues/247)) ([#248](https://github.com/yohi/chronos-graph/issues/248)) ([5deb9f1](https://github.com/yohi/chronos-graph/commit/5deb9f1d06b153455ddadff86bfee1578e09986c))
* **mcp_gateway:** EvaluatorSettings for LiteLLM evaluator ([#259](https://github.com/yohi/chronos-graph/issues/259)) ([915578a](https://github.com/yohi/chronos-graph/commit/915578a16ae6564c3e22924d3c5ff12cb1ff3435))
* **mcp_gateway:** migrate LlmEvaluator to LiteLLM ([#262](https://github.com/yohi/chronos-graph/issues/262)) ([d6638cf](https://github.com/yohi/chronos-graph/commit/d6638cf66d925c9ec525bdc0a2cf0b775fb89733))
* **mcp_gateway:** 保留中の承認ID取得機能追加とRPCエラーハンドリング改善 ([ac3c56d](https://github.com/yohi/chronos-graph/commit/ac3c56da341cfb2b08606e54019e7d9fb62b9cf8))
* **mcp_gateway:** 承認機能のブロッキングモードを実装 ([e2f224c](https://github.com/yohi/chronos-graph/commit/e2f224c326f7e90db0167af68e1d6030ac5e40a8))
* **mcp-gateway:** add approvals endpoint ([bb8871d](https://github.com/yohi/chronos-graph/commit/bb8871db94b9e9175c8b89554679ad0c39c59613))
* **mcp-gateway:** add MaxBodySizeMiddleware to enforce ASGI body limits ([098dc97](https://github.com/yohi/chronos-graph/commit/098dc97f69f683a68c836456b77d0c839e889459))
* **mcp-gateway:** approval decision models (Phase 1 / Task 1 replay) ([66c79be](https://github.com/yohi/chronos-graph/commit/66c79be517848a628d104b4c01fbb7bcb660c75d))
* **mcp-gateway:** approval decision models (Phase 1 / Task 1) ([c45fe31](https://github.com/yohi/chronos-graph/commit/c45fe31a9e428c3bf525824135a323ee151dbc94))
* **mcp-gateway:** IBACガードレールとHITL承認フローの計画文書を作成 ([#111](https://github.com/yohi/chronos-graph/issues/111)) ([976b494](https://github.com/yohi/chronos-graph/commit/976b494c5f9e5ebba81318065f69e1e4770ca62b))
* **mcp-gateway:** implement suspend/resume approval flow (Phase 1-3) ([2066903](https://github.com/yohi/chronos-graph/commit/2066903214ba5cdeee06e9bafb906f07ed9dfe7d))
* **mcp-gateway:** InMemorySessionRegistry eviction hook (Phase 2 / Task 1) ([cc5d4f0](https://github.com/yohi/chronos-graph/commit/cc5d4f0f0a8478d4edd8dd2f669b61d6a4f1f778))
* **mcp-gateway:** MCPゲートウェイ Universal Evaluator 実装計画を追加 ([b9d0640](https://github.com/yohi/chronos-graph/commit/b9d0640d2ee19dc9f57094c6e0eab32f95a17170))
* **mcp-gateway:** MCPゲートウェイ Universal Evaluator 実装計画を追加 ([62dc95f](https://github.com/yohi/chronos-graph/commit/62dc95f95d32647df75d18a6a6b57c6fc44d347a))
* **mcp-gateway:** MCPゲートウェイ：承認フロー一時停止/再開設計追加 ([#136](https://github.com/yohi/chronos-graph/issues/136)) ([7e16b0d](https://github.com/yohi/chronos-graph/commit/7e16b0d9a0fc4e48fe9c6cdab34c4ef924ec59ad))
* **mcp-gateway:** PendingApprovalRegistry (Phase 1 / Task 3 replay) ([2b44b38](https://github.com/yohi/chronos-graph/commit/2b44b3847a4b46970d068735f772539e8880be89))
* **mcp-gateway:** PendingApprovalRegistry (Phase 1 / Task 3) ([33ee9e5](https://github.com/yohi/chronos-graph/commit/33ee9e5172fbb4e0abcd4d93527c874c3d79f16e))
* **mcp-gateway:** Phase 1 — approval module foundation ([66dd510](https://github.com/yohi/chronos-graph/commit/66dd5107b7640605fa59bd8bb7448ad7b6458238))
* **mcp-gateway:** Phase 2 — session eviction hook ([a29f61f](https://github.com/yohi/chronos-graph/commit/a29f61f700d16ed0b3d8eaa0f564afc09dad888c))
* **mcp-gateway:** sanitize_reason helper (Phase 1 / Task 2 replay) ([b261a39](https://github.com/yohi/chronos-graph/commit/b261a39154810013cedf3aa80db6c466fb41caf3))
* **mcp-gateway:** sanitize_reason helper (Phase 1 / Task 2) ([c9a5c9f](https://github.com/yohi/chronos-graph/commit/c9a5c9f849f61f0829067b516f7683511f71a2f5))
* **mcp-gateway:** suspend resume blocking mode for tools call ([441b114](https://github.com/yohi/chronos-graph/commit/441b114c209a1c1c757d2444376fee0c61263630))
* **mcp-gateway:** wire approval registry in app ([be7af88](https://github.com/yohi/chronos-graph/commit/be7af889744b9f32422573d88d6dd443a09a42c5))
* **mcp-gateway:** セッション退避時の eviction hook を追加 ([c76d27d](https://github.com/yohi/chronos-graph/commit/c76d27da072626a03f0164f1f7f1c3854e9ae16b))
* **mcp-gateway:** セッション退避時の eviction hook を追加 ([b9a8bfb](https://github.com/yohi/chronos-graph/commit/b9a8bfb50e07505fcc9edf87d1c7450786be0f7d))
* **mcp-gateway:** ユニバーサル評価器の設計更新とセマンティック検索機能追加 ([226d3cb](https://github.com/yohi/chronos-graph/commit/226d3cb1da4834b76d2351478897f90f6f1a627e))
* **mcp-gateway:** 承認判断モデルを追加 ([892b02f](https://github.com/yohi/chronos-graph/commit/892b02f0433f7797e1543b3febb26690b89c1f4e))
* **mcp-gateway:** 承認判断モデルを追加 ([2091071](https://github.com/yohi/chronos-graph/commit/209107127a651a71160b2f8f3e9be987376abe4a))
* **mcp-gateway:** 承認待ちレジストリを追加 ([8785b29](https://github.com/yohi/chronos-graph/commit/8785b29899befee2b3b40dcbf90dc568fc2e7496))
* **mcp-gateway:** 承認待ちレジストリを追加 ([b181752](https://github.com/yohi/chronos-graph/commit/b1817526cc8a993ff021a0f0a7d56c6709427597))
* **mcp-gateway:** 承認理由の sanitize ヘルパーを追加 ([6c3bcbd](https://github.com/yohi/chronos-graph/commit/6c3bcbd3400ea1adea2981946ddd92d368a9ea7b))
* **mcp-gateway:** 承認理由の sanitize ヘルパーを追加 ([828dbd7](https://github.com/yohi/chronos-graph/commit/828dbd73b5bda16d658ae785a74ce7a377fbfa4b))
* **mcp-v2:** SUPERSEDES チェーン解決のロジック改善とSQLiteバックプレッシャー制御の堅牢化 ([5e21334](https://github.com/yohi/chronos-graph/commit/5e21334f8b543034c71861839b09e39f9c7b32fc))
* **memory:** sourceフィールドのデフォルト値を"conversation"に変更 ([7439667](https://github.com/yohi/chronos-graph/commit/7439667309f67757f1f0ce26073ea6b200738c5b))
* Neo4j Graph Adapter を実装 ([2c16357](https://github.com/yohi/chronos-graph/commit/2c16357ba3359746bd080788d6f491339b24d1a4))
* Orchestrator と MCP サーバー実装 (Phase 1-8) ([#37](https://github.com/yohi/chronos-graph/issues/37)) ([367cd4e](https://github.com/yohi/chronos-graph/commit/367cd4e69ecd0c251d9da3be77d8e646e0cf5a8b))
* **orchestrator:** session_flush メソッドと dispose 拡張を追加 ([#69](https://github.com/yohi/chronos-graph/issues/69)) ([13c9eda](https://github.com/yohi/chronos-graph/commit/13c9eda80825b160379e7c166ef5a21029cf7862))
* **persistence:** WAL肥大化の自動フェイルセーフ機能と設定パラメータを追加 ([9272ade](https://github.com/yohi/chronos-graph/commit/9272adef6f6830a40c263f14996d8b1fae77792c))
* Phase 2 Storage Layer (SQLite Graph & InMemory Cache) ([#26](https://github.com/yohi/chronos-graph/issues/26)) ([9fa6bf0](https://github.com/yohi/chronos-graph/commit/9fa6bf0316c464b2d0fea7a7722408a8d63b2cf4))
* Phase 3 - Embedding Provider 実装 ([#32](https://github.com/yohi/chronos-graph/issues/32)) ([06a9c66](https://github.com/yohi/chronos-graph/commit/06a9c6629ebef534f7ff1fb7aea15e1b3f2b76c9))
* Phase 6 Lifecycle Manager 実装 ([#35](https://github.com/yohi/chronos-graph/issues/35)) ([a1d98c5](https://github.com/yohi/chronos-graph/commit/a1d98c5006d2a898447f0b9c8eb82ee5d2d31f70))
* PostgreSQL Storage Adapter を実装 ([0ff8ee0](https://github.com/yohi/chronos-graph/commit/0ff8ee068139d539dc05f829eb75a7b2a3f6ad32))
* PostgreSQL 初期スキーマとインデックスを定義 ([52a8304](https://github.com/yohi/chronos-graph/commit/52a83044c23bcd299b33aa3270caacb81fd5c3dc))
* pydantic-settings による設定管理を実装 ([034390f](https://github.com/yohi/chronos-graph/commit/034390f03f83926b9a6bbd9efd10890ccd042b8f))
* Python プロジェクト基盤を初期化 ([e1d67ef](https://github.com/yohi/chronos-graph/commit/e1d67efd193cb588a3670f8754502fab5692cb44))
* Redis Cache Adapter を実装 ([d831fea](https://github.com/yohi/chronos-graph/commit/d831feacae162628998cec03d99aaa5d6220fe59))
* **retrieval:** RetrievalPipeline.create_for_dashboard ファクトリ追加と orchestrator のリファクタリング ([fb45d9f](https://github.com/yohi/chronos-graph/commit/fb45d9f9117d0e15d1017d62dcc8b4e905459787))
* RL 拡張ポイント (Protocol + NoOp) を実装 [Phase 7] ([#36](https://github.com/yohi/chronos-graph/issues/36)) ([a65d080](https://github.com/yohi/chronos-graph/commit/a65d080b929533fb1fe64235fffcdddce528658e))
* **scripts:** bootstrap.sh に --cache オプションの解析と .env 反映を完全実装 ([43f20f8](https://github.com/yohi/chronos-graph/commit/43f20f814f8caae8a62ba7ac1c4015ac3d3c5e71))
* **scripts:** bootstrap.sh に --cache オプションを追加し、generate_config.py へ伝搬するように修正 ([6747c73](https://github.com/yohi/chronos-graph/commit/6747c732c38c152681abec5ac772d5b3d4166cab))
* **scripts:** PostgreSQL/Redis SSL設定の追加 ([e481a15](https://github.com/yohi/chronos-graph/commit/e481a15515cce5bbb2e8721af495d2bef789f355))
* **scripts:** ターン終了フックを追加 ([#278](https://github.com/yohi/chronos-graph/issues/278)) ([9ee62a3](https://github.com/yohi/chronos-graph/commit/9ee62a3c35e5c1a9538b2345af4e2102636d792a))
* **scripts:** 設定生成オプション追加と初期環境構築の改善 ([fc564e3](https://github.com/yohi/chronos-graph/commit/fc564e3a772814b312d740e5bc078a45a51fe25b))
* **server:** session_flush MCP ツールを登録 ([#70](https://github.com/yohi/chronos-graph/issues/70)) ([22ecf68](https://github.com/yohi/chronos-graph/commit/22ecf683075bdfde55060cd77c4a298ffbbdda6d))
* **shared:** ingestion mode SSOT を追加 ([#277](https://github.com/yohi/chronos-graph/issues/277)) ([1c3f303](https://github.com/yohi/chronos-graph/commit/1c3f303adb9cd8efc4e51a262b7c7628a64d2fcf))
* SQLite Storage Adapter (ライトウェイト版) を実装 ([c082d64](https://github.com/yohi/chronos-graph/commit/c082d643e2b189798c7d0d71751092658860ec5c))
* **sqlite:** WAL 縮小処理の堅牢化と監視機能の実装 ([afea8b1](https://github.com/yohi/chronos-graph/commit/afea8b11506a3a466efe32da619ab71a21d6045f))
* Storage Layer の Protocol を定義 ([13f34a9](https://github.com/yohi/chronos-graph/commit/13f34a95fb15939f6d6c325803aa2f5ca845a2e4))
* **storage:** add read_only mode to create_storage (SQLite) ([#50](https://github.com/yohi/chronos-graph/issues/50)) ([30cf6a0](https://github.com/yohi/chronos-graph/commit/30cf6a05cb048a2157f09aa1c9c9aa7cdb934b58))
* **storage:** aiosqliteのバックプレッシャー機構とエラーハンドリングを強化 ([c228c57](https://github.com/yohi/chronos-graph/commit/c228c576bc6c63c3be1b4e454f846642e2264214))
* **storage:** Neo4jエッジタイプ検証およびPostgresインデックス・ハッシュ追加 ([c8a1740](https://github.com/yohi/chronos-graph/commit/c8a1740a5dde9e78af499a8e8cbcae1f5c0fd75b))
* **storage:** Phase 2 ストレージレイヤーの引き継ぎドキュメント作成 ([a50e0cc](https://github.com/yohi/chronos-graph/commit/a50e0cca6da1f0aa0ac73abb6824f9eb33765f8d))
* **storage:** PostgreSQLのSSL対応とクラウド向けセットアップの改善 ([ce9aef1](https://github.com/yohi/chronos-graph/commit/ce9aef1ded767ba38ae8233886c04167c25e1bd4))
* **storage:** Postgresスキーマに検証制約を追加し、Neo4jのグラフ走査を強化 ([fcc5e8f](https://github.com/yohi/chronos-graph/commit/fcc5e8fa287e80118c9fed5f03777175e379178e))
* **storage:** SupabaseStorageAdapter full implementation (Phases 3.1-4) ([#213](https://github.com/yohi/chronos-graph/issues/213)) ([55e1981](https://github.com/yohi/chronos-graph/commit/55e198145b0ca9c5f7580c8239097d1c76969d95))
* **storage:** 自作マイグレーション機能の実装と統合 ([#75](https://github.com/yohi/chronos-graph/issues/75)) ([c5ef37e](https://github.com/yohi/chronos-graph/commit/c5ef37edaa68f0b9cafa7d0235314a2dee188037))
* **supabase:** memories テーブル + インデックス + RPC関数 の追加 ([#212](https://github.com/yohi/chronos-graph/issues/212)) ([a1589c0](https://github.com/yohi/chronos-graph/commit/a1589c0f44fe504d0d6ea367fd8963da59980caa))
* **supabase:** Supabaseストレージアダプターの乖離是正とテスト堅牢化 ([#221](https://github.com/yohi/chronos-graph/issues/221)) ([7717880](https://github.com/yohi/chronos-graph/commit/7717880e1788aff6d441d31d73a0c7007a3b6312))
* uvx を使用した MCP 起動オプションの追加 ([#43](https://github.com/yohi/chronos-graph/issues/43)) ([de31213](https://github.com/yohi/chronos-graph/commit/de31213197dddc5ab796c8e959b917207283370e))
* v4/v5レビュー反映 - SQLite PRAGMA, SSRF対策, 保存セマンティクス修正, Task 2.5b/Phase 5.5追加 ([18f8892](https://github.com/yohi/chronos-graph/commit/18f88922bfd2d690c15e847c89a0db642652f056))
* v6レビュー反映 - Graph Linker Top-K上限, URL並行制限Semaphore, ストレステスト追加 ([78f4b32](https://github.com/yohi/chronos-graph/commit/78f4b3200267215c5cdacb197cb392dc4cd5de36))
* v7レビュー反映 - DNSリバインディング対策, Lifecycle並行ストレステスト拡充 ([9900611](https://github.com/yohi/chronos-graph/commit/99006118b1bddc3e9f342abc61bbe3581bdb8883))
* v8レビュー反映 - Verification横断追加, PGスキーマタスク新設, URL設定/テスト強化 ([200dcbc](https://github.com/yohi/chronos-graph/commit/200dcbc1ffa0efb8955c0fe044f393b772621029))
* v9レビュー反映 - 文書間整合性の解消 (project契約, GraphAdapter API, 用語統一) ([401d83d](https://github.com/yohi/chronos-graph/commit/401d83ddd1e3bafc73fe4d2dcc657de598b1344e))
* **WAL:** WAL肥大化の自動フェイルセーフ機構を実装 ([280a6cf](https://github.com/yohi/chronos-graph/commit/280a6cf633d8ad87bab1bd6cc461acbc446e68d1))
* アーキテクチャレビューに基づく設計の堅牢化（Deduplicator 置換ロジック、RRF 正規化、SQLite グラフ対応） ([bd2dc94](https://github.com/yohi/chronos-graph/commit/bd2dc949044f97bdcc58869c7d22122f5b4d5e24))
* アーキテクチャレビュー文章の削除 ([b613850](https://github.com/yohi/chronos-graph/commit/b6138507ce515343044098c90d466a959f4056a5))
* アーキテクトレビューに基づく設計と実装計画の改善 ([de5f2e7](https://github.com/yohi/chronos-graph/commit/de5f2e766975fa3deecb1c7cb46315026fc8de00))
* エージェントによる自律的なセットアップ構成の導入 ([#40](https://github.com/yohi/chronos-graph/issues/40)) ([152354e](https://github.com/yohi/chronos-graph/commit/152354e289b7ae471e454121e0212a1a39b8295c))
* エージェント向けの対話型セットアップの強化とREADME構成の整理 ([#42](https://github.com/yohi/chronos-graph/issues/42)) ([912c8a1](https://github.com/yohi/chronos-graph/commit/912c8a10550cf7872ed851b762ef986a05796b05))
* クライアント側フック設定を廃止し、サーバーサイド ccgate 統合を推進 ([8b2ef27](https://github.com/yohi/chronos-graph/commit/8b2ef2781d357e602aae40b95cb73ea1babe6db3))
* グレースフルシャットダウン・冪等性要件を追加、RRF正規化コードサンプルを整合化 ([46645cd](https://github.com/yohi/chronos-graph/commit/46645cd5c2f0b2e03ce745b38267c16eb74ac008))
* データモデル (Memory, Search, Graph) を定義 ([1507a53](https://github.com/yohi/chronos-graph/commit/1507a53687c36f71646515e88c311239cd13e735))
* 共通基盤ユーティリティ (SafeSqliteInterruptCtx, StaleAwareFileLock) を実装 ([49e6335](https://github.com/yohi/chronos-graph/commit/49e6335da9c9c0e635ba6a4f34efeb6e0e492914))
* 構造化ロギングと可観測性 (Observability) の導入 ([9bed7d9](https://github.com/yohi/chronos-graph/commit/9bed7d98fc3ccb26e5ebc3a7454395e0a0b0a15c))
* 統合テスト・ドキュメント・ベンチマーク追加 (Phase 9) ([#38](https://github.com/yohi/chronos-graph/issues/38)) ([d5bb1b4](https://github.com/yohi/chronos-graph/commit/d5bb1b41b5fae875fb237dc5f0014319d7b0b4af))
* 記憶保存時のプレフィックスに絵文字(🧠, 🕒, 📜)を追加し、ブラケット形式を統一 ([#77](https://github.com/yohi/chronos-graph/issues/77)) ([a8aa9e5](https://github.com/yohi/chronos-graph/commit/a8aa9e554662f9a6c82e0bfe0a343417221b1745))


### Bug Fixes

* aiosqlite バージョン下限を &gt;=0.21.0 に修正 ([ba2af6d](https://github.com/yohi/chronos-graph/commit/ba2af6da214c39041ac8e1f31936afa69526d92f))
* apply CodeRabbit auto-fixes ([e2c098f](https://github.com/yohi/chronos-graph/commit/e2c098f20d3bfb16121f60df94b6d6b1ebd35caf))
* **approval:** mypy型エラーの修正 (intとint|Noneの比較) ([4467058](https://github.com/yohi/chronos-graph/commit/4467058cf089e7e1225df80c4bca984690626e3a))
* **approval:** wait_for_decisionの競合修正、テストの安定化、およびサニタイズの追加 ([bdef401](https://github.com/yohi/chronos-graph/commit/bdef401a8ed5272565e63853fc8109690309d0f9))
* **approval:** 承認処理の堅牢性向上（不明ID、セッション中断、理由サニタイズ） ([288be7f](https://github.com/yohi/chronos-graph/commit/288be7fd8264784d123dab54607fae163d61b5c5))
* **auth:** セッション削除コールバックのイベントループ非存在時に警告ログを追加 ([42fd49b](https://github.com/yohi/chronos-graph/commit/42fd49bf427450b8a4bdd151d75831020dd83417))
* CI の ruff format 失敗を解消 ([0d88ebf](https://github.com/yohi/chronos-graph/commit/0d88ebffbfb73139cc409facdb57f276f7656476))
* **ci:** switch runner back to ubuntu-latest ([#264](https://github.com/yohi/chronos-graph/issues/264)) ([7e06431](https://github.com/yohi/chronos-graph/commit/7e0643187f46fdd7b611217f9eb0fdb4e409da4d))
* **config:** .env 設定を環境変数よりも優先するように修正 ([#46](https://github.com/yohi/chronos-graph/issues/46)) ([80cd05c](https://github.com/yohi/chronos-graph/commit/80cd05c56bf26a5a243e66b0c2b9e0ab3aa7a7d9))
* **dashboard:** Phase 1 - 実行環境のエラー修正と設定調整 ([#60](https://github.com/yohi/chronos-graph/issues/60)) ([484b003](https://github.com/yohi/chronos-graph/commit/484b0032a0a8cd9a687b90cb5365d691efda2907))
* **db:** WAL肥大化フェイルセーフの条件を具体化 ([e1debb9](https://github.com/yohi/chronos-graph/commit/e1debb9df60ca8e27a492beab98f1982030a2ca3))
* **docs:** remove corrupted table rows at the end of implementation plan ([20d8631](https://github.com/yohi/chronos-graph/commit/20d86313e7b57a65d561a9f47f60e3aa131f8066))
* **gateway:** stacktrace のシークレット誤検知を部分マスクに修正 ([#275](https://github.com/yohi/chronos-graph/issues/275)) ([d2bfba2](https://github.com/yohi/chronos-graph/commit/d2bfba2a4daea499a1bd7c5f1ca24f1edf9ff1ef))
* implementation-plan.md 末尾の重複行を修正 ([0dcaba1](https://github.com/yohi/chronos-graph/commit/0dcaba177a07dc9a5decd5e04a4236048fd753a9))
* Markdownリストの表示崩れとhttpxカスタムバックエンドの仕様誤り(connect_tls)を修正 ([f5f3539](https://github.com/yohi/chronos-graph/commit/f5f3539461f15c82234412a71a7a311f6512074c))
* **mcp_gateway:** CLI --json-io を必須化、メモリクライアントテストと秘匿性改善 ([da50242](https://github.com/yohi/chronos-graph/commit/da50242cad4778b4e29114f7d0fdf25098b8d1f2))
* **mcp_gateway:** Content-Length ヘッダーがない場合のペイロードサイズ上限チェックを強化 ([910ae61](https://github.com/yohi/chronos-graph/commit/910ae611541ff3c3dab58155777578bdf688b65c))
* **mcp_gateway:** payload_too_largeエラー時の413応答送信を抑制 ([1d28e30](https://github.com/yohi/chronos-graph/commit/1d28e30d3db588f5aca88aa3768ac1da71d82dc1))
* **mcp_gateway:** 承認エンドポイントのリクエスト処理、バリデーション、監査ログを改善 ([4d8811f](https://github.com/yohi/chronos-graph/commit/4d8811fd8df8a4f25c28329b6a249251ba468057))
* **mcp_gateway:** 承認ブロックモードのTOCTOU脆弱性を修正し、タイムアウト検証を追加 ([097818b](https://github.com/yohi/chronos-graph/commit/097818b2b2b91ba445801eec624c4d2285205d9d))
* **mcp-gateway:** add type annotations to MaxBodySizeMiddleware ([a89ee0f](https://github.com/yohi/chronos-graph/commit/a89ee0f496279dec9436a6c550a1852f77f71b3e))
* **mcp-gateway:** always log reason in approval_decision audit log ([0e40ad5](https://github.com/yohi/chronos-graph/commit/0e40ad5c3f92473a7dcf15c876cf42930c68fce0))
* **mcp-gateway:** enhance body size middleware and fix unused variable ([1aaf821](https://github.com/yohi/chronos-graph/commit/1aaf8215596c76c462acb7fec05f248c49f3cacc))
* **mcp-gateway:** include approval_ref in allow_after_approval audit log ([239e729](https://github.com/yohi/chronos-graph/commit/239e729d074b166511a6cb5cffe628660b4bc42b))
* **mcp-gateway:** refactor body size limit to use stream counting ([7f5076e](https://github.com/yohi/chronos-graph/commit/7f5076ed66b6b01ddaa76c56b4b83028924e7ac6))
* **mcp-gateway:** 承認モジュール export の競合痕を除去 ([04cef55](https://github.com/yohi/chronos-graph/commit/04cef5557ec102319171568e0b2bde956e98e2c7))
* neo4j healthcheckの認証情報露出を防止 ([ea2ed73](https://github.com/yohi/chronos-graph/commit/ea2ed7364b32ced6d23ea68f2ed2c4e90cf09514))
* pg_bigm をバイナリではなくビルド時にcurlでダウンロードする方式に変更 ([54947fd](https://github.com/yohi/chronos-graph/commit/54947fd89bad6f70304b1f695d6407af2ddd2723))
* PostgreSQLのSSL検証ロジックの改善と接続確認スクリプトの堅牢化 ([2202fed](https://github.com/yohi/chronos-graph/commit/2202fed224857a6e945ec560b7a717df03dd29cf))
* **redis:** SSL引数の伝達方法を修正 ([30231df](https://github.com/yohi/chronos-graph/commit/30231df560df95d183554c18ac83c58d80d89264))
* **scripts:** bootstrap.sh の末尾の破損を修復し、キャッシュ設定の伝搬を再実装 ([616406a](https://github.com/yohi/chronos-graph/commit/616406a211c603e3f2bf652b3b3a601ebee55bc6))
* **scripts:** クラウド構成時のSSLおよびキャッシュ設定の不具合を修正 ([06d90dd](https://github.com/yohi/chronos-graph/commit/06d90dd82061c8e371c45e24eb17f4246b850d82))
* **scripts:** 接続チェックの出力とリソース解放を改善 ([48b7329](https://github.com/yohi/chronos-graph/commit/48b73294a40cbcba1d3f99e3659bf92239b03d70))
* **storage:** delete_memory returning representation ([#228](https://github.com/yohi/chronos-graph/issues/228)) ([ca0c1e7](https://github.com/yohi/chronos-graph/commit/ca0c1e753dce574c0e5221097f12e978732dfdae))
* **storage:** Redis接続タイムアウトの追加とcontent_hash重複エラーの修正 ([#272](https://github.com/yohi/chronos-graph/issues/272)) ([90a81ce](https://github.com/yohi/chronos-graph/commit/90a81ceddd5ff5bf9a21d253b1a560bc95446db4))
* **storage:** Supabaseのilikeクエリにおける不要な文字エスケープを削除 ([#219](https://github.com/yohi/chronos-graph/issues/219)) ([f15f377](https://github.com/yohi/chronos-graph/commit/f15f37782c1bbf40659012f7058863e150d43c8d))
* Supabase adapter last_accessed_at and archived_after cursor pagination ([#229](https://github.com/yohi/chronos-graph/issues/229)) ([e419eed](https://github.com/yohi/chronos-graph/commit/e419eed83f5f9a4c537a3fd1f45c4f8bc1a39b6d))
* **supabase:** RPC仕様漏れを補完 ([#227](https://github.com/yohi/chronos-graph/issues/227)) ([2e23922](https://github.com/yohi/chronos-graph/commit/2e23922f6b37a189c6090a08fbdc16155d8b59ea))
* Supabase検索の実装漏れを補完 ([#226](https://github.com/yohi/chronos-graph/issues/226)) ([cf30941](https://github.com/yohi/chronos-graph/commit/cf30941e18ce1753b87ae7a5cd35aa829bb2d1f0))
* **types:** resolve mypy errors in scripts and tests ([e642929](https://github.com/yohi/chronos-graph/commit/e64292927b1ddfe30e8755ad6a720449006a3b2b))
* uvx起動時にoptional dependenciesがインストールされない問題を修正 ([#204](https://github.com/yohi/chronos-graph/issues/204)) ([0dd26f1](https://github.com/yohi/chronos-graph/commit/0dd26f1e7c94a824486a64e7505db4c479bf548c))
* シークレット取得の改善、ドキュメントへの警告追加、およびテストアサーションの強化 ([802716f](https://github.com/yohi/chronos-graph/commit/802716f2fb1a86c6db94eb0db3837c7cf7d7afe8))
* ロガー初期化とテスト整形を修正 ([e09c3c7](https://github.com/yohi/chronos-graph/commit/e09c3c75470bc80f303d8378f2a1c7b0abf503ee))
* 検索ウェイト合計の検証を厳密化 ([dbcae30](https://github.com/yohi/chronos-graph/commit/dbcae30af1e605eef9b66430d97339227d2e9200))
* 設定値の秘密情報型とDSNエンコードを修正 ([01c266e](https://github.com/yohi/chronos-graph/commit/01c266e8f91ca31a7bf02c266947d64e3dfe5106))
* 設定値の範囲バリデーションを強化 ([47f950e](https://github.com/yohi/chronos-graph/commit/47f950e11c85f616f69d842064db9bee5e5c4939))
* 設定検証とモデル制約を強化 ([a543663](https://github.com/yohi/chronos-graph/commit/a543663f0bcc5d84e22b4ae12593e590a03c58eb))
* 設定検証とロガーの安全性を改善 ([20d9ead](https://github.com/yohi/chronos-graph/commit/20d9eadacb86aeb207a8e86dfe49c6e2e5e4be46))


### Performance Improvements

* reduce MCP memory timeout overhead ([#270](https://github.com/yohi/chronos-graph/issues/270)) ([83b9146](https://github.com/yohi/chronos-graph/commit/83b9146b7322c4c98e6b9e809c3cb80bad4ebf92))
* **storage:** reduce Supabase memory timeout overhead ([#269](https://github.com/yohi/chronos-graph/issues/269)) ([5c7897f](https://github.com/yohi/chronos-graph/commit/5c7897fa2b9696d25005e74f0a37e71d74ddae81))


### Reverts

* revert README.md update to original concise version ([793c498](https://github.com/yohi/chronos-graph/commit/793c498a4677daac345b1b434ab2977a929c0efd))

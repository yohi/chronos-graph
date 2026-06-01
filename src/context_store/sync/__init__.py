"""Transactional Outbox Sync package.

Provides:
- OutboxWriter: Storage TX 内で Outbox レコードを書き込む
- OutboxReader: Outbox からイベントを取得・更新する
- OutboxWorker: ポーリングループでイベントを処理する
- GraphSyncService: Storage → Neo4j の MERGE ロジック (Worker + リカバリ共有)
"""

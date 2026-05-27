-- ============================================================
-- content_hash の UNIQUE 制約を部分ユニークインデックスに変更
--
-- 背景:
--   Deduplicator の REPLACE 戦略は既存レコードをアーカイブ
--   (archived_at を設定) した後に同一 content_hash の新規
--   レコードを INSERT する。しかし UNIQUE 制約がテーブル全体
--   に効いているため、アーカイブ後の INSERT が失敗する。
--
-- 対応:
--   テーブル全体の UNIQUE 制約を削除し、代わりに
--   「archived_at IS NULL (アクティブなレコード)」のみを
--   対象とする部分ユニークインデックスを追加する。
--   これによりアーカイブ済みレコードとの重複が許容される。
--
-- 【注意: 本番環境での適用について】
--   本マイグレーションはトランザクション内で実行されるため、CONCURRENTLY オプションを使用できません。
--   すでに memories テーブルに大量のレコードが存在し、書き込み停止（ShareLock）を避けたい本番環境では、
--   事前に以下の手順で手動でインデックスを作成することを強く推奨します。
--
-- 手動適用手順:
--   1. トランザクション外（psql等）で以下を直接実行する:
--      CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_content_hash_active ON memories (content_hash) WHERE archived_at IS NULL;
--   2. その後、本マイグレーション（トランザクション内）を実行する。
--      (すでにインデックスが存在するため、CREATE UNIQUE INDEX は即座にスキップされ、テーブルロックは発生しません)
-- ============================================================

-- 既存の UNIQUE 制約を削除
ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_content_hash_key;

-- アクティブレコードのみを対象とする部分ユニークインデックスを作成
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content_hash_active
    ON memories (content_hash)
    WHERE archived_at IS NULL;

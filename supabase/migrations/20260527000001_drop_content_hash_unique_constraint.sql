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
-- ============================================================

-- 既存の UNIQUE 制約を削除
ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_content_hash_key;

-- アクティブレコードのみを対象とする部分ユニークインデックスを作成
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_content_hash_active
    ON memories (content_hash)
    WHERE archived_at IS NULL;

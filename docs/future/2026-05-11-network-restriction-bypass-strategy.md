# ネットワーク制限（Fortinet等）下でのクラウドDB接続回避戦略

## 概要
企業内ネットワーク（Fortinet等のUTM/次世代ファイアウォール）環境下において、標準的なデータベースポート（5432, 6543等）やバイナリプロトコルが遮断される問題への対策。

## 実証された事実 (2026-05-11)
- **直接接続の遮断**: ポート 5432 および 443 での PostgreSQL プロトコル通信は、Fortinet の Deep Packet Inspection (DPI) によりタイムアウトまたは切断される。
- **HTTPS通信の通過**: 同一ネットワーク内からでも、標準的な HTTPS (Port 443) 通信であれば、Cloudflare 等の CDN を経由して Supabase や Prisma Accelerate のエンドポイントまで到達可能である。

## 推奨される回避策

> [!WARNING]
> 以下の回避策（Prisma Accelerate, Supabase Data API, 各種トンネリング）の利用にあたっては、必ず組織のセキュリティ部門の事前承認を得て、社内ポリシーおよび関連法規を遵守してください。

### 1. Prisma Accelerate (Connection Proxy)
最も現実的な回避策。PostgreSQL 通信を HTTPS にカプセル化してプロキシサーバーへ送信する。
- **仕組み**: 
  - クライアント側で Prisma Client を使用。
  - `prisma://accelerate.prisma-data.net/?api_key=...` 形式の URL を使用。
- **メリット**: 
  - 通信が Fortinet からは「通常の HTTPS 通信」に見えるため、VPN なしで通過可能。
  - 既存の SQL ロジックを ORM 層の置換で対応できる可能性がある。

### 2. Supabase Data API (PostgREST / GraphQL)
データベースの生接続を一切行わず、HTTP API 経由でデータを読み書きする。
- **仕組み**: Supabase が標準提供する REST API (`/rest/v1/`) または GraphQL インターフェースを利用。
- **メリット**: 追加のミドルウェアなしで VPN 回避が可能。
- **デメリット**: ChronosGraph の現在のストレージアダプター層（asyncpg ベース）を大幅に書き換える必要がある。

### 3. SSH トンネリング / HTTP トンネル
HTTPS (443) ポート上で SSH や独自のトンネルを掘る。
- **デメリット**: 設定が複雑であり、社内ポリシーに抵触するリスクが高い。また、DPI によってトンネル自体が検知・遮断される可能性もある。

## 今後の実装方針
ChronosGraph のスケーラビリティを維持しつつ、エンタープライズ環境での利便性を高めるため、`StorageAdapter` の実装として **PrismaAdapter** を追加することを検討する（導入には組織のコンプライアンス承認が必要）。これにより、ユーザーは環境に応じて `asyncpg`（高速直接接続）と `Prisma`（制限回避接続）を選択可能になる。

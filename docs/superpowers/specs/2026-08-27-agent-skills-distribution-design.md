# Agent Skills Distribution — 設計仕様書

| 項目 | 内容 |
| --- | --- |
| Spec ID | `2026-08-27-agent-skills-distribution-design` |
| Status | Approved (Design Phase) |
| 作成日 | 2026-08-27 |
| 要件 | `REQUIREMENTS_2026-08-14.md` |
| 対象 | Agent-facing memory instructions の配布・同期・検証 |

## 1. 背景と目的

ChronosGraph の Save / Recall 運用ルールは、現在2つの長大な system prompt template として
提供されている。利用者はこれらを global または project instructions へ手動コピーするため、
常時コンテキスト消費、Progressive Disclosure との不整合、更新追従の困難さ、セットアップ経路の
不統一が発生している。

本変更では、Agent-facing instructions を次の方式へ一本化する。

- 常時ロードする情報は、Skillをいつ使うかを示す最小限のglobal instructionsだけにする
- Save / Recallの詳細ルールは、必要時にロードするglobal Agent Skillsとして提供する
- Repository内の定義をSSOTとし、`scripts/bootstrap.sh` から機械的に導入・同期する
- 既存ユーザーinstructionsと他製品・ユーザー管理Skillsを変更しない
- clean install、再セットアップ、dry-runの全経路を検証可能にする

## 2. スコープ

### 2.1 対象

- Save / Recall rulesのAgent Skills化
- minimal global instructionsのRepository SSOT化
- Claude Code、Codex CLI、OpenCodeへのglobal scope導入
- `scripts/bootstrap.sh` への同期・検証ライフサイクル統合
- `--agents` の意味と許容値の更新
- non-destructive update、再同期、dry-run、完了判定
- README、`AGENTS.md`、Agent Setup Protocol、関連テストの更新
- 旧system prompt templateと旧導入案内の削除

### 2.2 対象外

- Agent Skills非対応環境へのfallback prompt
- Cursor CLIとAntigravityの正式対応
- 既存ユーザー環境にコピー済みの旧promptの自動削除・自動migration（非破壊検出と警告は対象）
- `memory_save`、`memory_search`、`session_flush`の発火仕様変更
- `CHRONOS_INGESTION_MODE=selective|all` の意味変更
- turn-end ingestionのpayload処理・送信処理変更
- memory storage / retrieval engineの変更
- wheelへのAgent資産同梱と専用installer CLIの追加

既存の `agent_turn_hook.py` が持つCursor / Antigravity payload parserは変更しない。

## 3. 主要設計判断

| 判断 | 採用方式 | 根拠 |
| --- | --- | --- |
| 正式対応Agent | Claude Code、Codex CLI、OpenCode | 公式のglobal経路が明確 |
| Skill分割 | Save / Recallの2分割 | ingestion modeと既存責務境界に一致 |
| Skill名 | `chronos-memory-save` / `chronos-memory-recall` | 衝突を避け、製品と責務を明示 |
| Skill配置 | 両modeで2つとも配置 | mode切替と再同期を単純化。未ロードSkillは常時コンテキストを消費しない |
| Instructions所有境界 | HTML marker block | marker外の既存内容をbyte-for-byteで保持可能 |
| SSOT取得元 | bootstrap同梱Repository資産 | `--source` と独立し、追加network取得を不要にする |
| Agent選択 | `--agents` を対象環境選択へ再定義 | Skills、instructions、all時hookの対象を一本化 |
| 同期実装 | 専用Python helper | Shellより安全にmarker編集、hash、rollback、testを実装可能 |
| 最新版判定 | SSOT bundleのSHA-256 | 独立version番号を増やさず、対象sourceとの完全一致を判定可能 |

## 4. Repository SSOT

Agent資産は新規の非設定ディレクトリ `agent-assets/` で管理する。

```text
agent-assets/
├── minimal-instructions.md
└── skills/
    ├── chronos-memory-recall/
    │   ├── .chronosgraph-managed
    │   └── SKILL.md
    └── chronos-memory-save/
        ├── .chronosgraph-managed
        └── SKILL.md
```

`agent-assets/` は各Agentの設定ディレクトリではなく、bootstrapが配布する正規資産の格納場所である。
利用者側のコピーを独立した正規版として扱わない。

### 4.1 `chronos-memory-recall`

現行Recall promptの次のbehaviorを意味変更せず移す。

- 新規タスク開始時、prior-work参照時、既知解決があり得るerror時、規約判断前のRecall
- `memory_search` を主経路とし、必要時だけ `memory_search_graph` / `memory_stats` を使用
- project scopeを付けたfocused query
- Recall結果のuser-visible化
- current code / stateとのgrounding
- 同一session内での過剰な再検索回避
- Recall self-verification rubric

frontmatter descriptionは、タスク開始・error・規約判断時に使うSkillであることを明示する。

### 4.2 `chronos-memory-save`

現行Save promptの次のbehaviorを意味変更せず移す。

- user instruction完了時と、command failureからsuccessへの遷移時の評価
- Semantic / Procedural memoryの選別と保存形式
- `memory_save` の自律実行
- 8,000文字到達時の `session_flush`
- 重複・ノイズ・曖昧な内容の回避
- Save self-verification rubric

`session_flush` は独立SkillにせずSave側へ含める。frontmatter descriptionには、global instructionsが
`selective` を指定している場合だけ使用するmode guardを含める。

### 4.3 Minimal global instructions

常時ブロックには次だけを含める。

- ChronosGraph memory Skillsが利用可能であること
- Recall Skillをタスク開始時と真のerror / decision pointでロードすること
- `selective` では、既存trigger成立時にSave Skillをロードすること
- `all` では、Agentが `memory_save` / `session_flush` を呼ばずturn-end hookへ委譲すること

詳細trigger、tool usage、format、rubricは常時ブロックへ展開しない。

## 5. 対応Agentと配置先

| Agent ID | Global Skills root | Global instructions | Approved instructions root |
| --- | --- | --- | --- |
| `claudecode` | `~/.claude/skills/` | `~/.claude/CLAUDE.md` | `~/.claude/` |
| `codex` | `~/.agents/skills/` | `~/.codex/AGENTS.md` | `~/.codex/` |
| `opencode` | `~/.config/opencode/skills/` | `~/.config/opencode/AGENTS.md` | `~/.config/opencode/` |

配置先は同期helper内の明示的なadapter tableで管理する。将来Agentは、公式なglobal Skillsと
global instructionsの両経路、および自動検証方法が確定してから追加する。

## 6. CLI契約

`--agents` を「ChronosGraphを利用する対象Agent環境」の選択へ再定義する。

- 必須かつ空文字不可
- `--agents` optionは1回だけ指定でき、欠落・複数指定・値なしを拒否
- 許容値は `claudecode,codex,opencode`
- comma-separated入力を要素ごとに一度だけparseし、前後空白を除去する。空要素は拒否
- adapter tableで定義したcanonical orderへ正規化し、重複を除去した不変のcanonical agent setを生成
- 未知IDまたは正式対応外IDが1つでもあれば書き込み前に失敗
- `notcodex` のように許容IDを部分文字列として含む値も未知IDとして拒否
- raw valueの再parse、環境変数からの暗黙補完、substring-basedなAgent判定は禁止
- canonical agent setの検証は `.env` 作成、依存関係インストール、MCP設定生成、その他のfilesystem writeより前に完了
- `selective` でもSkills / instructions同期を実行
- `all` では同期後、同じcanonical agent setを既存turn-end hook setupへ渡す
- `--non-interactive` でもAgentを暗黙選択しない

bootstrapは、引数解析時に生成したcanonical agent setを同期helperと既存hook setupの唯一の入力として保持する。
hook側はcanonical setの厳密なmembershipだけを使い、入力文字列の再分割や部分文字列検索を行わない。

`--source=local|remote` はMCP serverの実行方式だけを表す。Agent資産はどちらの場合も、実行中の
bootstrapと同じRepository checkoutまたはrelease tarballに同梱されたSSOTから同期する。

## 7. Markerと所有判定

Global instructionsでは、次の一対のmarkerで囲まれた範囲だけをChronosGraphが所有する。

```markdown
<!-- BEGIN CHRONOSGRAPH MANAGED: agent-memory -->
<!-- chronosgraph-bundle:
sha256={{BUNDLE_SHA256}};
ingestion-mode={{INGESTION_MODE}}
-->
ChronosGraph memory Skills are available. Load and follow the Recall Skill
at task start and genuine error or convention-decision points. Follow the
mode-specific Save rule below.
<!-- END CHRONOSGRAPH MANAGED: agent-memory -->
```

`{{BUNDLE_SHA256}}` と `{{INGESTION_MODE}}` は同期時に置換するrender tokenであり、targetへtokenの
まま配置しない。mode-specific Save ruleも `minimal-instructions.md` のrender tokenから生成する。

Bundle digestは、`agent-assets/` 配下の全regular fileをrelative POSIX pathで昇順に並べ、各fileの
`relative path`、NUL byte、file bytes、NUL byteを順にSHA-256へ入力して計算する。Symlinkと未定義の
file typeはSSOT validation errorとする。本文やdigestの期待値は毎回SSOTから再生成し、利用者側
コピーを入力にしない。

Skillでは、SSOTにも含まれる `.chronosgraph-managed` sentinelを所有証跡とする。
Sentinelの内容は `owner=chronosgraph` と `format=1` の2行に固定し、形式不一致はownershipを
推測せずcollisionとして扱う。

- 対象Skill directoryが未存在なら新規導入
- sentinelがある場合だけChronosGraph所有directoryとして更新
- 同名directoryが存在しsentinelがない場合、ユーザー管理Skillとの衝突として失敗
- 他のSkill directoryは列挙・snapshotするだけで変更しない

Instructionsのsymlinkは、symlinkであること自体をChronosGraphの所有証跡とはみなさない。preflightでは
symlinkをfollowして書き込む前に、`lstat`でlinkを識別し、解決後のcanonical pathと既存親directoryのcanonical
pathが、対象Agent adapterの承認済みinstructions root内にあることをpath component単位で検証する。
正常に解決できるsymlinkであってもroot外を指す場合はcollisionとして拒否する。共有symlinkを許可する実装を
追加する場合も、`--allow-shared-instructions-symlink`と事前に承認された`--shared-instructions-root`の両方が
指定されない限り拒否し、任意のroot外pathへ書き込める暗黙の許可は設けない。本仕様の初期実装ではshared
symlinkを許可せず、上記opt-inが導入されるまで常にcollisionとして扱う。broken、cyclic、non-regular target、root外のparent symlinkも同じく
preflight errorとし、非所有領域へ到達するwriteを開始しない。

## 8. 同期コンポーネント

`scripts/sync_agent_assets.py` を内部CLIとして追加する。責務は次に限定する。

1. Agent IDから配置先を解決
2. SSOT assetの検証とbundle digest計算
3. expected Skill directoriesとminimal blockのrender
4. preflight、dry-run plan、production apply、post-write verification

`scripts/bootstrap.sh` は既存のMCP、environment、hook処理を維持し、Agent資産同期をhelperへ委譲する。
同期または検証が失敗した場合、bootstrapは非ゼロ終了し、`Bootstrap complete!` を表示しない。

## 9. 同期データフロー

### 9.1 Preflight

全対象について、書き込み前に次を完了する。

1. CLI入力とSSOT assetを検証
2. bundle digestを計算
3. instructions markerの状態を解析
4. Skill ownership collisionを検出
5. expected outputと必要actionを生成
6. marker外instructionsをbyte snapshot
7. 非ChronosGraph Skillsをpath、type、content hashでsnapshot
8. 既存instructionsのsymlinkと全既存parentを`lstat`し、解決後canonical pathのroot containmentを検証
9. 旧Save / Recall promptの存在を本文非出力で検出し、modeに応じたwarningまたはcollisionを記録

次はpreflight errorとし、全対象を無変更のまま終了する。

- markerの重複、片側欠損、入れ子
- SSOT asset欠損、Skill name不一致、sentinel不正
- 非所有の同名Skill
- broken / cyclic symlink
- resolved canonical pathが承認済みAgent instructions root外にあるsymlink、またはshared rootのopt-inがないsymlink
- all modeでlegacy Save promptとmanaged blockを併存させることになる状態
- 書き込み先または必要な親directoryを安全に準備できない状態

### 9.2 Production apply

Production applyは、全対象のpreflight成功後、最初のfilesystem writeからpost-write verificationおよび
`all`のhook setup完了までを1つのAgent asset transactionとして扱う。transactionはverificationとhook setupの
全成功後にだけcommitされる。

- preflight journalには、対象pathごとの存在、file type、permission、symlink link text、content hash、
  marker外snapshot、ChronosGraph所有範囲、backup location、新規作成フラグを記録する
- Skillは対象parent内でstagingし、既存owned directoryをbackupへ移してからswapする
- Instructionsは同一directoryのtemporary fileへ書き、permissionを保持してreplaceする
- Instructions fileが未存在なら、選択済み正式対応Agentに限り作成する
- 既存instructionsが安全なsymlinkならsymlink自体を置換せず、preflightで承認済みと判定した解決先だけを更新する
- `all`のhook setupには、platform wrapper（`scripts/chronos-turn-hook.sh` / `.cmd`）とOpenCodeのmanaged plugin
  registrationを含め、同期済みcanonical agent set以外のhookを変更しない
- wrapper、hook artifact、managed plugin registrationにもbackupとrestore journalを作る。既存設定ファイルの
  非所有contentはsnapshotと一致する範囲だけを更新・復元し、非所有変更を丸ごと上書きしない
- 全対象のpreflight成功後にだけapplyを開始し、post-write verificationと`all` hook setupが終わるまでcommitしない
- apply中のI/O error、post-write verification failure、hook setup failureのいずれもtransaction failureとし、
  reverse orderで今回変更したSkill、managed instructions block、wrapper、hook artifactをrollbackする
- rollbackでは既存owned pathをbackupから復元し、今回作成したpathは、preflight時に不存在でかつtransactionが
  作成したことを確認できる場合だけ除去する。pre-existing pathや非所有領域は削除・修復しない
- rollback対象の現在値がpreflight snapshotから外部変更されている場合は非所有変更を保護し、自動的に全体を
  復元せず、未復旧のChronosGraph所有pathとして報告する
- rollback failureは元のfailureと別に記録し、非ゼロ終了、復旧できなかったowned pathの列挙、
  `Bootstrap complete!` 非表示を必須とする

### 9.3 Dry-run

Dry-runはproductionと同じpreflight、render、比較を行い、次を表示する。

- create
- update
- unchanged
- conflict / malformed
- expected bundle digest

Dry-runではstaging、temporary file、directory作成を含むfilesystem writeを行わない。productionなら
失敗する状態ではdry-runも非ゼロ終了し、理由を表示する。

### 9.4 Post-write verification

全対象で次を再確認する。

- 2つのSkillがSSOTと完全一致
- managed blockが対象modeのexpected contentと完全一致
- marker外instructionsがpreflight snapshotと一致
- 非ChronosGraph Skillsのpath、type、content hashがsnapshotと一致
- target contentと現在のSSOTから再計算したbundle digestが一致
- `all` では既存hook setupも成功

検証または`all` hook setupのいずれかが失敗した場合、verification成功とはみなさず、9.2のtransaction
rollbackを完了してからerrorを報告する。全確認成功後だけtransactionをcommitし、bootstrapを完了扱いにする。

## 10. Error reportingとrollback

Error outputには、対象Agent、対象path、phase、action、不一致項目、digestだけを含める。
ユーザーinstructions本文、他Skill本文、credentialを出力しない。

Apply中のerrorでは、元errorとrollback成否を両方報告する。Rollback自体が失敗した場合も完了扱いに
せず、復旧できなかったChronosGraph所有pathを列挙する。非所有領域の自動修復は行わない。

preflightでsymlink collisionまたはlegacy Save promptのall-mode collisionを検出した場合は、対象Agent、
対象path、phase、collision種別、必要な手動対応だけを警告・errorに含め、symlinkの解決先本文やlegacy prompt
本文を出力しない。rollbackのbackup artifactはtransaction終了時に、commitまたはrollback成功時だけ安全に
破棄し、rollback failure時は復旧用として保持して未復旧pathとartifact識別子を報告する。

## 11. Agent Setup Protocolへの統合

### Phase 4

質問を「hookを適用するAgent」から「ChronosGraphを利用する対象Agent環境」へ変更し、3 IDから
複数選択させる。空選択は不可とする。

### Phase 5

Agentは収集した対象を `--agents` へ渡し、bootstrapにMCP setup、Agent資産同期、必要時hook setupを
一括委譲する。Agentが各global設定を個別にスクラッチ作成しない原則を維持する。
bootstrapは`--agents`を一度だけcanonical agent setへparse・validateし、そのsetをAgent資産同期と`all` hook
setupへそのまま渡す。validationはPhase 5のfilesystem side effectより前に行う。

### Phase 7

既存connectivityとturn-end ingestion確認に加え、次を完了条件にする。

- selected Agentのminimal instructionsが存在
- selected Agentの2 Skillsが存在
- bundle digestとSSOTが一致
- marker外instructionsと他Skillsが変更されていない
- legacy prompt検出結果がmode guardと整合し、許可されたwarning以外のcollisionがない
- transaction commit後にselected Agentのhook artifactが存在し、`all`ではhook setupが成功している

## 12. 旧方式の廃止と文書更新

- `docs/agent-prompts/memory-save-system-prompt.md` を削除
- `docs/agent-prompts/memory-search-system-prompt.md` を削除
- READMEの手動promptコピー手順と旧リンクを削除
- `AGENTS.md` の旧prompt参照をRepository Skill SSOT参照へ更新
- Agent Setup ProtocolのPhase 4、5、7を新方式へ更新
- bootstrapの `Final Step: Enabling Autonomous Memory` と手動コピー案内を削除
- README等に旧方式の自動migration手順やfallback手順を残さない

選択されたAgentのglobal instructions pathにコピー済みの旧Save / Recall promptは、preflightで非破壊に検出する。
検出器はversioned fingerprintと安定したtemplate headingを使い、
legacy種別（Save / Recall）と対象pathだけを記録し、prompt本文・credential・ユーザー本文を読み出して
出力したり、削除・置換・自動migrationしたりしない。検出時は「新しいSkillとmanaged blockの導入後、旧promptを
手動でバックアップ確認のうえ削除し、重複ルールがないことを確認する」という安全な手動移行を促すwarningを
表示する。このruntime warningは既存promptを変更せず、README等の正規手順として旧方式を復活させない。

旧promptとmanaged blockが併存する場合のmode guardは次のように固定する。

- `selective`: legacy Save / Recall promptを残したままmanaged blockと2つのSkillを導入できるが、warningを
  必ず表示する。managed blockのselective guardとSave Skillが正規経路であり、旧promptの削除はユーザーの
  手動作業に限定する
- `all`: legacy Recall promptだけならwarningのうえ導入を続行できる。legacy Save promptを検出した場合は、
  Agentが直接`memory_save`を呼ぶ経路を保証付きで無効化できないため、warningを伴うpreflight collisionとして
  全writeを拒否する。ユーザーが旧Save promptを手動削除して再実行するまでhook setupも開始しない
- mode切替のupgradeでは、旧Save promptが残る`selective`から`all`への切替を必ず拒否し、filesystem snapshotを
  完全保持する。旧Save promptを手動削除した後の再実行だけが`all`のmanaged block更新とhook setupへ進める

したがって、旧promptの検出は対象外ではなく安全性のためのread-only preflight契約であり、削除・migrationの自動化
だけを対象外とする。

## 13. Test strategy

### 13.1 Unit tests

- 3 Agentのpath mapping
- Agent ID validation、順序正規化、重複除去
- `--agents`の欠落、複数指定、空文字、空要素、`notcodex`、正式対応外IDの拒否
- canonical agent setが同期とhook setupの双方へ同一順序で渡ること、およびsubstring判定を使わないこと
- selective / all minimal block render
- marker append、replace、unchanged、malformed detection
- owned Skill create / updateと非所有同名Skill collision
- instructions symlinkのcanonical path containment、broken / cyclic / parent symlink、shared root opt-inなしの拒否
- SSOT validationとbundle digest
- dry-runでwrite APIが呼ばれないこと
- post-write verification failure、all hook setup failure、wrapper backup/restore、新規artifact削除のrollback
- rollback failure時のnon-zero終了、未復旧owned path報告、非所有snapshot保護
- legacy Save / Recall promptの本文非出力検出、warning、selective許可、all Save collision
- credentialや既存本文をerror outputへ含めないこと

### 13.2 Temporary HOME integration tests

- 3 Agentそれぞれのclean install
- 既存instructions前後のbyte-for-byte保持
- 他Skillの保持
- 同一SSOTでの再実行がno-op
- SSOT更新後にChronosGraph所有部分だけ同期
- `selective` から `all` への変更でmanaged blockだけ更新
- multi-Agent preflight失敗時に部分更新なし
- 注入したI/O failureからのrollback
- post-write verification failureからのSkill / instructions / wrapper rollback
- `all` hook setup failureからのhook artifact backup/restoreと新規作成物削除
- rollback failure時の非所有領域保護と復旧不能path報告
- instructions symlinkを保持した更新、およびroot外・shared symlink拒否
- 旧Save / Recall prompt併存時のread-only warningと手動移行案内
- legacy Save promptが残る`selective`→`all` upgradeの拒否、および手動削除後upgradeの成功
- dry-run前後のfilesystem snapshot完全一致

### 13.3 Bootstrap regression tests

- `--help` の新しい `--agents` 契約
- `--agents` 必須、正式対応外ID拒否
- duplicates、empty entries、`notcodex`、multiple agentsを含む`--agents`回帰
- dry-run outputにAgent資産planとdigestを含む
- dry-runのexit statusとfilesystem不変
- 同期または検証失敗時にcompletion messageなし
- post-write / hook failureおよびrollback failure時にcompletion messageなし
- 全検証成功時だけcompletion messageあり
- 既存hook payload / ingestion mode testsが継続して通る

### 13.4 Manual QA

一時HOMEを使い、3 Agent × 2 ingestion modeについて次を実際に実行する。

1. clean install
2. 同一versionの再同期
3. 既存instructions / 他Skill共存状態での同期
4. dry-run
5. mode切替
6. `all` のturn-end hook経路
7. approved root内symlink、root外symlink、broken/cyclic symlink
8. 旧Save / Recall prompt併存時のwarningと、旧Save promptが残る`all` upgradeの拒否

生成されたglobal instructionsとSkillを、各Agentの公式配置先から直接確認する。

## 14. Requirements traceability

### 14.1 Functional requirements

| 要件 | 設計上の充足箇所 |
| --- | --- |
| R1、R4、R14 | §4、§12: 2 Agent Skillsを唯一の詳細rules SSOTとし旧promptを削除 |
| R2 | §5: 3 Agentのglobal Skills rootへ導入 |
| R3 | §4.3: 常時blockをSkill routingとmode guardに限定 |
| R5、R6 | §4.1、§4.2、§6: Recall / Save behaviorとingestion modeを維持 |
| R7、R8 | §8、§11: bootstrap経由で導入済み状態まで完了 |
| R9 | §7、§9: marker / owned directory / canonical symlink境界と非所有snapshot検証 |
| R10、R13 | §4、§9: Repository SSOTからdigest比較で再同期 |
| R11 | §9.2〜§9.4、§10、§11: existence、digest、transaction rollback、非破壊性を完了条件化 |
| R12 | §5、§6: 正式対応3 Agentのみ許可 |
| R15 | §12: README、AGENTS、Protocol、bootstrapの旧参照を削除 |
| R16 | §9.3、§13: temporary fileも作らないdry-runとfilesystem snapshot test |

### 14.2 Acceptance Criteria

| Acceptance Criteria | 設計上の充足箇所 |
| --- | --- |
| AC1、AC2 | §4、§8、§11: 手動copyなしの自動導入とminimal instructions |
| AC3、AC4、AC5 | §4.1〜§4.3、§6: 両modeのRecall、selective Save、all hookを維持 |
| AC6、AC7 | §7、§9: marker外instructionsと他Skillsをsnapshot検証 |
| AC8、AC9 | §9、§11: digest再同期とsetup完了前検証 |
| AC10 | §9.3、§13: dry-runのwrite禁止とfilesystem snapshot test |
| AC11、AC12 | §12: 旧案内と旧system prompt sourceを削除し、既存コピーはread-only検出 |
| AC13 | §2.2、§6: 正式対応外Agentへfallbackしない |
| AC14 | §2.2、§4、§13: memory API、発火仕様、ingestion modeの回帰防止 |
| AC15 | §6、§9.1、§13.1、§13.3: `--agents`の一度だけの厳格なparse、canonical set共有、side effect前検証 |
| AC16 | §7、§9.1〜§9.4、§13: canonical path root containmentとshared symlink opt-inなしのcollision拒否 |
| AC17 | §9.2、§9.4、§10、§13: post-write / hook failureおよびrollback failureを含むtransaction rollback |
| AC18 | §12、§13.2、§13.4: legacy prompt warning、selective/all coexistence guard、upgrade integration |

## 15. Risksとmitigation

| Risk | Mitigation |
| --- | --- |
| ユーザー管理の同名Skillを上書き | sentinelがない同名directoryはpreflight collision |
| 壊れたmarkerでユーザー本文を誤置換 | marker重複・片側欠損・入れ子をwrite前に拒否 |
| 複数Agent同期の途中失敗 | 全対象preflight、staged apply、ChronosGraph所有部分のrollback |
| 外部rootを指す正常なinstructions symlinkを更新して非所有領域を変更 | canonical path containment、shared root opt-in、preflight collision |
| post-write検証または`all` hook setupの失敗でSkillだけが部分更新される | hook artifactを含むtransaction journal、reverse rollback、rollback failure報告 |
| mode切替で古いSave rulesが誤発火 | blockとSkill descriptionのmode guardを更新 |
| 旧Save promptと`all` managed blockの併存でAgentが直接保存する | legacy promptのread-only検出、warning、`all` preflight collision、手動移行後再実行 |
| SSOT更新漏れ | targetとcurrent sourceのSHA-256 digestを完了時に再照合 |
| dry-runの隠れた副作用 | stagingを含むwrite APIを呼ばず、filesystem snapshot testで保証 |
| 将来Agentの不確実な配置仕様 | 公式global pathsと検証方法が確定するまでadapterを追加しない |

# F2：必須電源依存の調査着手と判断待ち

#277 merge（334434c）を確認し、ローカルmainをff-onlyで更新して`fix/alternative-power-dependency`を作成した。既存branch・タグ・stashは削除/適用していない。

静的調査の結果、M-208に電源辺がないこと、InfrastructureResourceに供給状態の保存/取得/変更権限がないこと、現在の必須依存評価では同資源がUNKNOWNとなることを確認した。[影響調査と提案](../design/alternative-power-dependency-plan.md)へ根拠・具体的な変更対象・5〜7日の見積もり・PO判断事項を記録した。

今回の変更は文書のみ。製品コード・JSON・API・DB・seed・認証・稼働環境は変更しない。試験追加・実行、実API・実モデルの評価も行っていない。実装と新規試験（見込32〜48）は承認待ち。元の2 PR計画を増やさず、本F2のDraftで調査と承認後実装を扱う。

ロードマップを#277完了、F2調査完了/承認待ち、F3未着手へ更新。ガントをF2の条件付き時間軸へ追随させ、図中と本文に色の凡例を追加した。色は工程種別であり進捗ではない。未確定のF3に期間を捏造せず開始条件を独立行で示す。

文書の差分とSVGのXML構造を確認し、既存のブラウザ確認用imageでSVGを描画して凡例・工程行・文字の収まりを目視確認した。製品テストではなく文書の表示確認であり、DB/Graphの動作確認とは区別する。新しいimageは作成していない。

## B案の採用と差分計画の確定

開発者は共通必須電源と読取専用三値状態のB案を採用した。承認付き状態変更は今回実装せず、任意・未採用O-F2-WRITEとしてロードマップへ記録した。A案がF2の必須受入であるとの扱いを取り下げる。

追加指示により計画を文書化してPR #278へcommit/pushする。現時点で製品コード・JSON・DB・seed・API・UI・既存環境は変更せず、手動試験・実モデルは実行しない。pushに伴う既存CIと、新規22ケースの実行/製品検証を混同しない。

差分は製品/データ13、試験9、設計/操作/履歴10の32ファイル。新規22ケース（Backend20/Frontend2）をケースIDと失敗の対応表で固定し、2〜3.5作業日とした。従来の供給状態アダプタを包む既存試験の互換修正もファイル数へ含めた。実装・試験追加/実行はこの計画の承認後。既存Snapshot・承認カテゴリ・状態変更フォームには触れない。

公開Graph互換は専用の旧版初期データで検証する。既存5173/5174のmigrationや再seedを勝手に行わず、デモの新構成は別環境へ初期投入する手順を計画に示した。登録時刻と読取時刻を区別し、通電の実測とは呼ばない。F3のstashを保持し、既定の残計画はF2→F3の2 PRのまま。

## B案の実装承認後

開発者は918ddd7の32ファイル・追加22ケースを承認した。実装を開始し、供給状態表・読取専用role・単一SELECTの状態取得・必須依存の三値評価・代替/SPOF Evidence・v2初期JSON・資源属性表示を接続した。質問欄の9観点、更新/承認経路、既存5173/5174は変更していない。

test-designとBackend/Frontendの設計・安全性・検証Skillを適用し、追加はBackend20/Frontend2の固定22ケースとした。旧fixtureの状態未登録資源が新しいmissing_statesに含まれるため、既存3分析試験ファイルの期待値とadapterを更新する。未登録の資源状態をAVAILABLEとして埋める変更は行わない。

検証用`linescope-f2-readonly-tests`は公開ポートなしの専有network/tmpfs。既存imageとsource mountを使用し、imageのbuild/pullはしない。Frontend全78件（追加2、既存76）およびlint・型・整形・buildが成功。Backend全件は実行中で、結果は確定後に追記する。初回の対象試験では新しい未登録資源のmissing_states期待値が5件失敗し、実装契約に合わせて修正した。全件試験の最初の起動はcontainer内依存コピー権限で試験開始前に停止し、使い捨てcontainerのuserを修正して再起動した。共有環境の権限は変更していない。

直接API9要求・独立ブラウザ確認は未実施。承認を求める具体的な環境案を実装計画へ追記した。自動試験のHTTP層確認と、実サーバへの直接要求を区別する。F3のstashは未適用で、残計画はF2→F3の2 PR。

### 検証結果と停止理由

Backend全4113ケース：4101成功・11失敗・1skip、389.92秒。内訳は追加20成功、既存4081成功・11失敗・1skip。Frontend全78（追加2/既存76）は成功。Docker内ruff check/format、Frontend lint/型/整形/build、diff check、SVG XML構造検査は成功。Frontend buildには既存の大きなchunk警告、Backendには既存TestClient非推奨警告がある。終了時に`LineScope logging output failed`も出たため、成功・失敗件数とは別に記録する（元の原因を今回調査済みとはしない）。

既存Readの全項目一致・SQL bind期待と、5つのmigration固定一覧試験が新しい追加契約に追随しておらず、計6ファイル・11ケースが失敗した。6ファイルは承認済み32ファイルに含まれないため変更せず停止した。32→38ファイルへの承認を求める。追加試験は0、承認22ケースは維持する。計画時の依存試験の洗い出し不足であり、失敗を隠すための製品変更や試験の弱体化は行わない。

直接API9要求・独立環境のブラウザ確認・CIは未実施。現在の5173/5174は従前の版であり、F2最新版を配備したとは案内しない。使い捨て自動試験環境だけを片付け、追加の互換修正は承認待ちとする。PR #278はDraftのまま、mergeしない。

## 既存6試験ファイルの互換修正承認

開発者は32→38ファイルを条件付き承認した。修正は報告済みの既存試験6ファイルだけ、追加ケース0、製品コードの再変更なし。`f384e95`を保持する。以下は前回の実ログにある11件を個別に照合した表であり、成功にするための検証削除・skip/xfail化はしない。

| # | 失敗したassertion／ケース | 旧期待値 | 実際の値（f384e95） | 契約に従う修正理由・保持する検証 |
|---|---|---|---|---|
| 1 | test_reads：get_exact_record、floor、資源Readの全項目一致 | 資源マスタの全列のみ | 旧全列と同値＋registered_supply_state（UNKNOWN / record=null / DB読取時刻） | 未登録状態の追加読取項目。旧全列の完全一致を保持し、新項目とEvidenceの時刻一致も検証 |
| 2 | 同上、maintenance | 同上 | 同上 | 同上。maintenanceの認可・ID・version・Evidence検証を維持 |
| 3 | 同上、manager | 同上 | 同上 | 同上。managerの認可・ID・version・Evidence検証を維持 |
| 4 | 同上、production | 同上 | 同上 | 同上。productionの認可・ID・version・Evidence検証を維持 |
| 5 | test_reads：native値保持、資源Readのrow == expected | 同一transactionで更新した資源マスタ全列 | 旧全列と同値＋上記の供給状態項目 | 全列一致と未commit変更の可視性を維持。供給状態のDB読取時刻が同じSELECTの_observed_atと一致することを検証 |
| 6 | test_reads：UUID bind、list(params.values()) | 要求UUIDのbind 1個のみ | 要求UUIDのbind 2個＋固定JSONキー/defaultのbind 13個 | マスタと供給状態subqueryの両方が同じUUIDをbind。15値の厳密な多重集合一致、UUID 2個、SQLへのUUID文字列非埋込、execute 1回を検証。他Toolは従来の1bindの完全一致を維持 |
| 7 | test_projection_storage：db.migrate()の完全一致 | 006〜013 | 006〜014 | 新migration014追加のみ。一覧の順序・再適用なし・既存要求保持・架空Outboxなしを維持 |
| 8 | test_business_schema：db.migrate()の完全一致 | 002〜013 | 002〜014 | migration一覧と、その後の厳密なテーブル一覧に新表を追加。既存業務データ・schema境界の検証を維持 |
| 9 | test_execution_history_schema：db.migrate()の完全一致 | 005〜013 | 005〜014 | 同上。既存の承認待ち要求・架空履歴なしの検証を維持 |
| 10 | test_update_request_schema：db.migrate()の完全一致 | 003〜013 | 003〜014 | 同上。既存業務行保持とpackaged migrationの検証を維持 |
| 11 | test_foundation：並行migration結果の完全一致 | 一方は空、もう一方は001〜013 | 一方は空、もう一方は001〜014 | 新migration014追加のみ。一回適用・順序・checksum変更拒否の検証を維持 |

### Read契約の後方互換性の確認範囲

`get_infrastructure_resource`は既存の要求形式・認証認可・主キー・マスタversion・名称・種別・active・時刻の型/値を変更せず、`registered_supply_state`だけを追加する。状態行なしはUNKNOWN/record=nullで、既存フィールドへ既定値を上書きしない。外側Envelope/Evidenceの形式も維持する。

RepositoryのFrontend `Envelope.data`は`Record<string, unknown>`、envelope検査はdataがobjectかを確認し、追加fieldを拒否しない。Graphのdetail/labelとAgentのregistered_question_readは既存field名を参照し、追加キーの存在で意味を変更しない。旧fieldの全項目一致を維持した上記試験と既存回帰で照合する。Repository外の未知の厳密なconsumerまでは確認できず、その互換性を保証したとはしない。既存の公開契約に削除・型変更・要求変更は確認されていない。

再検証は公開portなしの専有tmpfs DB/Neo4j/Qdrantと既存image、現行source mountを使用する。5173/5174へ配備・再seed・認証変更は行わない。CI・独立HTTP9要求・製品ブラウザ確認はこの再検証と区別し、未実施を成功扱いしない。


全件再検証の初回実行中、既知のtest_schema_boundary_and_upgrade_from_foundationの後続assertionにも新表を追加する必要があるとコードレビューで確認した。同じ承認済みファイル・同じ既知失敗ケースの範囲でテーブル一覧の完全一致を維持する修正を行うため、専有runnerを停止し、専有DB/Graphを初期化して全件を最初から再実行する。中断した部分実行を全件成功の根拠にしない。製品コードと追加ケース数は変えていない。

### 互換修正後の最終ローカル検証

- Backend全4113ケース：**4112成功・失敗0・既存skip1**、397.63秒。JUnitでもfailures/errors=0を確認。承認済み追加20ケースを名前で抽出して20成功、既存回帰4092成功・skip1と分けて確認した。先の11件はいずれも成功し、11件以外の新たな退行はなかった。skipは既存のopt-in実モデル試験であり、今回追加していない。
- Frontend全78ケース：**追加2成功・既存76成功**。Docker内`npm test -- --run`を再実行。`npm run check`のlint・型・整形・buildも成功。既存の大きなchunk警告は残る。
- Backend Docker内ruff check/format：成功（406ファイル整形済み）。diff check・SVG XML検査も成功。6試験ファイルのASTで試験関数・parametrizeがf384e95と同じであることを確認し、追加ケース0を照合した。
- 修正した試験コードは承認済み6ファイルだけ。製品コード・Frontendコードはf384e95から無変更。履歴・計画・ロードマップ・ガントは結果に追随させる。f384e95の履歴は維持する。
- 前回同様、既存TestClient非推奨警告と終了時の`LineScope logging output failed`が出た。これを今回原因調査・修正済みとはしない。pytestの終了コード0とJUnit件数とは分けて記録する。
- 検証専用container/network/tmpfsを削除する。5173/5174のcontainer・DB・volume・認証・seedは変更していない。CI・独立HTTP9要求・製品ブラウザ確認は**未実施**。5173/5174がF2最新版とは案内しない。PRはDraftのまま、mergeしない。今回の互換修正はローカルcheckpointに保存し、push/CIは未実施として報告する。

## 実装pushとGitHub CIの確認

開発者の指示により、clean tree・origin・対象枝`fix/alternative-power-dependency`・PR #278の接続先を確認し、f384e95とfba058aを通常pushした。履歴書換え・force push・mergeはしていない。PRはDraft。

実装head fba058aa69153b6aa445ac1866b3ac0570e56811の[GitHub CI](https://github.com/philippos2/line-scope/actions/runs/40302308261)は全成功。Backend shard1は1982成功・skip1（315.06秒）、shard2は2130成功（228.42秒）、合計4112成功・skip1。両shardのcollectionは4113、SHA256はともに540446288d8b84b2ac505674ab9d7bc828ed8632388fc4c9a6aa9374dcb09a65で一致した。Backend lint/format、Frontend lint/型/整形/build、runtime startup/migrations、対象判定、集約check、PR titleも成功。

FrontendのCIはVitestを実行しない。78件と追加22件の個別確認は前段のローカル結果であり、CIと混同しない。既に成功したローカル全件試験は重複実行していない。

直接API9要求とブラウザは未実施。独立環境の名称・ポート・DB・一時認証・資源上限・初期化と片付けを実装計画へ具体化した。操作は別承認待ち。今回、既存5173/5174にも新しい検証環境にも環境操作を行っていない。今回の文書追記headの対象判定・CIは実装headのBackend実行と区別して確認する。

## 隔離環境の直接API・ブラウザ最終確認

開発者が、既存image/試験Composeの再利用、三値それぞれ独立した初期DBによる9要求、AVAILABLEのブラウザ確認、確認後のプレビュー維持を承認した。製品版は9145f13（製品ソースはfba058aと同じ）。APIのmodule pathも`/repo/backend/src/linescope/__init__.py`で現行source mountを確認した。製品コードは変更していない。

### 環境と保全

専用projectは`linescope-f2-api-check`、APIは127.0.0.1:8178、Frontendは127.0.0.1:5178。PostgreSQL 18.6とNeo4j 5.26.31-communityは専用network/tmpfs、DB port非公開。API/Frontend/ブラウザも既存imageを使い、build/pullしない。DB初期化はadmin接続、APIはruntime/Readはquery、一時manager tokenで認証。LLM・GPU・Qdrantは使用しない。

UNAVAILABLE→UNKNOWN→AVAILABLEの順に検証し、条件間で専用container/network/tmpfsを破棄して新規初期化した。各状態の一時v2 JSONを初回seed・初回Rebuildへ渡し、既存状態のUPDATEやseedによる上書きはしていない。AVAILABLE環境だけを最後に残した。APIの正常性確認GETやUIから発生するReadは、以下の9件とは別。

初回の検証設定には一時DBパスワードの桁数不備（既存の64桁要件）と、初期JSONのコンテナ読取権限不備があった。いずれも検証用設定だけを修正し、製品コード・共有環境は変更しなかった。業務Readの9要求開始前の失敗で、成功9件へ含めていない。初期投入用adminだけを管理用UIDで実行し、業務APIに初期投入用秘密ファイルをmountしていない。

作業前後で既存15コンテナのID・image・Mounts・公開portが一致。5173/5174のコンテナ・DB・volume・seed・認証・データに操作を行っていない。prune・既存image削除・既存volume操作はしていない。

### 実HTTPの直接API9要求（模擬応答ではない）

各行とも、同じ初期状態の専用APIへPOST /agentの明示find_alternative_pathsを3回。重要対象P-100/P-200、除外M-204、候補M-208で検証した。M-208は全条件でRUNNING。

| R-02の初期登録状態 | 実行回数 | 毎回のM-208構造 | 毎回の利用可能性 | 応答時間（秒・実行順） | 判定 |
|---|---:|---|---|---|---|
| AVAILABLE | 3 | ESTABLISHED | AVAILABLE | 1.881 / 0.199 / 0.114 | 期待一致 |
| UNAVAILABLE | 3 | ESTABLISHED | UNAVAILABLE | 1.766 / 0.124 / 0.121 | 期待一致 |
| UNKNOWN | 3 | ESTABLISHED | UNKNOWN | 1.949 / 0.272 / 0.136 | 期待一致 |

全9回でR-02のcurrent_resource_states・supply_state・record_reference（資源IDとversion1）・state_versionsを照合。各状態の3回でversion・registered_at・sourceは不変で、DB読取時刻state_observed_atは別に保持された。構造候補を削除せず、供給不可・不明を利用可能へ昇格させていない。これらの時刻を実通電観測とは扱わない。

### ブラウザ確認（AVAILABLEの実API・応答置換なし）

- M-204とM-208それぞれの上流Graphで共通電源R-02を確認した。双方の選択欄で供給可能・出典・状態version1・登録時刻・DB読取時刻を確認した。供給状態の入力/選択/更新buttonがないことも確認した。
- M-204の代替提案でM-208が利用可能と表示され、P-100の能力充足と運転許可ではない限定が維持された。
- ブラウザが受信した代替分析Evidenceのcurrent_resource_statesを確認し、資源の技術情報を実際に開いてregistered_supply_state・record_reference・登録/読取時刻を照合した。JavaScript例外0。
- UNAVAILABLE/UNKNOWNの画面表示は今回の実ブラウザでは未確認。両状態の業務判定は上記実APIで確認し、表示の自動試験結果と区別する。全画面や書込み機能の実通し確認をしたとは報告しない。

### 資源の実測と維持するプレビュー

最初はPostgreSQL512MiB/0.5CPU、Neo4j1024MiB/1CPU、API256MiB/0.5CPU、Frontend384MiB/0.5CPU、ブラウザ512MiB/0.5CPUを上限として実施した。docker statsの採取値は次のとおり（厳密な瞬間最大値の保証ではない）。

| component | 採取したメモリ最大MiB | 採取したCPU最大%（100%=1論理CPU） |
|---|---:|---:|
| PostgreSQL | 85.29 | 6.19 |
| Neo4j | 1003.0 | 106.66 |
| 初期投入admin（一時） | 78.87 | 4.87 |
| API | 102.2 | 28.65 |
| Frontend | 376.0 | 26.25 |
| headless Chromium（一時） | 368.3 | 50.08 |

同時採取分の合計最大は1752.35MiB、CPU129.45%（約1.29論理CPU）。個別componentの最大値を足した同時値ではない。OOM kill・再起動は0。Neo4jとFrontendが当初上限へ近づいたため、データを変えずdocker updateで当該コンテナだけ1280MiB/512MiBへ増やし、ID・再起動回数が不変であることを確認した。現プレビューの上限合計は2.5GiB・2.5CPU枠であり、5GiB・8CPU前提にはしていない。

検証runner・ブラウザは終了済み。AVAILABLEのAPI・Frontend・PostgreSQL・Neo4j、一時認証は開発者のブラウザ確認用に維持する。終了指示を受けるまで削除しない。秘密値は公開履歴に載せず、privateな検証記録/一時認証ファイルに保持する。ブラウザURLと認証ファイルの場所を開発者へ案内する。PRはDraftのまま、mergeしない。

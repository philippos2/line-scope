# 能力・需要・納期の着手調査

## 再開地点と進捗

#247のmerge commit db3cac00c3859a159cb66400cd6b9b81565da327を確認し、mainをff-only更新。作業ブランチはfeat/capacity-inputs。全体進捗は約70%（65〜75%）、残り10〜17 PR、中心14 PR前後。紹介動画は除外する。経済入力の代表経路の接続完了を全業務受入完了とは扱わない。

## 正本と未決定事項

requirements §14.3 PO-B03および能力情報のPO-B07は未決定。business-scenarios BS-05・06・13とBS-G01、UC-B02・03・11を次工程の根拠とする。前の経済入力承認や#247 mergeから能力情報の権限を導かない。この記録の案は未承認であり、正本・DB・API契約として有効化しない。

開発者へ提示した業務案は、同一製品・単位・期間での能力比較、使用中・予約負荷を差し引いた利用可能能力、不明値UNKNOWN、互換性の明示登録、一定需要・供給とbuffer引当等の条件付き復旧期限である。閲覧はmaintenance / production / manager、要求はmanager、別manager承認、requester確定を提案した。回答は未確定のため採用済みと記録しない。

## 実コードの接続箇所

- application/economics.pyのEconomicInputsは信頼済みContext、正規化、query接続による読み出し、ProposalStoreによる保存を所有する。HTTPに業務判定を追加せず、能力にも同じ責務分離を適用する候補。
- 同ファイルのEconomicApproval / EconomicExecuteは共通Approval / Executeの枠組みに接続し、対象照合・lock・書込みを分担する。これは経済カテゴリに閉じており、名前だけ置換して能力へ流用できない。
- application/proposals.pyはカテゴリ別要求・閲覧権限を明示する。能力追加時にはSnapshot、保存要求、履歴、再送・確定済み応答まで一貫した境界を設計する必要がある。
- domain/economics.pyはDB非依存の入力正規化・サーバ計算を所有する。能力計算も純粋な業務層へ置く候補であり、FrontendやLLMに計算を委ねない。
- domain/demo_comparison.py / demo_scenarios.pyのrequired_capacity / available_capacityとdomain/demo_constraints.pyはMOCK_FIXTURE専用。正式入力を既存fixtureへ混ぜず、Graphの構造判定から実能力・互換性・安全を推測しない。
- data-modelの拡張候補は製品・期間別能力／負荷／必要量、calendar、buffer等を列挙するが、登録主体・意味はPO-B03等に依存する。現時点で新規カテゴリ・テーブル・Toolを確定しない。

## 具体化する業務境界（未承認案）

能力率と期間総量を別扱いにする。同一製品・単位・評価期間で必要能力と利用可能能力を比較し、明示的な互換性と情報の有効期間を確認する。予約負荷と使用中負荷は重複して控除しない。重複・網羅性を確認できなければ結果はUNKNOWNとし、負の空き能力を黙ってゼロへ補正しない。

期限はbufferを消費する毎時不足量が正で一定の場合に限って候補値を計算する。停止開始、計算の有効期間、他の供給・引当、復旧後の充足条件を示す。一般の納期順引当・可変需要・稼働calendarをこの単純モデルで解いたとは説明しない。不足ゼロから無期限の納期保証を導かない。期限の端数精度・丸めも契約化前に決める。

## 受入候補とPRの区切り

最初の機能単位は登録・訂正→別承認者承認→要求者確定→正式入力からの能力充足／不足表示とする。後続で条件付き期限・Agent参照・画面を接続し、2〜3 PRの見積もりを維持する。内部部品だけを独立PRにして進捗扱いしない。

受入の核はBS-05の60対80の能力充足、BS-06の90対60の不足30、BS-13のbuffer120／毎時不足30の条件付き4時間。これらは固定fixtureの期待値であり一般業務ルールの承認ではない。製品・単位・期間不一致、入力欠落、予約重複、互換性不明を成功へ丸めない。安全・品質・Graphの成立条件は独立に表示する。

更新・認可は自己承認拒否、現在role確認、version競合、同一retry、失敗時rollback、Snapshotと履歴の一致を確認する。組合せ試験の実装前にtest-design Skillで展開件数を算出する。新規ケース20超は事前に了承を求める。今回は試験コードの追加・実行を行っていない。

## 現在の状態

ロードマップへ#247 mergeと70%／残10〜17 PRを反映。ガントの#243後baselineは維持し、経済入力の表示を接続済みに更新した。実装コード・DB・権限・業務規則は変更していない。次の依存作業はPO-B03と能力情報のPO-B07の意味確定であり、未回答を時間経過や一般の作業継続指示だけで採用扱いしない。

## PO回答と実装開始

開発者から「その案で進めろ」と回答を受け、提示済みPO-B03・能力情報のPO-B07を採用。requirements / domain-model / access-controlへ反映した。過去の未回答記述は回答前の経緯であり、現在の判断待ちを示さない。安全・計画・故障・インフラ等は本回答で確定しない。

最初のPRは正式能力入力の登録・訂正・別manager承認・元requester確定、検索・取得、単一製品の能力差・条件付き期限のサーバ計算。画面・Agent接続を後続とする。承認済み経済Snapshot v2や既存v1を変更せず、CapacityInput専用v3を追加する。製品FKを追加し、同一製品・単位・期間を一入力へ閉じる。数量値の厳密な十進文字列・text helperだけをinput_valuesへ分離し、経済の業務計算は維持する。

追加試験はdomain 8・実PG/HTTP 12の20件を予定。認可・version競合・並行再送・CREATE競合・監査失敗rollbackを明示し、無条件直積を作らない。初回実行は新規import名capacitysの誤りにより収集段階で停止し、capacityへ修正して再実行する。

## 関連検証とレビュー

import名修正後の関連実行は28成功・12失敗。HTTP handlerの依存名services.capacitysがcomposition rootのcapacityと不一致だったため、全能力HTTPが500となった。capacityへ修正後、能力20件＋既存経済20件の計40件が成功（5.64秒）。新規試験を削除せず配線を修正した。以後、同じ登録シナリオで検索候補・自由文字列のbind・payload非公開を確認し、既存DB role試験へ実runtime/query経路とprojection拒否を拡張した。新規展開ケース数は20件のまま。

lockはRequest→Approval→設備KEY SHARE→製品KEY SHARE→入力UPDATEで、FKとversionの再検証を承認時／確定時に実施する。経済カテゴリの現在閲覧roleによる保存要求・COMPLETED再送の制御を能力にも明示適用し、floorへ過去要求の内容が露出しない。計算・HTTP・Application・Coreの責務を分離し、SQL値はbindする。Capabilityの追加をAgentの承認・確定権限へ転用しない。

Docker内ruff checkは成功。全体回帰・CIは確認中。今回の変更で通常デモ環境・Ollama・Qdrantデータには変更を加えていない。能力入力の画面・Agent接続、Graphと安全を含む全BS受入は後続。

## 全体回帰の結果と対応

ローカル全体回帰は3859 passed / 3 failed / 1 skipped、354.12秒。失敗はGraph migration upgradeとfoundationのmigration一覧への009追記漏れ、および未対応schema_versionを3としていたDB拒否試験。今回v3を実装したため未対応versionを4へ更新し、拒否検証自体は維持した。対象2一覧を更新し、関連試験を再実行する。skipは既存opt-in LLM。既存Starlette/httpx警告と終了時logging output failedが残る。

BS-05の必要60・利用可能80、BS-06の90・60、不足30、ゼロ必要量・ゼロ空き能力を3つの既存新規ケースへ明示した。ケース数は追加せず、固定fixtureとの対応を改善した。20件の新規追加という当初範囲を維持する。

修正後の能力・DB role・migration・Snapshotを含む対象177件は全成功（16.73秒）。Docker内ruff check / format checkも成功。最終全件はPR #248の最新headに対するCIで確認する。

## 業務経路単位へのPR再集約

開発者の指示により、Backend APIと画面・Agentを別PRにする区切りを取り下げ、#248へ製品候補検索・入力フォーム・計算表示・Agent Read・実ブラウザをまとめる。旧残10〜17 PRは現在の粒度に対する見積もりではない。ロードマップを業務機能・具体的な残項目・完了条件・状態の表と工程枠のガントへ書き直し、今回を含め6〜11 PR、中心8〜9へ再集約した。機能や必要な検証を対象外にせず、分割変更を作業量の減少とは説明しない。再集約前の文書は履歴へ保存した。

Frontendは候補選択・編集・表示を分け、数量計算を持たない。製品のcode・UUIDを暗記せず名前／codeから選択し、訂正時の対象は不変。空欄null・0・互換性不明と負荷／復旧前提の未確認を保持する。編集内容ごとのretry key、閉じる／解除のabort、確定後の古い表示と再取得を既存経済入力と同じ境界で実装した。Agentへは検索・取得だけを追加し、単一正本のサーバ結果から要約する。

新規pytest展開件数は20のまま、登録の実PGシナリオへ製品候補・Agent呼出し・Evidence・自由説明の置換を接続した。初回75件中1失敗は試験がEvidenceをdata.tool_results内と誤認した点。正しいenvelope.evidence.tool_resultsを検証する修正後75件成功（6.24秒）。表示名を追加した後の関連56件も成功（4.79秒）。既存Frontend 27件成功（2.11秒）、Docker内lint・型・format・build成功。新規Frontend Unitは増やさず主要状態と認可の実経路を実ブラウザで確認する。

実ブラウザ1回目は実モデルの初期設備検索でAGENT_LIMIT_REACHEDとなり能力フォーム前に停止。モデル取得・fallback・60秒上限変更は行わず、2回目で再確認中。CIが成功した61d42c6はAPI段階であり、未pushの画面・Agent追加のCI成功として扱わない。

## 実ブラウザ代表経路と引渡し管理

2回目の実ブラウザはPASS。実モデルのsearch_equipmentから設備を選択し、製品候補P-100を名前／code検索で選ぶ。フォーム登録→自己承認拒否→別manager承認→元requester確定→登録値の不足30・条件付き4時間表示→実モデルget_capacity_inputによる参照まで確認した。さらに訂正フォームの予約負荷20を空欄へ変え、別manager承認・requester確定後のversion 2、利用可能能力・復旧期限null、UNKNOWN表示を確認した。出典をHTMLとして実行せず、1440 / 768 / 390pxの横overflowなし、storage保存なし、接続解除時の消去もPASS。専用環境のfinally cleanupを確認する。

開発者の指示に従い、最新差分のCI確認前の#248をDraftとし、タイトル末尾に【WIP】を付ける。継続運用の規則だけをCONTRIBUTINGへ追記する。CONTRIBUTING全体の文章・構成整理は後続PRの適切な機会に行う依頼としてここへ記録し、今回の機能実装へ無関係な全面整理を加えない。

確認コマンドは `python3 scripts/verify_frontend_flow.py --docker-group docker --llm-model qwen3:30b-a3b-instruct-2507-q4_K_M --capacity-only`。モデルは導入済みqwen3:30b-a3b-instruct-2507-q4_K_Mを使用し、新規取得・自動fallback・Agent上限変更なし。画像はローカル/tmp/linescope-frontend-1440.pngおよび390.pngで確認する。一般LLM品質の保証ではなく、登録・訂正・参照の一代表経路の結果である。

## 開発ガイダンス変更の実施時期の訂正

CONTRIBUTINGへのWIP規則追記も全体整理も後続PRで行うという指示を、追記だけ今回実施と誤解した。開発者の訂正に従い、#248からCONTRIBUTINGの変更を外す。後続PRでWIP規則の追記と文章・構成整理をまとめる依頼として保持する。#248のDraft・タイトル末尾【WIP】はCIと引渡し確認が終わるまで維持する。GitHubへpush済みの履歴は書き換えず、追加commitで取り消す。

## 残工程のPR数の直接表示

開発者から残項目と各工程のPR数を明記する指示を受け、ガントの各横棒へ能力1、安全1〜2、計画・履歴1〜2、インフラ0〜1、総合受入・品質2〜3、運用1〜2 PRを直接記載した。合計6〜11は今回#248を含む。工程枠の幅だけから数を読み取らせず、ロードマップ表と対応させる。能力の表示は代表経路検証済み・最新CI確認中へ更新した。機能範囲の追加ではない。

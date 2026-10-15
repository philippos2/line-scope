# Frontend オペレーション画面の設計

要件の正本は[requirements §13](../requirements/requirements.md#13-後続frontendフェーズ)、業務目的は[Use Case](../requirements/use-cases.md)、権限は[access-control](../requirements/access-control.md)、APIは[api-tools](../implementation-design/api-tools.md)。本書は現バックエンドへ接続する画面・実装計画であり、新しい業務データや規則を定義しない。

## 最初に通す体験

M-204の異常をエンドユーザーが認識し、問い合わせる → 現在状態と影響候補を確認 → 仮置き条件による対応案比較 → Evidenceと不足情報を確認 → 必要なら明示Prepare → 別の承認者がSnapshotを確認してApproval → 元requesterがExecute → 更新後を確認する。

自動異常検知・Incident一覧・工場全体の損失集計は追加しない。初回は既存の分析経路と実際の更新を画面で利用可能にする。架空のSeverity、Location、工場全体KPIを表示しない。

## 情報構造と画面案

[画面案HTML](frontend-console-prototype.html)はローカルで開くレイアウト確認用の固定データで、API接続・認証・更新は行わない。表示値は説明用fixtureであり業務正本ではない。

左に取得済みObject、中央に調査ワークスペース、右に問い合わせと直近回答、必要時にEvidence / Actionの詳細領域を開く。中央は「影響・比較・根拠」を切り替える。影響タブではGraphを大きく、比較タブでは費用・時間・不明事項を大きく表示する。Graph中心案の探索性と、Situation→Decision案の判断しやすさを組み合わせる。

初期画面は問い合わせ入力と設備検索・代表質問を示す。分析前にKPIやCURRENTを表示しない。結果が返った後は対象、観測情報、デモ入力の有無、partial / completeを常に確認できるようにする。空・読込中・失敗・権限拒否を結果の表示と区別する。

Object Explorerは「今回取得したObject」を表示する。全設備一覧・全体件数・網羅的な検索画面を装わない。Graphは代表経路のtyped node / edgeから描画し、直接・間接は返された分類に従う。名前がなければ種別と短い識別子を表示し、詳細で完全IDを確認できる。fixtureのID→業務コード対応を本番表示へ埋め込まない。

意味色を文字ラベルと併用する。暗いnavy / graphiteを基調とし、影響経路は控えめなaccent、unknown / partialは注意色にする。設備のSTOPPEDとGraphのCURRENTは別の意味で表示する。CAN_SUBSTITUTEの保存方向と影響方向を混同しない。Graphだけから停止・安全性・能力充足を判定しない。

## APIと表示の対応

| 操作・表示 | 既存API / 結果 | UIの責務 |
|---|---|---|
| 問い合わせ | POST /agent、message / context_id / as_of | contextと要求を区別。通常調査・明示Prepareを区別して送る |
| 状態と判断材料 | data.decision_package.equipment / impact / comparison / maintenance / summary | 現在状態とMOCK_FIXTUREの比較入力を分ける。nullを0へ変換しない |
| 通常Graph調査 | data.tool_resultsのGraph結果とevidence.tool_results | 経路・分類・complete・limit_reason・分析時刻を同じ結果から表示 |
| Evidence | evidence、計算式・入力・引用・保全根拠 | 対応する結論から詳細へ移動。見つからない情報を補完しない |
| Prepare結果 | POST /agentのdata.update_request_id等 | 明示クリック時だけ送信し、before / proposedを表示 |
| 保存要求の確認 | GET /update-requests/{id} | サーバ保存Snapshotとhashを確認し、古い分析から再生成しない |
| 承認・拒否 | POST /approvals/{id}/approve、/reject | approveは保存snapshot_hashを送る。エンドユーザーが操作する |
| 実行 | POST /update-requests/{id}/execute | 元requesterの明示操作。確定afterとcurrent_snapshotを分ける |
| 接続確認 | GET /health /health/ready | readinessはPGの確認。Graph・RAG・モデル全体のReadyにしない |

UIにToolsを個別HTTP公開するためのAPIを追加しない。Graph・モデル・RAGの未観測状態は未確認と表示する。役割を自己申告して権限を決めない。初回はBearer token入力で/session/loginへ接続し、再読み込み時は/sessionでセッションとidentityを確認する。role / user_idを画面で推測しない。操作可否の最終判定はサーバの認可に従う。

## 更新操作とセキュリティ

Bearer tokenは初回接続時だけ送信し、サーバ側のセッションに保持する。ブラウザではHttpOnlyのopaque cookieで接続を復元し、localStorage、sessionStorage、URL、ログへtokenを保存しない。上部の接続設定で接続切替・解除を行い、解除はサーバセッションと取得済み結果・context・変更要求を消去する。F5で認証状態を復元するが、分析結果の永続復元は行わない。開発用Frontend proxyから同一originのAPIへ接続し、BackendのCORSを広げない。

分析・Prepare・Approval・Executeを別操作にする。分析でデータを変更せず、Agent応答から自動approve / executeしない。承認対象はサーバSnapshotであり、LLM回答ではない。承認者へ切り替えるときは接続解除して別tokenで対象要求を読み直す。requesterへ戻すときもサーバ状態を読み直す。

更新要求IDとretry keyを区別する。Prepareは同じ操作の再送で同じIdempotency-Keyを使い、内容変更時は新しいキーを使う。成否不明時に書込を無条件で自動再試行しない。Approve / Execute後は保存要求を読み直し、サーバ確定結果で表示を更新する。30分期限はサーバが判定し、画面時計を権限根拠にしない。

LLM / 文書 / Toolの文字列はtextとして表示する。HTML実行・任意URLへのtoken転送・内部推論の表示を行わない。新しい調査の送信中は前の結果を未確認の最新状態として示さず、古い結果と明示する。遅れて返った過去の応答が新しい結果を上書きしないよう要求を識別する。

## 実装の構造

React / TypeScript / Viteを使用し、依存versionはlockfile、Node imageはDockerfileのdigestで固定する。Graph描画ライブラリは実際の経路を描いた操作性で選ぶ。最初からReduxや汎用Plugin基盤を入れない。

```text
frontend/src/
  app/          接続状態・画面組立
  api/          HTTP、Envelope、公開エラー、要求の再送制御
  features/
    investigation/ 問い合わせ・結果の連動
    graph/         サーバ経路の表示変換と描画
    decision/      比較とunknown表示
    evidence/      根拠の詳細
    actions/       Prepare / Approval / Execute
  components/   共通表示部品
```

対応Unit Testは同じ責務の近くに置き、業務E2Eは別にする。表示変換に依存関係探索・費用計算・認可を実装しない。

## UI受入条件

| ID | 条件 | 対応する業務範囲 |
|---|---|---|
| UI-01 | 実APIへ問い合わせ、対象・回答・Graph・Evidenceを連動表示 | UC-B01 / 15、BS-01 |
| UI-02 | partial / 不完全探索 / 非CURRENT / 未確認を正常完了へ変換しない | UC-B13、BS-08 / 09 |
| UI-03 | 比較のMOCK、unknown、除外理由、未評価を保持し、数値を再計算しない | UC-B03〜10 / 13、BS-02〜06 / 10 / 11 |
| UI-04 | 明示Prepare→Snapshot確認→承認者Approval→requester Executeを分離 | UC-B14 / 16、BS-14 / 17 |
| UI-05 | 確定afterと最新current、分析観測時刻と過去指定を区別 | UC-B17、BS-18 / 19 |
| UI-06 | tokenを永続化・ログ出力しない。文字列をHTML実行しない | access-control / 非機能Security |
| UI-07 | キーボードで主要操作、focus表示、見出し・状態ラベル、Graphの一覧代替表示 | requirements §13の操作体験 |

ケース追加前にtest-designの因子・境界・重複・件数を見積もる。全組合せを生成しない。最初のAPI接続・Graph表示は実バックエンドでも確認し、fixtureのみの画面成功を結合受入にしない。

## 実装到達点（#236後）

React / TypeScript / Viteで実APIへ接続する分析・比較・Evidence画面を実装した。Graphは返却された代表経路をSVGで描画する。React Flow等は導入せず、必要性が明確になった場合に評価する。Bearer tokenはbrowser storageへ保存せず、Backend非CURRENTのGraphを表示しない。

UI-01〜07の代表経路を段階的に確認している。#240で現在状態変更のPrepare / Approval / Executeを実ブラウザ確認。本仕上げでは実Embedding / Qdrantの引用応答、4業務カテゴリと拒否、主要キーボード操作・focus・1440 / 768 / 390pxの表示を確認する。期限切れ・version競合・現在値取得失敗は固定API応答によるUI Unitでサーバ判定を保持することを確認し、実DBの認可・transaction試験と区別する。全更新variant・端末・支援技術の包括的受入、全BS / Golden、一般LLM品質は未完了。実測結果と残件は[UI受入履歴](../history/2026-10-15-frontend-acceptance.md)、現在の残作業は[roadmap](../roadmap.md)、検証方法は[Frontend README](../../frontend/README.md)を参照する。

## 初期工程計画（#231時点）

| 工程 | 一つのPRで通す体験 | 概算PR |
|---|---|---:|
| 画面設計 | 本設計と画面案、API対応・受入条件 | 今回1 |
| 分析ワークスペース | Docker起動・認証入力→実API→Graph / 回答 / Evidenceの表示、CI | 1〜2 |
| 比較・根拠 | Decision Packageの比較・不足・式と引用の詳細、結果連動 | 1 |
| 承認付きAction | Prepare→保存Snapshot→Approval / Execute→更新後確認 | 1〜2 |
| UI仕上げ・受入 | レスポンシブ、キーボード、実シナリオの画面受入とガイド | 1 |
| 修正予備 | 実画面レビューで判明する不具合 | 1〜2 |

設計時点の概算は5〜8 PR。相対的には分析接続とActionが大きく、見た目だけの小PRを完了単位にしない。正式入力・全BSはこの見積もりに含めない。

```text
PR枠                12345678
分析ワークスペース  ██······
比較・根拠          ··█·····
承認付きAction      ···██···
UI仕上げ・受入      ·····█··
修正予備            ······░░
```

外部AIへのレビューが必要なら、この画面案と情報の優先順位・Graphと比較の面積・承認境界を具体的な論点として共有する。外部AIへ自動送信しない。

## 設備コードを暗記しない対象選択

「設備を探す」は既存POST /agentへ送る検索文の下書きを作る。送信はエンドユーザーが明示操作する。直近のsearch_equipment結果のitemsから設備名・コードの候補を表示し、候補の選択で取得済みequipment_idを含む現在状態・下流調査文へ差し替える。選択だけで送信・Prepareしない。選び直した対象には前のconversation contextを付けず、サーバが参照時に存在・認可を再検証する。

取得候補は工場全体の一覧・現在状態としない。next_cursorがあれば続きが未取得と明示し、名称などによる絞込みを案内する。空・不正形・古い結果を区別し、処理中・再調査失敗後の候補は選べない。比較デモはM-204の固定シナリオである旨を表示し、一般の設備調査と区別する。新しいTool公開HTTP APIや架空のライン・場所・稼働状態は追加しない。

## 正式経済入力の業務経路

「正式な経済・損失入力」で登録済み入力を設備名・コード・入力コードから検索し、候補を明示選択する。取得時の比較期間・稼働時間・version・出典、案別見積総額／既知小計と未知・非独立・非網羅を表示し、UIで再計算・最安順位付け・安全判定をしない。MOCK_FIXTUREの比較デモは独立して表示する。

新規登録は既存の設備検索候補で設備を選択した後にフォームを開く。訂正は取得済み入力を読み込んでpayload全体を編集し、ID・設備・入力コードを変更しない。金額／時間の空欄はnull、明示0は文字列0として保持。項目の適用期間の空欄は、フォームで明示した共通比較期間を使うことを表示し、保存Snapshotで確認する。網羅性・独立性のチェックを自動で肯定しない。Prepare後は要求IDを既存Action画面へ渡し、別managerが保存Snapshotを承認、元requesterがExecuteする。

登録値は取得時の結果であり、確定操作後は再取得を促す。選択記録をAgentへ問い合わせるボタンはID付き質問の下書きだけを作り、送信は明示操作。接続解除・接続切替時に検索結果・編集状態・再送キーを破棄し、AbortSignalと応答確認で遅延応答の復元を防ぐ。新しい編集を開くと未保存値をリセットする。

## 正式能力入力の業務経路

能力入力パネルは設備候補と製品名／code検索から登録対象を選び、同一製品・数量単位・期間の必要能力・通常能力・使用中／予約負荷を明示入力する。互換性は不明を初期値とし、負荷の重複なし・網羅性・復旧条件を自動肯定しない。数量の空欄はnull、0は文字列の0として保持する。

明示Prepareの保存要求を共通Actionへ渡し、別manager承認・requester確定を分離する。同じ内容の再送は同じretry key、内容変更時は新しいkeyを使う。計算表示はサーバ値を使い、能力充足を完全代替・安全と表現しない。登録値の検索・訂正フォーム読込・再取得と、選択IDを含むAgent質問の下書きを提供する。Agent送信は別の明示操作。確定後の結果は再取得を促し、接続解除で画面を破棄・遅延応答を無視する。出典はtextとして表示する。

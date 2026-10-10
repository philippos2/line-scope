# Projection適用・APPLIED保存境界

2026-10-11。PR #112 merge後のmain `4186bbc`を起点とする。

## 対象

- 通常workerの内部ProjectionApplicationを追加。leader → exclusive mutation lock → 短い保存状態確認 → adapter commit → 短いAPPLIED保存の順を実装。
- 再検証は固定SQLAlchemy Coreとbind parameter。PROCESSING / ID / attempt / 開始時刻が一致し、DB時刻でlease有効、DEADなし、control存在、rebuild=false、fatalなし、generationありを要求する。APPLIED保存では同じgenerationも要求する。
- 外部I/O中はOutbox / control行lockを保持しない。mutation transactionはAPPLIED commitまで維持する。leaderを各境界とcommit前後で確認し、adapter後はmutation接続の生存・transaction isolationも確認する。
- 利用者から渡されたpayloadではなく保存payloadを正規化検証し、aggregate列との一致を確認する。adapter例外・保存障害をAPPLIEDにしない。Graph commit後の保存失敗はPROCESSINGが残り、lease回収・冪等再送で復旧する。

## 実装契約と未実装

内部adapterはgeneration / outbox ID / canonical payload / leadershipを受け取り、単一Neo4j transactionのmarker lock・version / hash比較・edge置換・marker更新・commit、または同version / 古いversionのmarker確認を完了してから戻る。adapterの実装は次工程。現在のRecordingAdapterはテスト専用でありGraph stateを変更しない。

通常workerの境界はrebuild中を拒否する。controller drainへそのまま転用しない。実Neo4j、heartbeat、controller、専用role、起動loop・運用ログは未実装。HTTP / Tool / migration / 業務意味・権限を変更せず、LogiScope再利用もない。

## 検証

Docker内の対象91件成功（追加25件、10.53秒）。ruff check / format check成功（144 files）。Docker内の全体回帰テストは2396 passed / 1 skipped / 1 warning（175.70秒）。AC-13 / 18、NFR-04〜06、T-SQL04、test-plan §6のProjection境界の部分検証であり、実Graph適用・worker全体の受入完了とは扱わない。

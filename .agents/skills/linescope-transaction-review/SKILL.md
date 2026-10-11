---
name: linescope-transaction-review
description: LineScopeのUpdateRequest、Approval、Execute、expected_version、Snapshot、idempotency/prepare retry、row/advisory lock、Outbox、Projection、Rebuild/Restoreの実装変更を原子性・並行性・復旧の観点でレビューする。
---

# LineScope Transaction Review

仕様を再定義せず、commit/rollbackの意味と順序を実コードで照合する。

[文書入口](../../../docs/deliverables.md)、[transaction-design](../../../docs/implementation-design/transaction-design.md)、[data-model](../../../docs/design/data-model.md)、[operations](../../../docs/implementation-design/operations.md)、[test-plan](../../../docs/implementation-design/test-plan.md)を参照する。対象カテゴリの業務不変条件はrequirements/domain-model、認可はaccess-control、HTTP retryはapi-toolsを正とする。

## 更新経路

接続/transaction所有者、各lockの取得と保持期間、現在値再読込、version/CREATE一意性、Snapshot照合、全Target変更、履歴/Audit、必要Outbox、承認消費、結果保存、commitを順に追う。複数Targetの一部commitや暗黙flushを導入しない。

主Transactionの失敗、別Transactionでの失効/失敗監査、保存不能fallbackを分ける。失効前に再lock・再検証し、他の成功や終端状態を上書きしない。FAILEDを一般的rollbackへ拡大しない。

定義された状態遷移が実装済みかを別に確認する。DB例外の継承とcatch順を追い、deadlock・lock timeout・通信途絶・commit不明を同一と仮定しない。error codeと自動retryの可否をAPI契約に照合する。

retry keyの発行元、scope、正規化入力、永続性、UNIQUE競合、rollbackと終端再送を正本へ照合する。context/Approval/request IDを混同しない。確定afterと後続current値を分け、commit不明時に自動再実行を追加しない。

## Projection / Graph

正本commitとNeo4j commitを分散Transactionと扱わない。Neo4j適用→PG ACKの間の障害を再適用で回復できるか、markerのwrite lock・version/hash・edge置換が原子的かを確認する。

claim/lease/retry/DEADの各試行をfenceし、古い報告で新attemptを上書きしない。Outbox ID/時刻の順をcommit順・最新値と仮定せず、commit済み状態集合とaggregate versionを追う。

Graph分析と更新/Projectionのlock境界、CURRENT/generationの開始・終了確認、Evidenceの観測時刻を確認する。全ストアの同時Snapshotとは説明しない。

Rebuild/Restoreではleader、排他lock、drain、正本Snapshot、generation検証・公開、flag/fatal、途中失敗とcrash再開を別々に追う。作業用generationは公開完了ではない。heartbeat/DTOだけで公開や生存を証明しない。検証済みmarkerとPG pointerを確認する。期限チェックだけでblocking I/Oのhard timeoutを満たしたとしない。

## 検証

該当する並行UPDATE/CREATE/消費、禁止cycle、途中write/監査/Outbox失敗、PG ACK失敗、stale version、応答喪失と再送、lock競合・期限境界・leader喪失を実DBで検証する。故障注入はSQL文字列の綴りに依存せず、処理境界で同期し、rollback後の状態をassertする。

lock順、transaction境界、失敗保存、未知結果、関連AC/Test、残る未実装/未検証を報告する。正しい意味を抽象化やコード削減のために変えない。新規状態/業務ルールが必要なら、通常refactoringとして紛れ込ませない。

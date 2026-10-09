# 業務判断支援の追加・文書整合性レビュー

## 判断と変更理由

2026-10-09、POが提示した15 Use CaseとBS-01〜12 / BS-G01を受け、実装を止めて文書を整備した。POは新Use Case / Scenarioの意図を既存文書との不整合時に優先すると指示した。運用上の意思決定支援の採用自体を判断待ちにはしない。

POの追加指示で不足ケースも補った。LogiScopeのdemo-video-script、demo-data-design、agent-demo-verificationを読んだが、その後の「真似るのはあのノリだけ」という指示に従い、業務上の問いから根拠と判断へつながる雰囲気のみを参考にした。物流の業務仕様、Tool、技術構成、コード、データを継承していない。追加内容はLineScopeの不足レビューに基づく。

## 更新した文書

従来19文書すべてへ必要な追加・責務境界を反映し、implementation-design/business-scenarios.mdを追加した。Use Case文書を別途増やさず既存use-casesに統合し、正本文書は20となった。READMEの資料リンク名とhistory indexも整合させた。旧履歴の当時の19文書という記載は残す。

- requirements: 目的、R-B01〜10、UC-B01〜17、AC-B01〜11、データ20項目のA / B / C分類、PO-B01〜08、権限・数値・時間・関係意味の境界。
- design: 正本／派生モデル、決定論的計算の責務、必要なDB拡張と入力Evidence、Agentの説明と非自律更新。
- implementation-design: 20 Business Scenario、固定数値とUC ↔ BS ↔ AC、試験階層、API拡張の未確定部分、更新・将来評価・RAG・Evals・運用の境界。

既存UC-01〜21、AC、R-01〜40、T-R01〜21を保持した。PO提示の新UCは番号衝突を避けUC-B01〜15とし、対象確認・更新後確認をUC-B16・17で補足した。BS-13〜19は納期、Prepare、安全不明、加算不可、曖昧対象、分析不能、確定後確認を補う。

## 成立状況と残る仕様不足

BS-01、BS-14、BS-17〜19の中心動作とBS-08の経路は既存仕様で表現可能。ただしGraph / Prepare / Approval / Execute等はまだ全実装済みではない。BS-05 / 06の構造代替と保全履歴参照も既存仕様の部分であり、能力・故障原因・経済評価まで成立するとは扱わない。

新しい能力・費用・安全・劣化・計画種別・故障・納期情報は追加設計が必要。データ分類はrequirements §14.2を正とし、maintenance history=A、next planned maintenance=B（候補のみ）、その他18項目=C（一部既存情報があっても要求全体の意味を満たさない）。自由記述を計算用正本として自動転用しない。

PO判断待ちはrequirements §14.3に集約した。比較期間／費用範囲、損失と独立加算、能力／負荷／buffer、安全／劣化、修理交換計画／将来停止、故障履歴、新情報の権限、InfrastructureResourceの被影響意味の8群。未決定事項に依存する実装・受入を勝手に完了させない。

BS-G01の専用数値fixtureとUC-B14の将来停止予約variantは判断確定後に追加する。BS-13の4時間は明記した単純モデルの試験期待値であり、全生産計画の業務ルールではない。BS-03の継続有利の意図と150日の数値を保持し、共通比較条件と費用回収期間の意味を未決定事項に結び付けた。

## セルフレビュー

| 領域 | 確認結果 |
|---|---|
| 目的・優先順位 | 今回の意思決定支援を対象に含め、旧v1にないことだけで対象外にしない |
| UC / AC / Test | 元15UC・13BSを保持し補足。UC ↔ BS ↔ AC表を追加。UC-B11 / 14の直接検証をBS-13 / 14で補う。全体合格と部分実装を区別 |
| 数値 | 200000、1600000、1900000、480000、150、30、4および復旧期限を手計算相当の決定論的検証で確認。lead timeから無条件に停止損失を作らない |
| Domain / Graph | OPはProcessとして固定し、Operation variantはAssignment由来USES。required方向、一段置換、全AND成立、CURRENT、最短hop、過去as_ofの限定を維持 |
| DB / API / Tool | 必要な新入力・計算契約を明示し、未確定列・endpoint・status・型を実装済みとして書かない。数量は既存Snapshot v1へfloatを追加しない |
| 権限 | 新情報の権限はPO-B07。既存全Target条件・単一カテゴリ・Graphロール・Evidence認可を維持 |
| Approval / Execute | 分析のみではPrepareなし。人間Approvalと元requester Executeを維持。予約停止を現時点UPDATEに読み替えない |
| Transaction / Outbox | 状態遷移、lock順、Outbox、Rebuildは維持。判断支援計算をcommitや承認消費と混同しない |
| Evidence / RAG | 計算入力・式・版・時刻・仮定を追跡。文書検索結果だけで安全基準や費用を確定しない |
| 未知と完全性 | Graph complete、経済incomplete、能力不足、安全未確認を区別。UNKNOWNと0・NONE・NULLの意味を混同しない |

致命的な設計思想の矛盾は認めない。具体的な差異は、RUNNINGと劣化／安全／能力、未来評価とas_of、予約停止と現在状態変更、InfrastructureResourceの被影響方向であり、既存の意味を勝手に反転せず追加設計・PO判断へ明示した。

## 検証と作業境界

コード・設定・migration・依存・業務DBは変更していない。Markdownのローカル参照先、文書数、UC / BS / AC / PO IDと対応、fence、数値、git diffの空白エラーを検証する。既存実装テストのローカル再実行は文書のみの変更なので省略し、PR CIで既存Backendとmigrationを検証する。記載したBusiness Scenario自体は未実装・未実行である。

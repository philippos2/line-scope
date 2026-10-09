# UI/UX意見書のレビューとAPI設計への留意点

日付: 2026-10-09

## 位置付けと共有意図

POが共有したChatGPTのUI/UX意見書へのCodexの評価記録。正式なUI仕様・要求・API契約ではない。POは、UI実装は後続でもAPI設計に影響し得るため今共有したと説明した。画面配置を今確定する指示ではない。

本記録のAdoptは「後続設計で採用したい原則」というCodexの判断であり、業務ルール・物理モデル・APIを追加確定する意味ではない。既存正本を変更せず、コード・UI実装も行わない。

確認した主な根拠: [要件 §9・13・14](../requirements/requirements.md)、[UC-B09・13〜15とGolden Use Case](../requirements/use-cases.md)、[AC-B05・06・09〜11](../requirements/acceptance-criteria.md)、[ドメイン §15](../requirements/domain-model.md)、[Agent設計](../design/agent-design.md)、[API / Tool契約](../implementation-design/api-tools.md)、[Business Scenario](../implementation-design/business-scenarios.md)、[Frontendの現状](../../frontend/README.md)。Frontendは方針文書のみで、画面コードはまだない。

## 評価

| 対象 | 判断 | 理由・修正条件 |
|---|---|---|
| 業務判断支援を中心にする | Adopt | 要件 §9とUC-B09／Goldenの目的に合う。日本語の問い合わせ・説明を、構造化した判断材料へつなぐ |
| Situation → Investigation → Decision → Action | Modify | 認知上の順序として有効。固定の画面遷移にはしない。「なぜ起きたか」の原因診断まで保証せず、既知の事実・報告・分析仮定・依存経路を区別する |
| Situation Summaryを先に見せる | Modify | 選択対象・正本状態・観測時刻・分析条件・不完全性を先に示す。Severity・安全保証・経済値は未定義のまま表示しない |
| 対応案の横並び比較 | Adopt | UC-B09、AC-B05に合う。比較期間・単位・費用範囲を揃え、不足時に優劣を確定しない |
| Hard Constraintを先に扱う | Adopt | AC-B06に合う。違反案は実行可能候補から除外し、除外理由とEvidenceは確認可能にする。安全情報不足を安全とも違反確定とも扱わない |
| Unknown / MissingとEvidence | Adopt | AC-B09／11に合う。未知・未探索・取得不能を0や不存在と区別し、結論から入力・式・正本・文書・前提へ遡れるようにする |
| Graphの主役固定を避ける | Modify | 以前のGraph中心案は候補であり固定仕様ではない。状況要約・比較を主な作業面にし、Graphを影響説明と経路確認に強く使う方向を推奨。詳細配置は後続で検証する |
| Chatと次の問い合わせ候補 | Adopt | 問い合わせ・説明・探索の入口として有効。選択肢をクリックしただけでPrepareせず、明示更新意思を確認する。Approval／ExecuteはAgentへ委任しない |
| AnalysisとActionの分離 | Adopt | サーバ保存のcanonical before／proposed、承認状態、確定after、後続currentを区別する。元requesterのExecuteと人間のApprovalの境界を保つ |
| HomeのOperational Overview | Defer / Needs product decision | 正本の設備状態の一覧と、Incident・通知・Severity・工場全体の損失集計は別。後者は登録・検知・権限・集計規則等の業務定義が必要 |
| 配色・アイコン・Component配置 | Defer | 落ち着いた意味色、読みやすさ、色以外の状態表現は妥当。具体テーマ・部品・ライブラリはUI段階で検証する |
| 例示の未定義状態・数値をそのまま採用 | Reject | DEGRADED／MAINTENANCE等を現行状態enumへ追加しない。例示の安全閾値・Severity・架空profileを正式な事実や業務ルールにしない |

## 例示を使う際の注意

- Equipmentの正本状態はRUNNING / STOPPED / UNDER_MAINTENANCE / UNKNOWN。ProcessやProductのAT RISK等は分析上の評価表示であり、正本状態として追加しない。分析評価を定義する際は、根拠・条件・完全性を契約に含める。
- CAN_SUBSTITUTEの保存方向は代替候補source → 被代替target。通常の影響経路へ混ぜず、代替の関係と到達経路を区別して描く。構造的代替、現在のavailability、能力充足、安全上の許容を混同しない。
- 60 / 90 = 66.7%の表示には同じ製品・単位・評価期間という前提が必要。これだけで経済損失が33.3%になるとは言えない。一般規則はPO-B02／03で確定する。
- 200,000円/hour、4時間buffer、軽微劣化、14日lead time等は独立したシナリオ例に由来する。自動的に一つのGolden fixtureへ混ぜず、損失の適用条件・稼働時間・比較期間を揃える。
- BS-03の150日は固定fixtureの単純費用回収期間。全対応案の一般的な損益分岐と同一視しない。
- GraphのCURRENTはProjection同期状態であり、工場全体の情報が完全・安全・最新である保証ではない。非CURRENTでは最新Graph結論を返さず、探索打切り時の件数を完全な総数としない。
- 固定fixtureの画面にはデモの前提を明示する。Mockの成立を本番ロジックや正式な安全基準へ昇格させない。

## API設計に今から使う観点

長文回答だけを返す契約ではなく、正式要件の構造化した結果をUIと日本語説明が共通で参照できるようにする。次の事項は既存要件に基づく契約具体化の観点であり、本記録で新endpointやfield名を確定するものではない。

- 対象、直接／間接影響、順序付き経路、Evidenceと表示件数を同じ分析範囲に結び付ける。UIが独自にGraphを辿り直して結論を生成しない。
- Graph・能力・経済・リスクごとの完全性と不足情報を保持する。部分成功、依存ストア障害、未知を区別し、全体の緑色表示で隠さない。
- 計算値には単位・通貨・評価期間・入力・式・仮定・推定／確定の根拠を対応させる。数値計算は決定論的なサーバ処理が行い、LLMやUIへ業務計算を委任しない。
- 対応案には共通比較条件、実行可能性・判断不能・除外理由、費用・時間・残存リスク・不足情報を対応させる。具体schemaはPO-B01〜07の意味確定後に設計する。
- 正本値と報告・仮定、分析観測時刻と評価時点を分ける。複数Read結果を、全ストアの同時Snapshotや完全な過去復元として扱わない。
- Prepare／Approval／ExecuteのID・状態・immutable Snapshot・確定結果・current valueは現行契約を保つ。context_idを分析・承認・冪等性キーの代用にしない。
- Drawerやタブ等の画面部品に合わせてendpointを増やさず、業務上の結果と認可境界を単位にする。Overviewに必要な集計は既存の検索paginationから全体件数を推測せず、必要な要件・契約を明示する。
- Graph・費用・Evidence・Tool Traceはサーバ側で認可する。Tool TraceへLLM内部推論、credential、内部SQL／Cypherを含めない。

## PO判断と次の扱い

既存PO-B01〜08は未決のまま保持する。Incidentの正本化、現場報告を工場長へ知らせる入口、Severityの定義、自動通知・検知、工場全体の経済集計を採用する場合は、新しいProduct / Domain Requirementが必要である。工場長の問い合わせに答えることと、自動的に異常の発生を知らせることを区別する。

今はAPIの出力責務を考えるレビュー材料として保持する。UI実装はサーバサイド完成後。正式な契約追加は、対応する業務意味と認可を確定し、Requirements → Domain / Data / API → AC / Testへ明示反映する。ASCII画面、名称、面積比、固定数値を採用決定とは扱わない。

---
name: backend-secure-coding
description: LineScopeバックエンドのauthorization、role、Trusted Execution Context、Tool argument、SQL/Cypher、LLM/RAG入力、secret、DB role、外部error responseに関係する実装・変更・security reviewを検証する。
---

# LineScope Backend Secure Coding

入力からauthority/SQL/出力へ至るdata flowを確認し、文字列操作の存在だけで脆弱性と断定しない。

[文書入口](../../../docs/deliverables.md)、[access-control](../../../docs/requirements/access-control.md)、[architecture §15](../../../docs/design/architecture.md)、[api-tools](../../../docs/implementation-design/api-tools.md)を参照する。RAG変更はrag-design、ログはoperations §13、試験はtest-plan §15を読む。

## 入力と権限

認証済みContextの注入元と利用側を追う。Body、エンドユーザーによる自己申告、LLM Tool引数、RAG本文、外部metadataをidentity/role/permissionの根拠にしない。型検証と認可は別に確認する。

Tool側と確定操作の境界で現在の認可・owner・全Target条件を正本と照合する。AgentにApproval/Executeや任意SQL/Cypherを公開しない。認証設定参照不能と権限喪失を区別してfail closedにする。

## DBアクセス

通常アクセスはSQLAlchemy Coreを第一選択とする。既存の安全なRaw SQLを非ORMという理由で機械変換しない。Raw SQL例外は選択理由、bind、transaction境界を追跡できることを確認する。

外部値・保存済み自由文字列をSQL構文へ補間せずbindする。table/column/label/sort/direction等は値bindで守れないため、固定allow-listから構造を選ぶ。DB driver用にCoreをcompileしている経路では、SQL本文とparamsの分離に加えJSONB等の型adaptationも確認する。Core/ORMの採用だけを安全性の証拠にしない。

検索・認可済み変更・migration・Projection/Rebuildのconnection authorityを確認する。readonly transactionだけでleast privilegeとしない。標準Composeと直接Python利用のfallbackを区別し、read接続障害から強いroleへfallbackさせない。DB constraintもApplication validationとは別に確認する。

## 外部データと出力

RAG変更ではQdrantを最終認可根拠にせず、正本metadata・active version・本文hash・生成前再確認を追う。取得文書の命令をSystem指示として採用しない。

ログ/responseにcredential、SQL本文、bind値、raw exception、Snapshot/prompt全文を不用意に出さない。サーバEvidenceとLLMの説明を分離する。依存loggerも含めて公開面を確認する。

## LLM回答の根拠と範囲

[Agent設計の根拠付き回答方針](../../../docs/design/agent-design.md#根拠付き回答の設計方針後続設計未実装)を設計・レビューに適用する。**事実はコードが責任を持ち、LLMには解釈と整理だけをさせる。** 取得・計算・根拠との対応の検証・確認不能な内容の公開抑止をコードの責任として確認する。LLMによる質問の構造化もコードで検証する。方針の記載を実装・検証済みの証拠にしない。

- 質問の対象と情報種別を有限の構造へ落とし、コードが対応スキーマ・Toolと照合する範囲ゲートを確認する。非対応、未検索、取得失敗・不完全、検索完了後の未登録を混同しない。LLMの分類を認可へ昇格させない。
- 主張と実取得結果の参照を構造化し、根拠の実在だけでなく対象・属性・関係・値・時点の意味が対応するかを検証する。IDや文字列の一致だけを正しさの保証にしない。検証できない内容を登録済みの事実として公開しない。
- 属性値・計算結果をLLMに創作させず、登録データと決定論的処理から表示する。特定質問・設備に専用経路を作る、近接する情報から別の事実を断定する、注意書きやプロンプトの追加だけで解決済みとする設計を避ける。
- 回帰は質問例への一致ではなく、未対応の情報、根拠からの飛躍、対象不存在・曖昧さ、取得不完全などの失敗分類で確認する。未実装・検証不能・残る限界を明記する。

## 検証と報告

許可された自由文字列へのInjection、identifier拒否、権限拒否、secretを含む障害、実DB role/constraintの試験から変更に必要なものを選ぶ。ID型拒否だけで自由文字列のbindを検証したことにしない。

findingごとにseverity、入力源、構築/越境箇所、実際の到達可能性、推奨修正、回帰試験を示す。確認不能は未検証、真の未定義業務権限はPO判断として分ける。transaction/lockを変更する改善は、原子性を維持するレビューも行う。

---
name: linescope-secure-coding
description: LineScopeのauthorization、role、Trusted Execution Context、Tool argument、SQL/Cypher、LLM/RAG入力、secret、DB role、外部error responseに関係する実装・変更・security reviewを検証する。
metadata:
  status: draft
---

# LineScope Secure Coding

Phase 1A草案。正式採用前。入力からauthority/SQL/出力へ至るdata flowを確認し、文字列操作の存在だけで脆弱性と断定しない。

[文書入口](../../../../deliverables.md)、[access-control](../../../../requirements/access-control.md)、[architecture §15](../../../../design/architecture.md)、[api-tools](../../../../implementation-design/api-tools.md)を参照する。RAG変更はrag-design、ログはoperations §13、試験はtest-plan §15を読む。

## 入力と権限

認証済みContextの注入元と利用側を追う。Body、利用者自己申告、LLM Tool引数、RAG本文、外部metadataをidentity/role/permissionの根拠にしない。型検証と認可は別に確認する。

Tool側と確定操作の境界で現在の認可・owner・全Target条件を正本と照合する。AgentにApproval/Executeや任意SQL/Cypherを公開しない。認証設定参照不能と権限喪失を区別してfail closedにする。

## DBアクセス

通常アクセスはSQLAlchemy Coreを第一選択とする。既存の安全なRaw SQLを非ORMという理由で機械変換しない。Raw SQL例外は選択理由、bind、transaction境界を追跡できることを確認する。

外部値・保存済み自由文字列をSQL構文へ補間せずbindする。table/column/label/sort/direction等は値bindで守れないため、固定allow-listから構造を選ぶ。DB driver用にCoreをcompileしている経路では、SQL本文とparamsの分離に加えJSONB等の型adaptationも確認する。Core/ORMの採用だけを安全性の証拠にしない。

検索・認可済み変更・migration・Projection/Rebuildのconnection authorityを確認する。readonly transactionだけでleast privilegeとしない。標準Composeと直接Python利用のfallbackを区別し、read接続障害から強いroleへfallbackさせない。DB constraintもApplication validationとは別に確認する。

## 外部データと出力

RAG変更ではQdrantを最終認可根拠にせず、正本metadata・active version・本文hash・生成前再確認を追う。取得文書の命令をSystem指示として採用しない。

ログ/responseにcredential、SQL本文、bind値、raw exception、Snapshot/prompt全文を不用意に出さない。サーバEvidenceとLLMの説明を分離する。依存loggerも含めて公開面を確認する。

## 検証と報告

許可された自由文字列へのInjection、identifier拒否、権限拒否、secretを含む障害、実DB role/constraintの試験から変更に必要なものを選ぶ。ID型拒否だけで自由文字列のbindを検証したことにしない。

findingごとにseverity、入力源、構築/越境箇所、実際の到達可能性、推奨修正、回帰試験を示す。確認不能は未検証、真の未定義業務権限はPO判断として分ける。transaction/lockを変更する改善は、原子性を維持するレビューも行う。

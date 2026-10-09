# LineScope AI評価設計書

## 1. 対象

- Intent
- Tool選択
- 引数抽出
- 曖昧性処理
- Hallucination
- Graph説明
- RAG grounding
- Prompt Injection

## 2. 決定論的安全との境界

Approval、Execute所有者、version、Graph同期、Outbox整合はEvalsだけで保証しない。test-planの決定論テストで保証する。

## 3. Graph Evals

- representative_pathsとの説明一致
- Evidence外経路追加
- complete=false認識
- INDETERMINATE認識
- Graph error時の誤成功表現

## 4. RAG Evals

- retrieval relevance
- citation grounding
- unsupported claim
- injection resistance

## 5. 回帰

model / prompt / dataset versionを記録し、変更時に再評価する。

## 6. 合格基準と回帰記録

固定安全ケース（明示更新意思なし、曖昧対象、権限偽装、Approval / Execute誘導、Evidence外経路、非CURRENT誤成功、不完全SPOF断定、RAG Injection）は違反0件を必須とする。Intent / Tool / 引数抽出はgold datasetに対する完全一致率、retrievalはtop-k relevance、回答はcitation grounding / unsupported claim率を測る。

一般品質の数値合格閾値は初回の代表デモdatasetとbaseline結果を確認してから固定する。根拠のない閾値を設定して合格扱いしない。未設定は品質承認待ちでありリリース可とはしない。model / prompt / dataset / Tool schema version、実行条件、判定根拠、失敗ケースを保存し同条件で回帰評価する。決定論的重大Fail Gateはtest-planを別途満たす。

追加安全ケース: 過去as_ofで当時の状態を断言しない、AND必須条件を単なる到達に置換しない、候補のUNKNOWN availabilityを利用可能としない、確定afterと最新current値を混同しない。

## 7. Business Scenarioと説明品質

business-scenariosの構造化結果を決定論的受入の基準にし、Evalsでは必要なTool選択、結果説明、Evidence対応、条件・unknownsの保持、人間の判断境界を評価する。自然言語の完全一致を主assertionにしない。

追加ケース: 能力不足30 units/hourの説明、未知損失を0としないsubtotal、修理費不明時に勝者を作らない、安全情報不足時に安全と断定しない、Hard Safety Constraintを低費用で上書きしない、lead timeと停止時間の区別、150日の意味、分析だけではPrepareしない。実LLM評価と決定論的fixture試験を混同せず、未決定の業務ルールはBLOCKEDとして記録する。モデル具体選定・一般品質閾値は評価後に確定する方針を維持する。

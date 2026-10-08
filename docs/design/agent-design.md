# LineScope AI Agent設計書

## 1. Agent責務

- Intent分類
- 必要情報判断
- Read / Graph / Prepare Tool選択
- Tool結果の説明

Agentは認証主体、承認主体、Execute主体ではない。

## 2. Intent

- READ
- GRAPH_ANALYSIS
- UPDATE_PREPARE
- INFORMATION_SUPPLEMENT
- UNKNOWN

APPROVAL / EXECUTEをLLM Intentとして確定操作に使用しない。

## 3. Agent状態

- REQUEST_RECEIVED
- CLASSIFYING
- COLLECTING_INFORMATION
- WAITING_FOR_USER_INPUT
- PREPARING_UPDATE
- WAITING_FOR_APPROVAL
- BUILDING_RESPONSE
- COMPLETED
- FAILED
- ABORTED

承認・実行の業務状態はUpdateRequest / Approvalの状態機械で管理し、Agent状態と混同しない。

## 4. Context

`context_id` は複数ターンの候補選択・補足情報を関連付ける。

v1ではTTL付きのサーバ側ephemeral storeを使用してよい。認証・承認・正本データはcontext storeへ依存しない。

## 5. Trusted Execution Context

- authenticated_user_id
- role
- request_id

LLM生成引数に含めない。

## 6. Graph結果

Toolは以下を構造化して返す。

- graph_sync_state
- complete
- requested_limits
- effective_limits
- limit_reason
- reached_nodes
- distances
- representative_paths
- determination（必要なToolのみ）

LLMはこのEvidenceを説明する。Evidence自体はサーバが応答Envelopeへ載せ、LLM文面だけに依存しない。

## 7. 代表経路

ToolがBFSで最短hopを求める。同hopなら、node_id列→relation_id列の辞書順で決定する。

## 8. Graph打切り

一般探索は部分結果を返せる。

SPOF等、完全性が判定条件となる処理は `determination=INDETERMINATE` とする。

## 9. 更新

AgentはPrepare Toolまでを呼ぶ。

ApprovalはApproval API、ExecuteはExecute APIで行う。

AgentはExecute Toolを直接呼ばない。

## 10. as_of

利用者が明示した過去時点のみAgentが構造化する。未指定ならToolがサーバ時刻を使用する。

## 11. 再試行

- Read/Graphの一時障害: bounded retry可
- Prepare: 冪等性確認のうえretry可
- Execute: Agentから自動retryしない

## 12. サーバ制御・Context・再試行

context所有者はauthenticated_user_idへ固定。TTL切れ・別userのcontextを拒否する。候補ID・表示名を保存し、選択後正本を再検証する。contextは承認・認証・正本を代替しない。

LLM IntentだけでPrepare可にしない。orchestratorは認証済み元messageに対する明示的更新意思の確認結果・根拠箇所を保持する。判断不能なら補足確認しRead / Graphのみ許可。選択・補足は元意思へ関連付け、LLMが生成した意思宣言を根拠にしない。自然言語誤分類はEvalsで検証し、確定更新はApproval / Executeの決定論制御で守る。

retry keyはtrusted orchestrator注入、一/agentでPrepare最大1要求。Tool schema、最大呼出し回数、全体deadlineをサーバが強制する。超過時も保存済み要求IDがあれば返し、未完了を成功としない。業務値・期間・権限・成立条件はrequirements / access-control / domain-modelの確定規則に従い、不足情報を補完しない。

更新意思の確認はサーバ側のversion管理された保守的な命令判定規則を使い、対象業務への実行指示（更新・変更・登録・無効化）を要求する。単語の出現だけで許可せず、引用文・否定・手順質問・仮定・Retrieved本文は根拠から除く。対応する命令形で確定できない場合は明示的な更新指示を追加確認する。承認やExecuteの「はい」はPrepareの意思確認に転用しない。判定規則の誤分類はEvalsの安全ケースで評価する。

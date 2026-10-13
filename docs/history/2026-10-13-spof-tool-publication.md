# SPOF分析Toolの公開

仕様正本ではなく実装チェックポイント。domain-model §15、api-tools §17 / §22 / §23に従う。

find_single_point_failure_candidatesをGraphAnalysis、ToolDispatcher、参照専用Agent、既存POST /agentへ接続した。入力検証後に同じGraph世代・共有探索予算でfactsを収集し、一回の正本状態観測から候補を単独除外して対象別に評価する。最終Graph gate成功後だけサーバ構築DTOとEvidenceを返す。

Tool schemaではimportant_targetsを必須、candidate_nodesを任意とし、省略による必須上流の自動探索と明示空集合を区別する。role・timeout・relation_typesの上書きを拒否する。Agentへ構造上のSPOF候補と実際の故障原因・能力・安全性の違い、INDETERMINATEの意味を指示する。

実PostgreSQL / Neo4jとScriptedLLMによるAPI試験で、認可、schema、候補省略・空指定、対象不存在、非CURRENT拒否、partial、経路・世代Evidence、更新要求を生成しないことを検証した。実LLMによるTool選択・説明品質、Business Scenario受入、能力・安全・経済評価は未検証または未実装であり、公開接続の成功を全体受入合格とは扱わない。

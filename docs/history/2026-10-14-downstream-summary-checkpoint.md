# 下流調査の日本語要約

PR #229 / feat/grounded-downstream-summary / b6b7b52。

#228の実Read baselineで下流回答616字・UUID列挙を確認した。Agent層のgraph_answer.pyで、単一trace_downstream_impactの取得済みdataから短い文章を生成する。LLMは調査とTool選択を担当し、追加DB queryは行わない。Tool data / Evidence / 経路 / Graph gate / API契約は保持する。

実Qwen3による同じ3質問を評価し、構造化結果は全3件成功。下流回答は128字、6到達候補（直接2、間接4）、種別別件数、探索範囲確認、停止影響・能力・安全・経済の未評価を説明した。UUIDを表示しない。report: /tmp/linescope-grounded-downstream.json。当時のrevision=29ad44a、working_tree_dirty=trueを記録する。通常Readの状態・原因不明と存在しない設備は既存LLM説明経路。

適用範囲: 単一の下流到達分析のみ。上流、共通依存、代替、SPOF、複数Graph分析を下流表現へ誤変換しない。探索不完全で0件でも影響なしとしない。参照失敗も表示する。過去指定の完全復元ではない旨のprefixを維持する。未知の業務名称を推測しない。その他の取得情報はdata / Evidenceに保持する。

追加7ケース。関連42 passed / 3.25秒。実PG/Neo4jのAPIで過去指定・完全性・上限・認可・Evidenceを確認。lint / format332ファイル成功。既存Starlette warningと終了時logging diagnosticは未解消。実評価専用環境とテスト環境を片付けた。

文書反映の候補: agent-design / prompt-designの説明方式へ、特定の下流分析をサーバ側で要約する実装を記述する。その他のLLM説明・品質評価を合格扱いしない。README / ガイド / roadmapにも実際の受入範囲を反映する。機能PRへ文書を混在させず、次の再現・文書整理工程で取り込む。

次の工程: 起動・操作ガイドのクリーン再現、受入結果と未受入範囲の整理、デモバックエンドの一段落判定。正式業務入力と全BS受入は別の残件として明示する。

履歴は文書PRまでstashして保持する。

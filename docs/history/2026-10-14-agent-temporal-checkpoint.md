# Agent過去時点分析の再開記録

作業記録であり仕様正本ではない。入口はdeliverables、残工程はroadmap。

- #219 merge確認後、main f696daeからfeat/agent-historical-analysisを作成。commit c95b15a、PR #220。
- API指定as_ofをGraph全5 Toolと設備割当Toolへサーバで伝播。同値timezoneを正規化し、競合・不正なLLM時刻を拒否。通常Readの現在状態と、現在登録情報の期間評価をEvidenceで区別。
- ReadAgentの過去指定拒否を解消。完全な過去状態復元ではない説明をサーバで付加。確認継続Contextに指定時刻を保持し、明示変更を優先。現在時点に戻る場合は新規Contextから要求する。
- 関連92成功・1skip、2.61秒。追加11ケース、旧as_of未接続拒否1ケースを新契約の正常／拒否試験へ置換。lint・format317ファイル成功。実PG/Neo4j API試験、LLMはScriptedLLM。
- 実LLM品質、Decision Package／RAG／更新への過去指定、point-in-time復元は今回の実現範囲ではない。既存警告・終了時logging output failedは未調査。
- PRは入口→Tool→根拠・回答→確認継続までまとめ、内部部品単位には分割しない。文書整理は別。
- CI確認後、#220のmergeを確認して次の業務機能へ進む。PO-B01〜08を推測で確定しない。roadmap更新・見出し修正と複数の履歴stashは別の文書整理で反映する。

CI全成功：3713成功・1skip、収集3714件・hash一致、選択1772＋1942＝3714。試験時間253.17秒／255.85秒。runtime・migration・PR title・集約checkも成功。ローカル使い捨て試験環境は片付け済み。

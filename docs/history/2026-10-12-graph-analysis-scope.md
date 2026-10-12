# 通常Graph到達探索の評価範囲

仕様正本ではなく、実装・検証の判断記録。

#168の実LLM回答でcomplete=trueに続き「不明事項なし」と広く総括された。通常Graph Toolは依存関係の到達探索であり、下流の実際の運転停止・能力・安全性・経済影響を評価していない。既存の意味論をdataとEvidenceの両方に明示するため、analysis_scope=DEPENDENCY_REACHABILITYとnot_evaluated=[OPERATIONAL_IMPACT, CAPACITY, SAFETY, ECONOMICS]を追加した。

completeは引き続き探索完全性であり、not_evaluatedをFalse / 0 / 安全 / 業務判断完了へ変換しない。現在状態は別の観測事実として保持する。このToolの評価範囲であり、LineScope全体の業務判断支援をスコープ外へ変更しない。

Agentへ同じ区別を指示し、LLM向け参照表にもメタデータを保持する。通常Graphの実DB / API試験と読取probeで、完全探索・部分探索の契約を確認する。認可・Graph gate・ロック・探索上限・LLM予算・モデル選定は変更しない。

実LLMの初回試行はAGENT_LIMIT_REACHEDだった。説明品質の実測はPRへ記載し、Promptによる指示を安全性の保証や一般品質合格と扱わない。私有.envは変更せず、LogiScopeコードは再利用していない。

読み込み済み状態の実LLM試行はstatus=okで完了した。応答には「探索の完全性：完全」と「未評価項目：運用影響・能力・安全性・経済影響」の両方が提示された。更新したprobeで6対象・2製品・6経路・CURRENT・評価範囲・Evidenceの整合を確認した。UUID列挙は残っており、一般説明品質の合格とは扱わない。

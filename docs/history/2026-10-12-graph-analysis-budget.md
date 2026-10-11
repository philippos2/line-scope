# Graph分析専用の時間budget

api-tools §10・§17のserver timeoutとtransaction-designの分析境界を正本とする。

- Rebuildのleader・drainから独立したGraphAnalysisBudgetを追加する。サーバが渡す正整数timeout_msとmonotonic clockから一度だけ期限を決め、remaining / requireで確認する。確認や再呼出しで期限を延長しない。
- 期限ちょうど以後、または非有限clockではGraphAnalysisTimeoutで停止する。既存PG / Neo4j timeout helperへ残時間を渡せる契約とし、Neo4jの0 timeoutによる無制限化を避ける。
- これは内部budget部品であり、公開Toolへの設定注入、BFS / 経路復元の途中停止、TIMEOUT partial結果の生成は後続。期限切れだけを理由にCURRENT / generationの終了確認を省略した結果を公開しない。
- DB・API契約・既存のlock / Transactionを変更せず、SQL / Cypherを追加しない。LogiScopeコードは再利用していない。

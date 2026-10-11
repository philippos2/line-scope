# Graph分析のPostgreSQL整合gate

仕様正本はtransaction-design §16・§20、api-tools §11。本記録は実装判断の履歴。

- GraphAnalysisGateは読み取り接続を選び、READ ONLY / READ COMMITTED transactionでshared mutation advisory lockを取得する。leader lockは取得しない。
- lock取得後にCURRENTとactive_generationを確認する。呼出元は単一generationのNeo4j readとサーバEvidence構築をcontext内で完了し、正常exit後だけ結果を公開する。終了時にもCURRENTと同じgenerationを要求する。
- LAGGING / ERROR / REBUILDINGは既定Graph errorへ変換する。終了確認失敗・generation変更・期限切れ・DB障害時は正常結果を返さずtransaction lockを解放する。
- server-owned budgetをlock待ち・状態確認へ伝播し、既存の固定Core timeout処理を使う。新しいRaw SQL、DB schema、API、Toolは追加しない。接続確立・ネットワーク等の厳密なwall-clock制御は未完。
- これはPostgreSQL側だけの内部gateであり、CURRENTだけでNeo4j markerの検証済み状態を証明しない。Neo4j read transaction、generation marker確認、認可、探索、Evidence契約、公開Graph Toolへの接続は後続。LLM説明はlock解放後に行う。
- 実PGでshared/shared並行、shared/exclusive競合、開始・終了時の各同期状態拒否、generation変更、予算不足、READ ONLY強制、例外時解放を確認する。全ストア同時SnapshotやGraph受入全体の完成とは扱わない。LogiScopeコードは再利用していない。

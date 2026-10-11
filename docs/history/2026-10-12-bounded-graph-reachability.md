# 上限付きGraph到達探索の内部計算

正本はapi-tools §10・§17、domain-modelの探索方向、AC-G01・02・07・08。本記録は実装判断の履歴であり、公開Toolの完成を示さない。

- `domain/graph_reachability.py`にDB・HTTP・driverへ依存しないBFSを追加する。入力は呼出元が完全取得・期間評価・方向変換済みの論理edge集合とする。部分取得のGraphAdjacencyを完全な入力として渡してはならない。
- typed IDを区別し、起点はdistance=0。最短hopと一つの代表経路の前駆node・source_record_idを保持する。同層nodeと隣接edgeは辞書順に処理し、入力順によらない結果を返す。
- 深度・起点を含むdistinct node数の正整数上限を適用する。上限値に到達しただけでは未完とせず、新たな到達nodeを訪問できない場合に限りDEPTH / NODE_COUNTを返す。両方ならNODE_COUNTを優先する。
- 再訪を除いて許容循環を有限処理する。到達関係から操業停止・成立条件・代替能力・SPOFを推論しない。required=falseも含む通常到達探索とCAN_SUBSTITUTE除外は、論理edgeを準備する呼出元の責務。
- 接続・CURRENT / generation・認可・as_of・system limit・Neo4jの部分取得・PATH_COUNT / TIMEOUT・Evidence公開・直接／間接分類のTool応答への接続は後続。内部結果のcompleteはdepth / node境界のみであり、公開Graph分析のcompleteとしてそのまま使用しない。
- 本体とUnit Testはdomainの対応ディレクトリへ置く。正本文書・DB schema・API契約を変更せず、SQL / Cypherを追加しない。LogiScopeコードは再利用していない。

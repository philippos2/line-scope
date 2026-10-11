# Graph代表経路の内部復元と返却数上限

正本はapi-tools §10・§17、AC-G02・04・08・10。本記録は内部処理の実装判断であり、公開Toolの完成を示さない。

- `domain/graph_paths.py`でBFSの前駆node・source_record_idから、一つの最短代表経路を反復処理で復元する。typed node列、順序付きrecord ID列、hopsを保持し、DB・HTTP・driverへ依存しない。
- 起点単独の0-hop経路は返却せず、経路数上限を消費しない。depth / typed ID順で返し、追加の未返却経路が存在する場合だけPATH_COUNTとする。既存NODE_COUNT / DEPTHを優先し、探索済み対象を経路上限で消去しない。
- 前駆集合に一つの起点と一意なnodeを要求する。距離の型・親の存在・1-hop差・record IDの存在を検証し、不正な前駆を架空の経路へ変換しない。循環する前駆を距離条件で拒否する。
- 公開Evidenceではrecord IDを確認済みedge事実へ解決し、relation_type・保存source/target・論理方向を含める必要がある。この内部DTOだけで公開Evidenceを完成扱いしない。
- TIMEOUT、認可、CURRENT / generation、as_of、system limit、Neo4jの部分取得、Graph Tool / Agentへの接続は後続。内部completeはBFSと経路選択の範囲に限り、公開Graph分析全体の完全性を保証しない。
- API / DB / 正本文書・既存Transactionを変更しない。SQL / Cypherを追加せず、LogiScopeコードも再利用していない。

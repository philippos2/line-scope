# ページ取得から複数段Graph到達探索への接続

正本はapi-tools §10・§17、domain-modelの探索方向、transaction-design §16。今回の区切りは内部Graph読取であり、公開Tool / Agent接続の完了ではない。

- 固定Cypherへbindされたtyped neighbor ID・source_record_idの内部keyset continuationを追加。同じread context、generation、as_of、方向で使い、公開cursorや権限根拠として扱わない。parallel関係もrecord IDまで比較して取りこぼさない。
- DomainのBFSを順序付き・完全なlazy neighbor providerへ接続する。既存のメモリ上の探索は同じBFSを呼び、既存契約を維持する。部分ページを空集合・完全集合として扱わず、必要に応じて次ページを読む。未訪問対象でdepth / node上限が確定した場合は追加取得を止める。
- Graph read contextでrootの存在・activeを検証し、単一Neo4j TransactionとPG shared lock / CURRENT / generationの終了確認を保持して複数段探索・経路選択を行う。返却経路のrecord IDに対応する保存方向・relation type等の事実だけを返す。
- Deadline / driver / 整合性異常は伝播し、正常な空結果へ変換しない。TIMEOUT partialの公開境界、server as_of / system limits、認可、Graph Tool / Agent接続は後続。内部結果を業務停止・SPOF・代替可否の判定へ昇格させない。
- SQL・DB schema・API契約・既存更新Transactionを変更しない。Cypherは固定構文とbindのみ。LogiScopeコードは再利用していない。退避した開発原則のdocs変更とは別の機能固有記録。

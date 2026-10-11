# 検証済みgenerationのGraph分析read adapter

仕様正本はtransaction-design §16・§20、api-tools §11、data-modelのGraph projection。本記録は実装判断の履歴。

- GraphAnalysisReaderはPGのshared analysis gate内で、READ access modeの単一Neo4j explicit transactionを開く。同じtransactionでgeneration markerを検証し、固定queryでtyped nodeを読む。公開API/Tool、任意Cypher、更新機能は追加しない。
- generation marker検証をNeo4jGenerationの既存処理からcaller-owned transaction用の関数へ抽出する。marker欠損・未検証・不正hash/時刻を拒否し、既存Rebuild検証の契約・commit所有権は維持する。
- node queryはgeneration/type/UUIDをbindし、typeを固定allow-listから選ぶ。登録version・activeを検証する。activeは登録有効性であり、操業可否を推論しない。該当なしはNone、未知の影響なしという結論ではない。
- read transactionのtimeoutは既存上限と残り予算の小さい方。自動retryを使わず、結果とサーバEvidence構築をcontext内で行い、Neo4j read完了後もPG終了確認までshared lockを保持する。正常exit後だけ結果を公開し、終了したread contextの再利用を拒否する。
- Graph/driver例外は固定GRAPH_UNAVAILABLEへ変換し、raw exceptionを外部messageへ出さない。PG gateの同期状態errorを維持する。READ access modeだけでDB roleのleast privilege完了と扱わない。
- 実PG/Neo4jで検証済みmarker・node、欠損/不正marker拒否、DB UNIQUE制約、node不正値拒否、inactive保持、型/ID拒否、shared lockと終了時Rebuild検知を確認する。探索・認可・as_of・Evidence外部契約・公開Graph Tool・read専用Neo4j roleの運用接続は後続。全ストア同時SnapshotやGraph分析全体の完成とは扱わない。
- 正本文書・API・DB schemaは変更せず、新しいRaw SQLは追加しない。LogiScopeコードは再利用していない。

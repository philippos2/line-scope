# 認可済みGraph探索とEvidence生成の接続

正本はaccess-control §9、api-tools §9・§10・§17、transaction-design §16。

- ApplicationのGraphAnalysisが入力・認可・server time / limitsを固定し、注入されたGraph readerと状態readerへ接続する。ApplicationへSQL・Cypher・driver操作を持ち込まず、まだHTTP / Agent Toolへ登録しない。
- 通常relation filterを固定bindされたGraph queryの方向集合へ適用する。探索・経路選択・Evidence構築を同じread contextで行い、終了時CURRENT / generation確認が成功した後だけ結果を返す。
- 状態readerは検索用接続のREAD ONLY Transactionで、Core生成SELECTを一回実行する。複数設備の状態・versionとstatement timestampを同じSnapshotで取得する。空集合でも観測時刻を保持する。Graphと状態正本の全体同時Snapshotではない。
- 起点のdistance=0を保持し、直接／間接対象から起点を除く。代表経路に保存source / target・relation type・record ID / version・論理方向を保持し、未返却edgeをEvidenceへ追加しない。state欠損はmissing_statesとして示し、0や推測値で埋めない。
- 過去as_ofのGraphは現在登録関係の期間評価。現在状態の観測はCURRENT_STATE_AT_OBSERVATIONと区別し、過去利用可能性へ適用しない。
- TIMEOUT partialの安全な公開境界、runtime設定・driver組立、Graph Tool登録とAgent接続は後続。業務停止・SPOF・代替可否の判定は含めない。既存DB / API契約・更新Transactionを変えず、SQLはCore生成とbind、Cypherは固定構文とbindのみ。LogiScopeコードは再利用していない。
- 開発原則のdocs変更はstashのまま保留し、本機能へ混在させない。

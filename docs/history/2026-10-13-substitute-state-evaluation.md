# 代替Graph factsとPostgreSQL正本状態の接続

仕様正本ではなく、実装チェックポイントの記録。

正本domain-model §15.1 / §15.3 / §15.4、既存Graph分析gate・deadlineに従い、内部Application処理へGraph factsと状態adapterを注入し、一段代替評価へ接続した。HTTP / DB driver / SQLをApplicationへ持ち込まない。認可と検証済みGraph read contextの所有者は後続の公開Application入口。最終gate成功前に結果を公開しない。

PostgreSQLの設備現在状態と生産作業のplanned_statusを、SQLAlchemy Coreによる一つのSELECT内でstatement_timestampとともに観測する。設備・生産作業のactiveを確認し、型付きIDと正のversionを保持する。query接続・readonly transaction・timeout・DB障害のerror変換は既存GraphStateReaderへ局所化し、従来の設備だけのread契約を維持する。DDL / grant / DB schema / 更新transactionは変更しない。

設備RUNNING / STOPPED / UNDER_MAINTENANCE / UNKNOWNと、生産作業PLANNED / CANCELLEDを既存規則で三値へ変換する。状態欠落はmissing_statesへ明示しUNKNOWNを維持する。Process / InfrastructureResourceの運転状態は補完しない。historicalを明示し、現在の観測factsは保持しても過去利用可能性へ流用しない。

不正な状態コード、version、観測時刻、重複ID、未要求IDはINTERNAL_ERRORで失敗し、破損factsを利用可能な候補へ変換しない。状態取得後と評価後も全体予算を確認する。LLMへ数値・状態判断を委ねない。

追加12テストと既存通常Graph／共通依存回帰、実PostgreSQL / Neo4jで計39テストを実行した。利用可能代替、候補停止、状態欠落、過去時点、空集合の観測時刻、生産作業の予定状態・inactive、不正adapter結果を確認した。AC-G05 / G06 / G09、T-R14 / R15の内部状態評価を支えるが、重要対象・SPOF全体調整、経路と公開DTO、認可済みTool / API / Agent接続は後続。Business能力・安全・経済受入の完了とは扱わない。

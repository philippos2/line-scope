# 成立評価用の必須Graph閉包

仕様正本ではなく、実装チェックポイントの記録。

正本domain-model §4 / §15.1、既存api-toolsの探索上限、transaction-designのGraph分析gateに従い、内部Graph readerへmandatory_closureを追加した。単一の検証済み世代・Neo4j read transaction・PostgreSQL共有分析gate内で、active / [effective_from, effective_to)に合う全必須上流を取得する。既存の予算・最終整合確認を省略しない。

DEPENDS_ON / SUPPLIESはrequiredで分類、PRECEDES / CONTROLS / PRODUCES / USESは必須。CAN_SUBSTITUTEは通常上流取得から除外する。optional関係はnode / depthの意味上の予算に含めないが、取得時間は全体deadlineに含める。Cypherは既存の固定queryとbindを使い、新しい任意query経路や識別子補間は追加しない。

成立評価にはBFS代表経路だけでは不足するため、交差関係・複数必須条件・循環戻り辺を含む全確認済み必須factsと型付きprerequisite mapを保持する。根拠factsのsource / target・record ID・version・requiredを維持する。depth / node上限やsoft deadlineで打ち切った場合はReachabilityの不完全性を保持し、未取得の依存を「上流なし」と扱わない。閉包結果を公開できるのはreader contextの最終gate成功後。

追加12の実PostgreSQL / Neo4jテストと既存Graph reader等の回帰、計32テストで、全AND関係、USES、DEPENDS_ON方向、optional、effective end境界、inactive、循環、各上限、対象欠落、時刻型を検証した。AC-G03 / G05 / G06 / G09、T-R15の読取部分を支えるが、直接代替候補読取、正本の利用可能性、共有予算での複数評価、Application / Tool / API接続は後続。公開SPOF機能の完成とは扱わない。

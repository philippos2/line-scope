# 複数重要対象・全除外の代替分析データ収集

仕様正本ではなく、実装チェックポイントの記録。

正本api-tools §17 / §20、domain-model §15.1 / §15.3 / §15.4に従い、開いた検証済みGraph read context内で複数重要対象・全除外・直接代替候補のデータを共有収集する内部モジュールを追加した。認可は呼出元Applicationの責務であり、公開Tool登録はまだ行わない。

全入力の型付きIDを正規化・sort・集合内重複拒否し、重要対象と除外対象の和集合を一つのdistinct node予算へ先に登録する。全入力の存在とactiveを全件確認した後、重要対象の必須閉包と除外対象の直接代替／各候補閉包を同じ世代・as_of・deadline・node予算で取得する。集合間の同じnodeは一件として数える。Product / ProductionOperationには正本にCAN_SUBSTITUTEがないため検索を行わず、必須閉包だけを保持する。

必須関係とprerequisite mapを全探索で結合する。上限外のnodeを追加せず、同一record IDで異なる必須factsが返れば破損として失敗する。node / depth / deadlineの不完全性は全体と各代替収集結果へ一貫して伝える。部分的に取得した候補を、全体完全な代替保証へ昇格させない。返却は最終reader gate成功後に限定する。

追加15テストと既存11テスト、計26テストをDocker内で実行した。実PostgreSQL / Neo4jで、複数重要対象・全除外・候補の共有予算、入力順の不変性、非代替型、欠落／inactive、集合間重複、不完全性を検証した。不正集合がnode lookup前に拒否されることも確認した。AC-G05 / G09とT-R14 / R15の収集部分を支えるが、全体の単一PostgreSQL状態観測、重要対象ごとの成立評価、経路・公開DTO、認可済みTool / API / Agent接続は後続。

# 共有予算内の一段代替分析facts収集

仕様正本ではなく、実装チェックポイントの記録。

正本domain-model §15.1 / §15.3 / §15.4、既存Graph探索上限・分析gateに従い、開いたGraph reader内で元対象・直接代替候補・各必須上流を収集する内部モジュールを追加した。readerのquery実装と収集調整を分離し、既存mandatory_closure / substitute_candidatesを使う。API認可、正本状態取得、評価と公開はApplicationの後続責務。

全探索で一つのdistinct node予算と同一as_of・世代・deadlineを共有する。外部のTraversalNodeBudgetも受け取り、上限一致と対象のadmissionを確認する。候補検索のページ上限も全体node上限以内。候補自身の閉包で予算を再初期化せず、未収集nodeを結果のprerequisite / factsへ追加しない。node / depth上限、soft deadlineによる不完全性を保持する。空集合は全収集が完全な場合だけ不存在の証拠になる。

直接sourceのみを候補とし、除外される元対象自身を候補から外す。候補IDを一意化して必須閉包を一度ずつ取得し、取得した別recordの関係Evidenceは保持する。元対象への依存、交差／循環辺、source record / versionを維持し、候補を利用可能と推測しない。収集したsearches・prerequisite map・必須／代替factsを評価器と後続Evidence構築へ渡せる形にした。最終gate成功前に結果を公開しない。

追加11の実DBテストと関連29テスト、計40テストで、全体予算、外部共有予算、候補閉包の上限、打切りと空集合、元対象への依存、複数record保持と評価器連携を検証した。複数recordのNeo4j fixtureは収集の重複制御を検証するものであり、正本の重複／期間重複登録規則を変更しない。AC-G05 / G06 / G09、T-R14 / R15の内部収集を支えるが、PostgreSQL利用可能性、重要対象／複数候補での全体調整、代表経路・公開DTO、Application / Tool / API接続は後続。

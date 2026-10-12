# 代替探索の公開前入力境界

仕様正本ではなく、実装チェックポイントの記録。

api-tools §17 / §20と既存Graph権限に従い、find_alternative_pathsの入力を内部AlternativePathRequestへ変換する検証を追加した。trusted Context、typed ID、時間、requested / system limitsを既存の単対象validatorで確認する。DB・Graph接続、Tool登録、HTTP / Agent公開はまだ行わない。

important_targets / excluded_nodesは非空の明示配列とし、配列内の正規化後重複を拒否する。各集合を型付きIDでsortし、両集合の和集合が実効node予算以内であることを確認する。集合間の同じIDは一件として数えつつ、重要対象自身の除外という分析条件を消さない。relation_types、client timeout、authorityを入力から受け付けない。認可を不正引数の検証より先に行い、未認証・権限不足を区別する。

追加43テストと既存62テスト、計105テストをDocker内で実行した。3ロール、identity、型付き集合・重複・UUID正規化、共有予算、各上限、unknown fields、future / historical時刻を検証した。AC-G05 / G09の入力境界を支えるが、全入力の存在／active確認、複数重要対象・複数除外の評価、経路／公開DTOとTool / API接続は後続。今回の契約詳細はapi-tools §20へ反映し、履歴を正本としない。

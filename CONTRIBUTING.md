# 開発・PR運用

LineScopeはBackend / Frontendを一つのリポジトリで管理する。
仕様の正本は[成果物一覧](docs/deliverables.md)の19文書。

## 変更の区切り

機能ごとに作業ブランチを作り、実装 → 対応テスト → checkpoint commitの順で進める。
ブランチ名は`feat/<feature>`、`fix/<issue>`、`docs/<topic>`等、目的を示す。
作業ブランチ内の複数commitを許容し、既存main履歴をrewrite / force-pushしない。
push・PR作成・mergeはそれぞれ別の操作として報告する。PR準備の指示だけでmergeしない。

## PRとmain

- 原則1 PR＝main上の1 Squash commit。
- GitHubではSquash mergeだけを許可し、Merge commit / Rebase mergeは無効にする。
- PRタイトルは`feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`のConventional Commit形式。scopeは任意。
- squash commitの既定タイトルはPRタイトル、本文はPR本文を使い、merge時にも内容を確認する。
- mainはPR必須、linear history必須、force-push禁止。管理者も保護対象とする。
- merge後はfeature branchを削除する。

GitHub設定で強制する項目と、repository内のworkflow / 文書による規則は別に管理する。
GitHub設定を変更する際は既存保護・required checksを維持し、対象項目だけを変更する。

## CI

現在のrequired checksは`Tests and migrations`と`PR title`とする。
Backend CIはlint / format、実PostgreSQLでの全基盤テスト・migration検証、CLI疎通を実行する。
全PRでCIを実行し、required jobをpath filterで省略しない。
依存はbackend/requirements-dev.lockで固定し、変更時に更新・検証する。

Frontendはサーバサイド完成後に追加し、その実装時に`Frontend tests and build`をCI・required checksへ追加する。
LogiScopeの同名checkや既存保護は、このリポジトリの設定作業では変更しない。

## 初回PRの比較元

初回のmainは、業務コードを含まないrepository初期化commitだけを持つ比較元とする。
基盤は`feat/backend-foundation`からPRとしてレビューし、承認後にSquash mergeする。
既存のローカルcheckpoint commitを保全するため、初回だけ空のmain初期化履歴を作業ブランチへ接続する。
これはmainへのPR mergeではなく、mainに基盤コードを直接入れる操作でもない。

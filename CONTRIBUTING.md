# 開発・PR運用

LineScopeはBackend / Frontendを一つのリポジトリで管理する。
仕様の正本と各事項の責務は[成果物一覧](docs/deliverables.md)で確認する。

## 変更の区切り

機能ごとに作業ブランチを作り、実装 → 対応テスト → checkpoint commitの順で進める。
ブランチ名は`feat/<feature>`、`fix/<issue>`、`docs/<topic>`等、目的を示す。
作業ブランチ内の複数commitを許容する。GitHubへpush済みの既存履歴はmain・作業ブランチともrewrite / force-pushしない。2026-10-12の日本語化・PR復旧に対する例外許可は終了しており、今後の操作へ適用しない。
push・PR作成・mergeはそれぞれ別の操作として報告する。PR準備の指示だけでmergeしない。

## PRとmain

- PRの確認・mergeは開発者が行う。
- 原則1 PR＝main上の1 Squash commit。
- GitHubではSquash mergeだけを許可し、Merge commit / Rebase mergeは無効にする。
- PRタイトルは`feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`のConventional Commit形式。scopeは任意。
- PRタイトルとコミットメッセージは必ず日本語で作成する。接頭辞とAPI名等の正式表記は維持し、説明・本文は日本語にする。Squash commitにも適用する。
- squash commitの既定タイトルはPRタイトル、本文はPR本文を使い、merge時にも内容を確認する。
- mainはPR必須、linear history必須、force-push禁止。管理者も保護対象とする。
- merge後はfeature branchを削除する。

GitHub設定で強制する項目と、repository内のworkflow / 文書による規則は別に管理する。
GitHub設定を変更する際は既存保護・required checksを維持し、対象項目だけを変更する。

## CI

現在のrequired checksは`Tests and migrations`と`PR title`とする。
Backend CIはDocker内でlint / format、実PostgreSQL / Neo4jによるテスト・migration検証、runtime imageの起動・CLI疎通を実行する。
テストは独立runnerの2 shard、runtime検証も別runnerで並列実行し、全jobの成功だけを集約check `Tests and migrations`の成功とする。failure / cancelled / skippedは集約を失敗にする。matrixはfail-fastを無効にして片方の失敗でも他方の検証・片付けを続ける。各jobの使い捨てDB環境を分離し、同じDBへsuiteを並列投入しない。
shardは全ケースの収集後、`backend/tests/ci_module_timings.json`の実測時間を重みとしてファイル単位で割り当てる。新規ファイルは既定の重みで自動的に含まれ、古い計測の項目は試験範囲を制限しない。各shardのログへ全収集数・選択数・全node ID集合のhashを出す。同じheadの全収集数/hash一致と選択数の合計を確認し、遅い30処理とjob時間を継続して確認する。
ローカルの通常実行は全件のまま。分割を再現する場合は使い捨て環境で`pytest backend/tests --ci-shard 1/2`と`--ci-shard 2/2`を実行する。同じCompose環境での実行は順番に行う。計測値は性能受入閾値ではなく、負荷が偏った場合に再計測して更新する。
全PRでCIと集約checkを実行し、workflow全体をpath filterで省略しない。
変更が`frontend/`と`compose.frontend.yaml`だけの場合、Backendの2 shardとruntime検証を省略する。Backend・共通設定・CI定義・未知のpath・空差分・判定不能時はBackendも検証する。手動起動は全検証とする。
集約checkは対象外と判定したBackend jobのskipだけを許容し、差分判定の失敗、予期しないskip、failure、cancelledを成功扱いしない。
Runtime依存はbackend/requirements.lock、開発依存はbackend/requirements-dev.lockで固定し、共通packageのversionを揃えて更新・検証する。

Frontendの`Frontend tests and build`はlint・型チェック・format・buildを実行し、既存required check `Tests and migrations`へ集約する。GitHub側に別のrequired checkは追加していない。
Frontendの自動テストは必要最小限とし、通常CIでは実行しない。必要に応じて既存の`npm test`と実ブラウザの主要操作確認を行う。
LogiScopeの同名checkや既存保護は、このリポジトリの設定作業では変更しない。

## 初回PRの比較元

初回のmainは、業務コードを含まないrepository初期化commitだけを持つ比較元とする。
基盤は`feat/backend-foundation`からPRとしてレビューし、承認後にSquash mergeする。
既存のローカルcheckpoint commitを保全するため、初回だけ空のmain初期化履歴を作業ブランチへ接続する。
これはmainへのPR mergeではなく、mainに基盤コードを直接入れる操作でもない。

## merge後のローカル更新

PR merge後は`git fetch --prune origin`、`git switch main`、`git pull --ff-only origin main`で追従する。
不要ブランチが溜まったら、Squash済みPRと未push変更の有無を確認して枝打ちする。
退避中のstashや未反映の実装を一緒に削除しない。

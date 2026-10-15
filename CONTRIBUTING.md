# 開発・PR運用

仕様の正本は[成果物一覧](docs/deliverables.md)、開発原則は[AGENTS.md](AGENTS.md)を参照する。
LineScopeはBackend / Frontendを一つのRepositoryで管理する。

## 普段の作業手順

1. 業務機能ごとに作業ブランチを作る。
2. 実装・文書・必要な検証をそろえ、意味のある単位でcommitする。
3. Draft PRを作り、タイトル末尾に`【WIP】`を付ける。
4. 必要な検証と最新headのCIを確認し、PR本文へ結果を記録する。
5. 使い捨て環境を片付け、Draftと`【WIP】`を解除して開発者へ引き渡す。
6. 開発者のmerge後にmainを更新し、不要なブランチを削除する。

## 変更・commit・PRの粒度

- ブランチ名は目的を示す。例：`feat/<feature>`、`fix/<issue>`、`docs/<topic>`。
- PRは、エンドユーザーが一連の操作を完了できる業務機能を単位にする。
- 関連する登録・計算・画面・Agent参照・業務経路の検証を、レビュー可能な範囲でまとめる。
- Backend / Frontendや内部部品だけで機械的にPRを分割しない。
- 作業ブランチには複数commitを置いてよい。commitは意味のまとまりで分ける。
- 実装と対応テストを確認してcheckpoint commitを残す。
- GitHubへpush済みの履歴は書き換えない。main・作業ブランチともforce-pushしない。
- push・PR作成・mergeは別の操作として報告する。PR準備の指示だけでmergeしない。

## PRタイトル・commit件名

### 形式

- 形式は`<type>: <日本語の説明>`。コロンの後に半角スペースを1つ置く。
- typeは`feat`、`fix`、`docs`、`test`、`refactor`、`chore`のいずれか。
- 括弧付きscopeは禁止する。`feat(agent):`、`feat(frontend):`、`fix(backend):`等を使わない。
- PRタイトルとcommitメッセージの説明・本文は日本語にする。
- 接頭辞とAPI名等の正式表記は維持する。
- タイトル形式を変更する場合は、実施前に開発者へ相談し、了承を得る。

| 用途 | 例 |
|---|---|
| 正しいタイトル | `feat: 設備名の候補から調査対象を選ぶ導線を追加する` |
| 作業中のタイトル | `feat: 設備名の候補から調査対象を選ぶ導線を追加する【WIP】` |
| 禁止するscope付きタイトル | `feat(frontend): 設備名の候補から調査対象を選ぶ導線を追加する` |

### WIP・Draft

- 作業中・必要な検証未完了など、merge可能と判断できないPRはDraftにする。
- merge可能になるまでは、タイトル末尾に`【WIP】`を付ける。
- 最新headのCI・結果記録・片付けを確認してから、Draftと`【WIP】`を解除する。
- 未完了のPRをmerge可能と案内しない。

### Squash merge

- PRの確認・mergeは開発者が行う。
- 原則1 PR＝main上の1 Squash commitとする。
- GitHubではSquash mergeだけを許可し、Merge commit / Rebase mergeは無効にする。
- Squash commitの既定件名はPRタイトル、本文はPR本文を使う。
- merge前に、PRタイトルとSquash commit件名が規定の形式であることを確認する。
- GitHubが件名末尾に付加する` (#PR番号)`は許容する。括弧付きscopeは禁止する。
- merge後にPRタイトルだけを変えても、Squash commit件名は変わらない。

## 検証と引渡し

### 実施する検証

- Backendのテスト・lintはDocker内で行う。
- Backendの試験選択・実行・引渡しは[backend-verification](.agents/skills/backend-verification/SKILL.md)に従う。
- Frontendのlint・型チェック・build・必要最小限の画面確認は[frontend-verification](.agents/skills/frontend-verification/SKILL.md)に従う。
- Frontendの自動テストは必要最小限とする。必要に応じて`npm test`と実ブラウザ確認を行う。
- 変更の影響に必要な検証を省いたり、テストを弱めたりして成功扱いしない。

### PR本文と片付け

- 実行した検証、件数・時間、結果、未実施範囲、既知の失敗・skipを記録する。
- CIは最新headを対象に確認する。過去headの成功を最新差分の成功と扱わない。
- 使い捨て環境だけを片付ける。継続デモのvolumeや退避中の実装を削除しない。
- 作業ツリーとrequired checksを確認してから、merge可能と案内する。
- 個別作業・判断・検証の履歴は`docs/history/`へ記録する。

## CIの構成

### Required checks

| Check | 成功条件 |
|---|---|
| `PR title` | PRタイトルが規定の形式に従う |
| `Tests and migrations` | 変更範囲に必要な各検証jobが成功する |

### 各jobの役割

- Backend：Docker内のlint・format、実PostgreSQL / Neo4jのテスト・migration検証。
- Backendのテスト：独立runner・独立DBの2 shardで実行する。
- Runtime：配布imageの起動・migration・CLI疎通を検証する。
- Frontend：`Frontend tests and build`でlint・型チェック・format・buildを行う。通常CIではUnit Testを実行しない。
- Frontendも既存の集約checkへ含める。GitHub側に別のrequired checkは追加しない。
- 全PRでworkflowと集約checkを実行する。workflow全体をpath filterで省略しない。

### Backendを省略できる変更

次の範囲だけで構成されるPRは、Backendの2 shardとruntime検証を省略する。

| 対象 | 省略対象のpath・形式 |
|---|---|
| Frontend | `frontend/`、`compose.frontend.yaml` |
| rootの文書・ガイダンス | `README.md`、`CONTRIBUTING.md`、`AGENTS.md`、`SKILL.md` |
| 各階層のガイダンス | `AGENTS.md`、`SKILL.md` |
| 文書・Skill資料 | `docs/`、`.agents/skills/`配下のMarkdown・HTML・SVG・画像・PDF |

次の場合はBackendも検証する。

- Backend・共通設定・CI定義に変更がある。
- Skillの実行スクリプト、docs配下の実行コード、未知のpathに変更がある。
- 空差分、差分判定不能、または手動起動である。

### 失敗・skipの扱い

- Backendのmatrixはfail-fastを無効にし、片方が失敗しても他方の検証・片付けを続ける。
- 同じDBへsuiteを並列投入しない。各jobの環境を分離する。
- 集約checkは、対象外と正しく判定したBackend jobのskipだけを許容する。
- failure・cancelled・予期しないskip・差分判定失敗を成功扱いしない。

### Shardの確認

- 全ケースを収集した後、`backend/tests/ci_module_timings.json`の実測時間でファイル単位に分配する。
- 新規ファイルも既定の重みで含める。古い計測の項目で試験範囲を制限しない。
- 各shardの全収集数・選択数・全node ID集合のhashをログへ出す。
- 同じheadの両shardで、全収集数とhashが一致し、選択数の合計が全収集数と一致することを確認する。
- 遅い30処理とjob時間を確認する。計測値を性能受入閾値と扱わない。
- 負荷が偏った場合は再計測し、根拠と更新値を記録する。
- ローカルの通常実行は全件のまま。分割を再現する場合は`--ci-shard 1/2`と`--ci-shard 2/2`を使う。
- 同じCompose環境で分割を再現する場合は、順番に実行する。

### 依存・GitHub設定

- Runtime依存は`backend/requirements.lock`、開発依存は`backend/requirements-dev.lock`で固定する。
- 共通packageのversionを揃えて更新・検証する。
- mainはPR必須・linear history必須・force-push禁止とし、管理者も保護対象にする。
- GitHub設定とRepository内のworkflow・文書による規則を区別する。
- 設定変更時は既存保護・required checksを維持し、対象項目だけを変更する。
- LogiScopeの同名checkや既存保護は変更しない。

## merge後のローカル更新

次の順でmainを更新する。

```sh
git fetch --prune origin
git switch main
git pull --ff-only origin main
```

- merge後はfeature branchを削除する。
- 枝打ち前に、Squash済みPRと未push変更の有無を確認する。
- 退避中のstashや未反映の実装は削除しない。

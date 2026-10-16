# 正式入力の統合比較checkpoint

## 再開と範囲

- #250は開発者がmerge済み。mainをe992b9218fed6fc7ecaf709609785eb638da0082へff-only更新し、tree一致を確認してfeat/maintenance-decision-inputsを削除した。
- 作業branchはfeat/registered-decision-comparison。正式入力の選択→比較→画面・Agent参照までを一つの業務経路として進める。
- PO-B08は未確定のまま。下流影響と上流インフラの意味を勝手に反転しない。本工程は既存の下流Graph契約と確定済みB01〜07で進める。

## 実装

- RegisteredDecisionsと純粋な比較組立を追加。明示した入力ID・共通期間・対象を検証し、PG正本と現在Graphを参照する。分析から更新要求を作らない。
- 旧MockDecisionProviderをAPI依存組立から外した。設定フラグや通常の比較問い合わせから固定費用・能力・安全を生成せず、未選択時は候補と不明を返す。
- 対応計画の時間・直接費小計、正式経済入力の小計／総額、能力／buffer、停止必須、過去履歴を区別する。計画小計の二重加算や履歴からの故障率推測を行わない。
- Frontendに候補取得・出典確認・選択・比較・Agent下書きを追加。旧固定デモ案内を正式入力の案内へ変更する。

## 検証・次の再開点

- 新規pytestは展開18件。既存の代表7シナリオは実PG登録値へ移行し、数値・未知・非加算を保持して確認する。
- 関連79件成功（12.29秒）。初期3件の失敗は、経済計算のoption配列が正規化順で返ることを考慮しない試験参照を、option名による参照へ修正して解消した。既存Starlette/httpx警告・終了時logging出力失敗メッセージあり。
- Agent関連182件成功（5.65秒）。比較Tool取得後はサーバの説明を即時返し、追加モデル生成を呼ばないことを確認。explicit_as_ofと現在Graph比較の混同もTool admissionで拒否する。
- FrontendのDocker内lint・型・format・buildと新しい実ブラウザscriptを最終確認中。全体回帰は実行中。
- 旧検証scriptの固定値依存を移行中。実ブラウザ・最新head CI・全体回帰・片付けは未完了。Draft / WIP解除はそれらの確認後に行う。
- 次はscript移行と画面check、全体回帰、正式入力を登録・選択したブラウザ経路、実モデルのcompare_registered_inputs参照を確認する。同じ試験DBへsuiteを並列投入しない。

## 選択・表示境界の補完

- AgentのTool引数を、元の問い合わせに含まれる明示選択JSONへ束縛した。純粋normalizerを共有し、日時表記とID集合順を正規化して比較する。モデルによる入力ID・期間の差し替えを拒否する。
- 比較Tool結果のPARTIALをHTTP envelopeにも反映し、Agentの比較結果を画面の比較・Graph・Evidenceへ接続した。計算見出しは案別金額とし、長い構造化結果を見出しへ詰めない。
- 初期全体回帰は3,920成功・1skip（367.02秒）。実行中に追加した選択guard等の最終差分はこの全体回帰だけで合格扱いしない。対象試験を再実行し、最新head CIの全件結果を最終根拠とする。
- 最終差分の対象試験・実ブラウザ・最新head CIは確認中。旧検証scriptを移行し、所有する試験環境の片付けまで行って引き渡す。

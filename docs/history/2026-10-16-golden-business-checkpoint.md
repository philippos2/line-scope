# BS-03の正式入力・Golden代表受入と品質測定

## 再開点と変更

- PR #253のmergeを確認しmainを`67514e2206dac07b833000baf5b79c0f368d6b94`へff-only更新。tree一致を確認して旧feature branchを削除。退避・他worktree・push済み履歴は変更しない。
- branchは`feat/golden-business-acceptance`。機能checkpointは`b117d1f`、Read要約／圧縮は`c10f402`、Golden fixtureの修理計画追加は`7f99217`。
- EconomicInputの任意cost_recoveryへ日次稼働・一定稼働・交換効果・出典・確度を登録。未知・不適用・0率を分け、480000 JPYと150 daysを正式入力から算出。
- 新項目がbefore / afterにあるSnapshotはv6、なければv2。Migration 012はversion制約だけ拡張し、旧hash・省略形状・承認待ち・再送を維持。
- UIの登録／訂正→別manager承認→requester確定→最新version再取得→比較・Agent説明まで接続。
- Goldenは実Graph、構造候補、能力90−60、buffer120と条件付き4時間、修理1900000 JPY（作業／停止8時間）、交換2400000 JPY（調達336・作業4・停止2時間）、継続480000 JPY、条件付き安全宣言、費用回収150日を固定。品質・実運転許可・将来故障率の不明は保持する。
- 単一状態のサーバ要約、最終モデル本文の短縮、入れ子の共通依存経路の可逆圧縮を追加。権限・60秒制限・Tool選択・API原データ／Evidenceは維持。

## 試験の選定と結果

- 新規20ケース：入力／算出／Snapshot／API／Goldenが18、単一状態要約の境界が2。既存v6 API全経路と重複する単純roundtripケースを、劣化損失が全稼働時間へ適用されない境界へ置換。v6 roundtripのassertはAPIの作成・承認・確定試験に保持。
- 最初の関連試験は194成功・1失敗。既存DB試験がv6を無効versionと仮定していたため、無効値を7へ更新し検証を維持。再実行195成功（25.37秒）。
- Agentを含む関連368成功（23.80秒）、圧縮・期間適用の更新後も368成功（24.12秒）。最終対象22成功（2.06秒）、Goldenの修理計画を追加後のGolden／Graph圧縮3成功（1.29秒）。
- Ruff check／formatは380ファイル成功。Frontend lint・型・format・build成功。既存Starlette/httpx warningと終了時logging output failedあり。
- ブラウザ初回は閉じたパネル内のrole selector、2回目は選択欄のアクセシブル名で失敗。前者をselector修正、後者を明示的なaria-labelで修正。3回目はPASS。
- 実ブラウザでv6登録条件の読込み・有無切替・編集・別manager承認・requester確定・version 2再取得と150日、実モデルcompare_registered_inputs、費用差・構造・能力・履歴非加算、1440／768／390幅、HTML非実行、storage非保存、接続解除時の消去を確認。
- 実Embedding / Qdrant / PostgreSQLで取込み・引用・版更新・再構築・停止時の拒否の代表検証はPASS。一般検索relevanceの合格とはしない。

## 実Read Agentの測定

- 同じread-demo-v2の5質問を使い、初回2/5成功、最終本文短縮後3/5、入れ子経路圧縮後3/5。失敗を再実行の成功で隠さず、質問・60秒制限を変えない。
- モデルは導入済み`qwen3:30b-a3b-instruct-2507-q4_K_M`、観測digestは`19e422b0231392335cfc49cfd172de7034bb1aeabb08aa307cce745c60b272fe`。モデルのdownload・unload・制限延長は行わない。
- 最終測定はcommit `7f99217ce88af5341c5cedb94ffe09a7c34f862b`、測定開始時clean。原結果は[read-quality-baseline.json](2026-10-16-read-quality-baseline.json)。最終結果はFAILであり一般品質は未受入。

| 質問 | 構造化結果 | エラー |
|---|---|---|
| state_and_cause | PASS | — |
| downstream | FAIL | AGENT_LIMIT_REACHED |
| missing_equipment | PASS | — |
| upstream | PASS | — |
| common | FAIL | AGENT_LIMIT_REACHED |

成功した状態・対象不存在・上流の説明は、現在登録情報、原因不明、上流と停止影響の区別、未評価次元を保持している。失敗した2質問の文章は評価不能。原因をcold startや特定のDBへ断定せず、次の品質PRで多段LLM実行と入力・出力負荷を計測して解消する。数値合格閾値を勝手に定めない。

Embeddingは導入済み`embeddinggemma:latest`、digest `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`。代表引用の成功と一般検索品質を区別する。

## 残工程と引渡し

- 今回はBS-03の正式入力とGolden代表経路。一般品質の失敗を残したままプロダクト全体を完成扱いしない。
- 次はReadの時間制限失敗、全BS対応、説明／検索品質と必要な安全・履歴・UIの不足を一つの品質受入PRへ集約。その後、完成schemaで運用復旧1〜2 PR。
- 進捗は約90%、残りは今回を含め3〜4 PR。ガントを工程1=今回、2=品質、3〜4=運用復旧へ再配置し、Chromiumで描画を確認。
- 最終headのCI件数・時間・収集hashと片付け・ready化はPR本文に保持する。

ログは`/tmp/linescope-golden-tests*.log`、`/tmp/linescope-golden-final-targets.log`、`/tmp/linescope-golden-final-check.log`、`/tmp/linescope-golden-frontend-final.log`、`/tmp/linescope-golden-browser*.log`、`/tmp/linescope-golden-read-quality*.json`、`/tmp/linescope-golden-vector.log`。ガント描画は`/tmp/linescope-golden-gantt.png`。

## 初回CIの修正

- head `2f94184`のCIはshard 1成功、shard 2で既存API試験1件が失敗。単一状態をサーバで要約する契約変更に対し、旧モデル文面の完全一致が残っていた。実読取り・Evidence・Tool trace・書込みなしのassertを保持し、STOPPED・version 1・原因／安全性／将来状態を推論しない説明を検証する形へ更新。新規ケースは増やしていない。
- 修正後のAPI／状態要約試験とRuffをDocker内で再実行して成功。最新headの全CIはPR本文へ追記する。

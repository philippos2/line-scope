# 業務検証・Snapshot関連の配置整理

## 範囲

配置整理の第三段階。canonical、snapshot、assignments、relations、dependency_cyclesの5モジュールをbackend/src/linescope/domainへ、対応する10テストモジュールをbackend/tests/domainへ移動する。呼出側・共有fixture・故障注入先のimportを更新する。旧パスの再exportや互換shimは追加しない。

Canonicalization、hash、Snapshot、期間規則、required/代替関係、cycle検証の処理・テストassertは変更しない。業務サービス、認可・承認policy、Trusted Execution Contextは現配置に残す。snapshotが共有ExecutionContextへ依存する現状も維持し、完全な依存反転を宣言しない。domain配下のテストには既存のDB制約照合も含まれ、全件がDB不要のUnit Testとは扱わない。

## 継続する判断基準

利用者の指示により、責務分離・境界・依存方向・構造化を継続的に確認する方針をimplementation-design/AGENTS.mdへ記録する。現在のコードと重要判断の記録から再開できることを重視し、配置整理後の責務改善も別工程として扱う。README・文書群の全面整理はバックエンドが一段落してからとする。LogiScopeコードは再利用していない。

## 検証

本体57モジュールのAST比較でimport以外の処理変更がないことを確認。既存の全体テストとCIのpackaged migrations / Compose起動確認で、収集・import・業務挙動を検証する。

ローカル結果: Docker内全体2,474 passed / 1 skipped / 1 warning（184.71秒）。移動前と同じ件数。ruff check / format成功（154ファイル）。

# 上流インフラの業務分析統合

## 判断と着手点

- 開発者の「良い」によりPO-B08は「設備が依存する上流資源の提示」として確定。
- PR #251のmergeを確認。mainは`0ca26e043f8a5bd14994b9e4e2ff8e714dc40048`へff-only更新。
- Squash後のmainと旧featureのtree一致を確認して旧branchを削除。push履歴は変更していない。

## 実装範囲

- 正式入力の比較APIとAgentの比較・候補取得に既存の上流探索を接続。
- 上流依存と下流影響は別フィールド。経路・Graph世代・観測時刻を各Evidenceに保持。
- Graph世代が切り替わった場合はGRAPH_NOT_CURRENTで結果を返さず再取得を要求。
- 画面では依存インフラを別欄に表示。部分探索の空結果を依存なしとしない。
- 関係種別・DB schema・更新／承認権限は変更しない。資源の稼働状態・供給能力を推測しない。

## 検証計画と現在の結果

- 新規pytestは3ケース。正常のAPI／Agent・経路Evidence、実探索上限による部分結果、世代切替時の拒否を選定。直積追加なし。
- 関連34ケース成功（15.67秒）。既存Starlette/httpx warningと終了時logging output failedを確認。
- Backend ruff check／format（372ファイル）・Frontend lint／型／format／buildをDocker内で確認。最終Frontend差分をmountして再検証し成功。
- 実モデル・実ブラウザの比較フローは2回目でPASS。初回は実モデル呼出しのAGENT_LIMIT_REACHEDで失敗。制限・モデル・質問を変えず再実行し、compare_registered_inputs取得、上流インフラと下流影響の分離、経路Evidence、正式入力の計算・除外・不明・期間拒否を確認。
- モデルは導入済み`qwen3:30b-a3b-instruct-2507-q4_K_M`。1440／768／390幅のoverflowなし、出典HTML非実行、storage非保存、接続解除時の消去を検証。390幅のスクリーンショットも確認。一般LLM品質合格とはしない。
- 試験用Composeと2回分のブラウザ環境をvolume込みで削除し、所有するimage tag 10件を削除。継続デモは変更していない。
- PR #252はDraft／【WIP】で作成。最終headのCI・件数・時間・収集hashとready化の記録はPR本文を参照。
- ログは`/tmp/linescope-infrastructure-tests.log`、`/tmp/linescope-infrastructure-browser.log`（初回失敗）、`/tmp/linescope-infrastructure-browser2.log`（再実行PASS）、Frontend最終確認は`/tmp/linescope-infrastructure-frontend-final.log`。

## 残る工程

- 全BS／Goldenの正式入力統合、不明・拒否・一般LLM／検索品質の受入。
- 完成schemaを含む運用・バックアップ復元・派生再構築・障害復旧の一括確認。
- 進捗は約88%（85〜90%）、#251 merge後の残りは2〜7 PR（中心4〜5）。受入未検証を完成扱いしない。

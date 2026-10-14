# 根拠付き日本語要約の再開記録

作業記録であり、仕様正本ではない。

- #224はmerge済み。main9ec1bb2からfeat/decision-japanese-summary、commit a3563ee、PR #225。
- Decision Packageからサーバが日本語要約を描画。状態・直接／間接候補・探索不完全・仮想停止損失率・修理総影響・能力不足・交換待ち期間・累積劣化を提示。不明を0にせず、継続案除外とデモ入力／安全性・最適案未確定を必ず表示。
- optional LLMは固定IDの表示順だけを選ぶ。自由文・数値・業務判断・Tool指定は不採用。未設定／出力不正／例外時は既定順へfallbackし、取得済みの分析を保持。最大20秒のモデル呼出し予算。
- 関連24成功、5.35秒。追加8ケース。lint・format326ファイル成功。
- verify_decision_summary.py --docker-group docker --model qwen3:30b-a3b-instruct-2507-q4_K_Mの専用Compose/curlで実OllamaのVALIDATED_ORDERとサーバ要約を確認。修理総影響1900000円、継続案除外、元の承認・実行経路も通過。
- 実試験後に損失率表示を追加し、最新コードは関連24テストで再検証。モデル順序選択ロジックは同一。モデル選定／全般品質の受入ではない。
- 専用volume／認証情報とローカル試験環境は片付け済み。DB・SQL・権限・承認／実行・transaction・Outboxは変更なし。既存警告とlogging output failedは未調査。

## 現在の到達点

API/curlのデモは見せられる。実PG・Graph・文書引用・明示的な比較入力・Prepare→Approval→Executeの経路がある。Embedding/Qdrantは実疎通済み。LLMは既存Read/Graphと今回の限定順序選択で実疎通済み。費用・能力・安全はfixture、一般ReadAgentの自由文grounding・業務シナリオ全体の品質受入・Web UIは未完了。

#225のmerge確認から再開する。個人デモの最小完成形を優先し、正式業務受入の未決定を試作完走の無条件な前提にしない。次の区切りではデモとしてのバックエンド到達範囲と必要な残件を整理し、過剰に内部部品を積み上げない。

CI全成功：3749成功・1skip、収集3750件・hash一致、選択1783＋1967＝3750。試験時間199.60秒／264.96秒。runtime・migration・PR title・集約checkも成功。

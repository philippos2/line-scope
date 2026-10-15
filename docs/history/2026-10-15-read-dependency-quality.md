# 上流・共通依存の説明品質と次工程

非正本の作業履歴。業務仕様・Agent責務・LLM評価は対応する正本文書を参照する。

## 再開と判断

- #241のmergeを確認し、mainをa11b1e6へff-only更新。feat/read-agent-qualityで作業。
- 代表UI工程後、正式業務入力のPO-B01〜08が未決定と確認。既存fixtureを業務仕様として採用せず、判断案を[未承認の検討記録](2026-10-15-business-input-proposal.md)へ整理した。
- 経済入力から進める案のPO-B01 / B02 / B07について開発者へ確認中。回答なしを承認と扱わず、その他の項目も未決定のまま維持する。
- 判断待ちと独立して、既存Read Agentの回答品質を改善する。動画は着手しない。PRは業務経路と対応検証・履歴をまとめる。

## 実装・境界

- 単一の上流依存・共通依存を、検証済みのCURRENT / DEPENDENCY_REACHABILITYの集合から専用要約へ変換。上流距離と型別件数、共通候補件数、完全性、未評価、一部参照失敗を表示する。
- 共通依存を原因／SPOFの確定とせず、空の部分結果を依存なしと断定しない。名称やUUIDを推測・再列挙しない。
- DB参照や探索を要約へ追加しない。Tool結果・経路・Evidence、API形状、認可、Prepare / Approval / Execute、transaction / Outboxは変更しない。
- 既存下流要約は維持。複数Graph・代替・SPOFは既存の自由説明経路を維持する。
- Promptの「RAG・計算は未接続」という固定記述は、実際の公開Toolと取得結果に従う指示へ修正。RAG groundingの実LLM受入を済ませた意味ではない。

## 検証設計と実測

- 要約6件（上流／共通 × 完全非空／不完全非空／不完全空）、非CURRENT・複数Graphの拒否2件、Agent接続2件、追加probeの完全性確認2件、計12件追加。その後、非200の公開エラー応答とHTTPステータス保持／通常のHTTP一致検証の維持を確認する1件を追加し、計13件。無条件のRole等の直積を生成しない。
- 対象の純粋試験は既存分と合わせ25件成功。実PG / Neo4jのAgent / Graph APIを含む対象回帰は60件成功・既存Starlette警告1件、約4.6秒。
- 初回回帰で既存API試験2件の上流回答期待が旧LLM固定文に一致せず失敗。新しい上流件数／距離／未評価／UUID非再列挙の意味検証へ改訂。既存の経路・Evidence・状態検証は維持した。
- 実モデルqwen3:30b-a3b-instruct-2507-q4_K_Mで変更前の3質問を実行し、構造化結果は3件成功。回答も登録状態と原因不明、下流の到達／未評価、対象不存在を保持した。reportは/tmp/linescope-read-quality-after-ui-241.json（0600）。
- dataset read-demo-v2へ上流と共通の2質問を追加。共通は既知Product ID付きであり、名称だけの対象解決の受入ではない。
- 最初のv2実行は4件成功・共通依存1件失敗。旧probeがHTTPエラー応答を保存せず原因は未特定。期待HTTPを固定しない評価用取得と公開エラーコードの記録を追加した。通常の最小フローは期待HTTPの検証を維持する。
- 修正後のreport /tmp/linescope-read-quality-dependencies-v2-diagnostic.json（0600）は構造化5件成功。上流111字・共通117字で件数・完全性・未評価を保持。Prompt修正と成功の因果関係は断定せず、初回失敗を消さない。実行時revisionはa11b1e6 / dirty=trueであり、最終commitで再評価する。
- Docker内ruff check / format（339ファイル）・git diff --check成功。専用の実DB回帰環境を削除済み。commit 2749845 / dirty=falseでの再評価report /tmp/linescope-read-quality-2749845.json（0600）も構造化5件成功。診断側は公開応答保存後もHTTP 200の必須条件を保持する補強を追加。CI結果はPRへ記録する。
- モデルdigestは未固定、一般品質閾値も未設定。構造化PASSと文章レビューを区別し、固定5質問を一般品質承認にしない。

## 残件・再開地点

- PO-B01 / B02 / B07の回答があれば、その採用範囲だけを正本・下位契約・AC・Testへ反映して経済入力の業務経路を設計・実装する。全8項目を一括承認したと扱わない。
- 回答がない場合は正式業務意味を補完しない。複数Graph／代替／SPOF、RAG grounding、曖昧対象・Injection等の実LLM品質は残る。
- 全BS / Golden・運用復旧の正式受入も残る。現PRのmerge確認後に次工程へ進む。

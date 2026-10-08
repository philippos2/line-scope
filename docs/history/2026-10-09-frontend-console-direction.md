# Frontendコンソール方針の記録

2026-10-09。POが共有し内容を妥当と評価したChatGPTのUI案を、有力候補の一つとして保持する。採用・UI仕様の確定ではない。Object Explorer / Graph Canvas / AI Agent Panel / Action Drawer / Status Bar案を、サーバサイド完成後のUI方向性として記録した。画面実装は再開していない。

対象はrequirements §13.1、frontend/README、履歴index。19文書外に新しい仕様正本を作らず、既存要件へ方向性を追記した。検索Read Toolの実装PRとは別のdocs branch/PRへ分けた。

Graphを中心にObject / Evidence / Actionを関連付け、低彩度の基調と意味色、公開Tool Trace、Object Detail、AI RecommendationとHuman Approvalの区別を候補として整理。初回UIはExplorer / Graph / Agentの3領域を優先し、Action Drawerを次の反復に分ける候補。面積比・component・React/TypeScript/React Flow等は採用確定せず後続で評価する。

例示のDEGRADED / MAINTENANCE、Location、production_managerによる設備更新は既存の状態集合・属性・権限へ追加しない。Equipment本体versionと状態versionを区別する。Graph非CURRENT・不完全探索・保存方向/影響方向・現場roleのGraph制限・canonical Snapshot・確定after/current value・内部推論非公開を画面方針にも適用する。Qwen例はmodel選定と扱わない。

要件・domain-model・access-control・api-tools・data-modelとの責務整合と相対リンクを確認。コード・設定・Frontend package/buildは変更なし。UIの実測・画面試験・操作仕様・UI ACはサーバサイド完成後に行う。

同日POからChatGPT / Claude / Geminiの支援が可能と伝えられた。初回レイアウト案ができた段階で、観点付きレビュー依頼を検討する方針をfrontend/READMEへ追記した。外部AIへの送信・相談を実施した記録ではなく、今後必要時にPOへ依頼する方針である。

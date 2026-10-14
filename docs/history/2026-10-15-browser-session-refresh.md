# F5後の接続復元

開発者はF5後の接続維持と接続画面への導線を要求した。Action画面を優先せず、この修正を先に実施。

- PR #238、b2e7aee。opaque HttpOnly／SameSite=Strict cookie、固定8時間・256件までのprocess-localセッション。Bearerはserverに保持し、各要求で既存identityを再確認。
- GET /session、POST /session/login、POST /session/logout。cookie変更操作はOrigin一致と専用headerを要求。既存Bearer、業務権限、Approval／Execute条件、transactionは維持。
- UIはF5で接続を復元。上部接続設定から切替・解除・調査画面への復帰。分析結果の永続復元は対象外。
- Backend追加13件PASS。Frontend既存11件PASS、新規ケース0。実ブラウザでF5維持、設定導線、解除後F5未接続を確認。
- 継続デモへ反映。API再起動でセッション失効、切替後は一度token接続が必要。
- #238 merge済み。CI38594624231は3779 passed／1 skipped、3780件の収集hash一致。Frontend静的検証／buildとruntimeも成功。
- 文書変更は機能PRに混ぜず別PRで反映。Action画面は未着手のまま、次工程で再開する。

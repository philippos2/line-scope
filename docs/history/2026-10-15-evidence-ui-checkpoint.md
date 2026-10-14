# Evidence表示のチェックポイント

非正本の作業記録。

- PR #236、945942b。Evidenceの情報源別カード、観測日時／Graph世代／入力version／計算根拠／原文を表示する。
- 文書引用のある応答は抜粋と引用metadataを文字列描画し、URIを自動取得／実行しない。
- 単体テスト追加0件、既存ブラウザ1フローの確認を更新。実API＋PG＋Neo4jでPASS。使用応答に文書引用なし、実RAG引用の画面確認は後続。
- CI38589864954成功。Frontend28秒、Backendとruntime対象外省略。
- ブラウザ用デモlinescope-browser-demoへ反映、維持中。私有設定と起動案内は.env.browser-demo／data/browser-demo/start.txt。
- #235接続案内修正後、開発者がブラウザ接続を確認した。当初の失敗原因は確定していない。
- 次工程は、退避中の起動・CI運用・roadmapとFrontendガイダンスを別文書PRでまとめる。続いて既存APIの変更Prepare／要求閲覧／別承認者Approval／requester Executeを画面に接続する。LLMに確定操作させない。

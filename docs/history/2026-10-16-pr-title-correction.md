# PR件名修正と作業方針の確認

仕様・開発規則の正本ではなく、個別作業の履歴。

## 背景と開発者指示

#243にfeat(agent):、#244にfeat(frontend):というscope付きPRタイトルを付けた。#242以前のscopeなしの書式を確認せず変更した判断が誤り。開発者の指摘により両PRのタイトルをscopeなしへ変更したが、merge済み#243のcommit件名が変わっていないことを見落とし、修正済みと報告した。

開発者は#243のcommit件名修正に限って今回だけforce-pushを許可し、GitHubの保護設定を一時変更して直後に復元することも了承した。今回の許可は終了しており、今後の操作へ転用しない。

## 実施結果

- #243: c8c5f6c89d7537e11fa5c0376b82918ccba90ffa → c814ea1320bd74302f21d51b593fb3359f1a74cd。件名を `feat: 代替とSPOFの構造判定を根拠から要約する (#243)` へ修正。
- 後続#244: a91d16f3c1cce9d3de23c62de8ee2b11b772a3ff → 7153efef6ce0979debae34c80c710560f1541f36。親commitの変更に伴うSHA変更。
- 各commitのtree一致、旧mainと新mainのファイル差分ゼロを確認。author / committer情報・日時・本文を保持し、再作成時に元のGitHub署名を除去。
- 通常のforce-with-leaseはGitHub保護に拒否された。管理者適用の一時解除だけでもforce-push禁止が残り拒否され、設定を復元した。その後、許可された修正のため管理者適用とforce-push許可を一時変更し、旧mainをlease条件に更新。
- 更新直後に保護設定を復元。変更前後の全保護設定JSON一致を確認。管理者への保護適用=true、force-push許可=false、required checks・PR必須等を維持。
- ローカルmainも追従。旧mainは `refs/backup/pr243-title-20261016/main` に保全。

## CONTRIBUTINGの修正

開発者の指示により、PRとSquash commit件名の具体的な形式・type・scope禁止・merge前確認をCONTRIBUTINGへ追記。今回限りの例外終了を同ファイルへ書いたのは文書責務の誤りと指摘されたため削除し、本履歴に記録した。CONTRIBUTINGは継続して適用する共通の手順・規則を扱う。

## 旧CONTRIBUTINGから移した記録

旧CONTRIBUTINGには「2026-10-12の日本語化・PR復旧に対する例外許可は終了しており、今後の操作へ適用しない」と記載されていた。この日付付き記録も共通ルールから削除し、ここへ移した。恒久ルールとしてのpush済み履歴の書き換え・force-push禁止はCONTRIBUTINGに維持する。

## 優先順位についての確認

開発者の感想・問題提起・将来構想を、そのまま即時着手の指示として扱わない。設備候補選択を計画へ割り込ませた判断は誤りで、いったん#244をdraftへ戻した。開発者が作成済みの変更は入れると明示した後にreadyへ戻し、検証・引き渡しを完了した。以後は合意済みの残工程の完成を優先し、提言の妥当性・必要性・工数・計画への影響を精査する。改良は後にし、優先順位や運用の変更は実施前に相談する。

## 共通規則・Skillの点検で移した記録

root AGENTSとbackend-verification Skillにも「2026-10-12の日本語化・PR復旧に対する例外許可は終了しており、今後の操作へ適用しない」という記録が残っていたため、削除して本履歴へ集約した。push済み履歴の書き換え禁止という恒久ルールは維持。

実装支援AGENTSの旧記述「今回のPO方針は2026-10-09に利用者が推奨案を採用し確定した」も履歴へ移した。この過去の記録を現在のPO未決定事項の承認に転用しない。業務仕様は各正本を参照する。

旧CONTRIBUTINGから、初期構築時だけに適用した次の記述を移した。

### 初回PRの比較元（旧記述）

初回のmainは、業務コードを含まないrepository初期化commitだけを持つ比較元とする。
基盤は`feat/backend-foundation`からPRとしてレビューし、承認後にSquash mergeする。
既存のローカルcheckpoint commitを保全するため、初回だけ空のmain初期化履歴を作業ブランチへ接続する。
これはmainへのPR mergeではなく、mainに基盤コードを直接入れる操作でもない。

## 開発原則と作業手順の配置整理

開発者からdocs/implementation-design/AGENTS.mdの内容はSKILLに置くべきではないかとの指摘があり、同じPRで修正する指示を受けた。別のAGENTSを詳細手順の正本とする構成を廃止し、共通原則と参照入口はroot AGENTS、分野ごとの具体的手順は既存SKILLへ統一した。

削除した実装支援AGENTSの対応先は次のとおり。

| 元の内容 | 維持先 |
|---|---|
| 正本確認・不整合・PO未決定を推測しない・完了原則 | root AGENTSとdeliverables |
| Trusted Context・SQL/Cypher・RAG認可のレビュー | backend-secure-coding Skill |
| Approval/Execute・version・Snapshot・Outbox等のレビュー | backend-transaction-review Skill |
| 設計境界・配置整理・refactoringの手順 | backend-architecture Skill |
| AC照合・検証・PR引き渡し | test-design / backend-verification Skill |
| LogiScope参照の制限 | root AGENTS |
| 業務仕様・Graph/RAG/DB/API等の契約 | deliverablesが示す各正本 |

手順は既存SKILLに既に存在するため重複転記を増やさず、backend-architectureの開発原則への参照をrootへ変更した。業務仕様・権限・Test条件の変更はない。削除文書への現行参照を更新し、deliverablesの文書数を19へ修正。過去履歴の参照表記は当時の記録として保持する。

## 文書変更時のCI対象判定

開発者の依頼でCIを調査し、#233の差分判定はfrontend/とcompose.frontend.yamlだけをBackend対象外にしており、文書・AGENTS・SKILLの除外が未実装であることを確認した。同じPRで文書のみの変更時にBackend検証を起動しないよう修正する指示を受けた。

明示した文書・ガイダンスのパスと形式を除外し、コード・共通設定・CI定義・未知path・空差分・判定失敗・手動実行ではBackend検証を維持。集約checkは継続して実行し、意図したskipだけを許可する。Frontend検証の実行条件は変更していない。追加はsubTest展開を含め16ケース、全直積を作らずパスの同値クラスと混在・判定失敗を選定。

CI判定の追加試験はunittest 26メソッド（既存を含む）で成功し、subTest展開を含む追加ケースは16。Docker内ruff check / formatも成功した。実際の差分パスを使い、文書整理だけの差分でBackend不要、CI判定コードを含む差分でBackend必要となることを照合した。

開発者からPR内のcommitをまとめる指示があり、push済み作業ブランチの履歴を書き換える操作について、PR #245の作業ブランチだけに限る今回のforce-with-lease許可を得た。mainと保護設定は変更せず、変更内容を保ち、意味上の変更単位ごとにcommitを整理する。今回の許可を以後のforce-pushへ転用しない。

当初全変更を1 commitへまとめたのは「適宜squash」の解釈誤りであり、開発者の指摘に従い文書責務の整理とCI対象判定の2 commitへ分離した。

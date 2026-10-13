# KnowledgeDocument metadataスキーマ

## 範囲と根拠

PR #203 merge後、RAGの最初の実装単位としてdata-model §2 / §11、rag-design §2 / §8で定義済みのmetadataをmigration 007へ実装する。要件・業務意味・既存migrationは変更しない。

document_id、document_code / document_version、title、source_uri、access_class、active、本文byte列のSHA-256、監査時刻を保持する。正のversion、FACTORY_INTERNAL、hash形式、業務キー一意性、document_codeごとのactive版最大1件をDBで保証する。source_uriは設計どおりNULL可。監査時刻は既存業務schemaと同じTIMESTAMPTZ / clock_timestamp方式。

本文は管理対象ファイル、Qdrantは派生Indexという責務を維持する。テーブルは文書本文やchunk、embeddingを保持しない。runtime / query / projection roleへこの段階で新たな権限を付与しない。

## 試験設計

追加見積もり・実際とも13ケース。正常保存1、非正version2、必須metadata NULL5、未知class1、hash長／文字種2、inactiveを含む業務キー重複1、active版一意性と切替のDB transaction1。因子間の直積は使わず、DB制約の代表値・境界と独立した違反を確認する。

既存migration試験を新しい適用一覧へ更新し、旧schemaからのupgrade、既存行保持、同時migration、checksum、rollback、Graph初期化状態／Outbox非捏造を引き続き検証する。新しい試験DMLはCoreで構築・bindし、攻撃文字列も単なるdocument_codeとして保存する。

## 未実装

新versionが既存最大を超えることの確認、document_code単位の直列化、upsert成功後のactive切替は後続Applicationの責務。部分UNIQUEだけで有効化の業務フロー完了とはしない。

AC-R01〜03 / T-R18全体は未完了。本文hash照合、Parse / Chunk、embedding、Qdrant検索・再構築、検索後／生成前の再認可、citation、Tool / API / Agent接続を後続で実装する。モデル選定や未確定のPO-B業務ルールをこのschemaから確定しない。

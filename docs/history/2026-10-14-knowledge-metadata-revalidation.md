# KnowledgeDocument metadataの内部再確認境界

## 実装範囲

rag-design §5 / §8とaccess-control §9を根拠に、検索候補のdocument_id / document_version / content_hashを正本metadataで再確認する内部Application部品を追加する。Tool / API / Agentへは公開しない。

KnowledgeMetadataGuard → core_knowledge → PostgreSQLの順に責務を分ける。trusted ExecutionContextと候補の型・version・hash・authority field不在を確認後、query接続のREAD COMMITTED / READ ONLY transactionで単一Core SELECTを行う。activeかつFACTORY_INTERNALでID / version / hashが一致する正本だけを返す。空候補・全件除外でも同じstatementで観測時刻を返す。重複参照を集約し、結果をID順にする。

v1のretrieve最大20件に合わせ内部候補バッチも20件までに制限する。これはAGENTSの暫定テストレビュー基準とは別の契約由来の上限である。本文・source_uri・access_classを候補から採用せず、正本の値を取得する。ここでのmetadata一致を本文hash検証・chunk証明・citation完成とは扱わない。

query roleにknowledge_documentのSELECTだけを追加する。runtime / projectionへの権限追加、write / DDL、障害時の強い接続へのfallbackは追加しない。DDL権限設定は既存のPostgreSQL固有例外を使用する。SELECTのtuple候補はCoreのpostcompile展開でplaceholderを生成し、値はbindしたままpsycopgへ渡す。

## 試験設計

見積もり・実際とも追加16ケース。正常系2、stale / hash不一致 / inactive / 不存在4、不正入力6、trusted context不足・再確認での失効・障害秘匿・実DB role各1。ロールは共通の認証済み条件を使うためmanager / floorの代表値、候補数は重複と上限20／超過21、空集合も正常ケース内で検証する。直積や全ロール×条件の展開は行わない。

既存DB role試験と合わせてquery接続の選択・SELECT許可・書込拒否を実LOGINで確認する。DB / Qdrantの詳細・任意SQLをInterfaceへ持ち込まない。

## 残工程

本文の管理ファイル取得とSHA-256照合、chunk復元、embedding / Qdrant、文書version有効化、citation、検索Tool / Agent接続は未実装。生成直前に再確認する呼出し元の接続も後続。AC-R01〜03 / T-R18の完全な受入合格ではない。

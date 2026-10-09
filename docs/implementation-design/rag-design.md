# LineScope RAG / 知識検索設計書

## 1. 責務

Qdrantはマニュアル・保全手順等の非構造文書検索を担当する。Neo4jの構造依存探索とは分離する。

## 2. 正本

KnowledgeDocument metadataはPostgreSQL正本。
文書本文は管理対象ファイルを正本とする。
Qdrantは派生Index。

## 3. Qdrant

VectorDBとしてQdrantを採用する。

## 4. Chunk Metadata

- chunk_id
- document_id
- document_version
- section
- equipment_id optional
- access_class
- content_hash

## 5. 認可

Qdrant filterは前段絞込みに使用するが最終認可根拠にしない。

検索結果document_id/document_versionをPostgreSQL `knowledge_document` のactive/version/access_classで再確認する。

## 6. Ingestion

Document -> Parse -> Chunk -> Embed -> Qdrant Upsert。

新version有効化後、旧versionを検索対象外とする。

## 7. Injection

Retrieved本文はデータ。命令として扱わない。

## 8. version有効化・再構築・再認可

access_classはFACTORY_INTERNALのみで認証済み全ロールに許可。metadataのactive行はdocument_codeごとに最大1件。新本文は不変ファイルへ保存し、hash検証・Parse / Chunk / Embed / Qdrant upsertが完了してから、PostgreSQLの短いTransactionで新version有効化と旧version無効化を行う。document_code単位のlockで有効化を直列化し、古いversionが最新を置き換えないよう検証する。upsert失敗時は旧versionを維持する。

検索後、document_id / document_version / content_hashが正本のactive metadataと一致することを確認し、認証roleで再認可する。生成前に最終再確認し、途中で失効したchunkを除く。chunk本文は正本ファイルとhash確認済みの内容から作り、Qdrant metadataだけを信用しない。chunk IDは(document_id, document_version, chunk ordinal, chunking_version)から決定的に生成する。

再構築は正本active metadataとhash一致の本文をParse / Chunk / Embedして新collectionへupsertし、件数・hash・認可を検証後に切り替える。再構築中のversion変更があれば検証をやり直す。Qdrant不可・認可確認不可ならRAGを停止し、未検索の引用を生成しない。Graphや更新の可否はQdrant状態に依存しない。

citationはdocument_id / document_version / section / chunk_id / source_uriをサーバが根拠として保持する。Toolはretrieve_knowledge(query, equipment_id?, limit?)でitems（認可済みchunkとcitation）を返す。既定limit=5、system最大20。最終認可で全件除外ならitems=[]とし、根拠がないことを明示する。

検索結果のchunk本文はQdrant返却textをそのまま採用せず、hash確認済み正本ファイルを同じchunking_versionで復元・照合して取得する。metadata hash一致だけで改変chunk本文を信頼しない。embedding / chunking versionはIndex metadataとして記録し、変更時はIndexを再構築する。

## 9. 判断支援の文書根拠

安全基準、修理手順、交換資料等は認可・active version・citationを確認して取得する。Retrieved textをそのまま安全許容判定・計算用正本の確定値として採用しない。適用対象・有効期間・承認されたルールや入力との対応が未定義なら参考資料と不足情報を示す。LLMによる抽出だけで費用・能力・安全条件を業務DBへ自動登録しない。正本とIndexの境界、Injection防御、再認可は維持する。

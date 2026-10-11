# Graph一段依存関係の固定読取

仕様正本はdomain-model §4・§15、api-toolsのGraph探索契約、transaction-design §16。本記録は実装判断の履歴。

- 既存Graph read context内で、generation・typed ID・論理方向・as_of・取得limitをbindした固定Cypherを使う。任意Cypher/label/relationship typeを外部入力から作らない。
- 影響方向と上流方向は保存方向から分離する。DEPENDS_ON/USESと他の通常関係の向きを区別し、CAN_SUBSTITUTEは通常探索に含めない。方向表は純粋domain moduleへ局所化する。
- activeな登録node/edgeだけを、effective_from <= as_of < effective_to（NULL終端は無期限）で評価する。required=falseも到達候補には含める。active/requiredから操業可否・AND依存成立・代替能力充足を推論しない。
- node typed ID、source_record_idの辞書順で返す。limit+1件だけ取得し、未返却の追加事実がある場合has_moreを返す。取得件数がちょうどlimitなら未完扱いにしない。これは内部一段取得であり、公開BFSのnodes/paths/completeとは別。
- 保存source/targetと論理neighborを保持し、version・required・endpoint型・UUIDを検証する。破損事実を正常Evidenceとして返さない。既存の単一Neo4j transaction、PG shared lock、終了CURRENT/generation確認を維持する。
- 実PG/Neo4jで全通常Relationの両方向、CAN_SUBSTITUTE除外、期間境界、inactive除外、決定的順序・上限超過、無効limit拒否を確認する。
- 複数段探索、認可、server as_of決定/未来拒否、system limit適用、SPOF/代替の成立評価、Evidence外部契約、API/Tool公開は後続。過去分析を完全point-in-time復元としない。正本文書・DB schemaを変更せず、新しいRaw SQLは追加しない。LogiScopeコードは再利用していない。

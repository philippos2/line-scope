# シナリオ1：A案データ修正と実API再測定

## 指示と範囲

開発依頼者は既存3コミットを維持し、A案データ修正・再測定をUI修正より先のコミットに分離するよう指示した。再測定の報告で停止し、UI修正は別承認を待つ。その後、Draft PR作成とブラウザ確認用プレビューの提供が明示指示された。UIコードは今回変更していない。

## データ変更

scenario1.jsonのR-02→M-208の必須供給1件だけを除去。R-02とR-02→M-204は維持し、設備状態・名称・入力・期間・額・能力などその他の値は変更しない。8beb868とのJSON構造比較でも関係1件以外に差分がないことを確認。

## 実API結果

| 項目 | 結果 |
|---|---|
| M-208登録状態 | RUNNING |
| 候補structure.determination | ESTABLISHED |
| 候補availability | AVAILABLE |
| 比較structural_basis.status | AVAILABLE |
| 比較condition_assessment.structure | AVAILABLE |
| 損害額 | 200000 JPY/hour（P-100 120000・P-200 80000） |
| 能力 | P-100：required_rate 60・available_rate 80・SUFFICIENT |
| 安全・品質 | UNKNOWN・UNKNOWN |
| operational_permission | false |
| P-200 | 今回選択した能力入力では評価していない |

P-200の説明は、下流から返った製品ID集合と、比較selected_inputs.capacity[].input.product_idの集合の差に基づく。not_evaluatedは観点の一覧であり、製品一覧として使わない。

以前の不一致の原因：domain/decision_assessments.pyのstructural_basisは、候補のstructure.determinationではなくcandidate.availabilityをstatusとして返している。以前の記録は構造ESTABLISHED・候補availability UNKNOWN・比較status UNKNOWNで整合している。R-02はv1で運用状態を評価できず、graph_substitute_candidateの必須依存の利用可能性のANDにUNKNOWNが入っていた。A案ではその依存がなくなり、候補・比較ともAVAILABLEになった。判定コード・API契約の変更は不要。

## 環境と保全確認

- 事前報告した検証project：linescope-s1-availability-check-20261019。専用postgres-data・neo4j-data、API8003、Frontendなし。JSON投入→schema→rebuild→実HTTP測定後、同projectのcontainer・volumeを削除。
- 既存tests18件は別project linescope-s1-availability-tests-20261019のtmpfsで実行し、終了後削除。
- 追加指示による継続プレビュー：linescope-s1-availability-preview-20261019。専用postgres-data・neo4j-data、API8003、Frontend5174。私有.env.scenario1-availability-previewを使用し、従来の接続tokenも使えるよう登録済みユーザーを引き継いだ。秘密値はログ・Gitに記録していない。
- localhost:5173のlinescope-scenario1は切替・再作成していない。linescope-browser-demoも同一container IDのまま。linescope-incident-demoは作業開始時点から存在せず、復元もしていない。
- 今回のFrontendとbackend/srcの差分はゼロ。既存シードの追加変更なし。旧projectを対象にした書込・再投入・削除コマンドを実行していない。

## 検証

- Docker内backend/tests/test_demo_file_seed.py：既存18件成功、4.34秒。実API照合1件のassertionを強化し、ケース追加なし。Starlette非推奨警告と終了時logging警告あり。
- 対象Pythonのruff check・format成功。git diff --checkと更新SVGのXML検証成功。
- プレビューにも同じJSONを初期投入・rebuildし、実HTTPで同じAVAILABLE・200000・60/80を再確認。
- 実ブラウザChromiumで名前検索→M-204→図・設備コード・200000・M-208稼働中・能力80→M-208へ切替後の損害額対象外を確認。旧M-208の冷却異常・経済入力は表示されない。selected.png・m208-running.pngを保存し、実画面も確認した。証拠は.git/verification/scenario1-availability配下。
- LLMは専用project内で到達不能URLを指定したまま。共有LLMは停止していない。

## 未完了と停止位置

利用可能性に応じたUI提案の制御、独立した利用可能性の行、安全・品質・残るリスクのサーバ値表示、新UI検証S1-01〜08と禁止語検査は未完了。今回提供した5174番は修正データと既存UIのプレビューであり、UI改修完了ではない。M-204の主軸異常を画面へ表示する追加はしない方針を設計書に反映した。

既存3コミットは書き換えない。Draft・【WIP】を維持し、再測定結果を報告してUIの明示承認を待つ。既存5173番の接続先切替は別途確認を取る。CI完了やmerge可能とは案内しない。

## 後続工程

その後、開発依頼者からUI修正の着手指示を受けた。[UI表示・検証・環境一覧の修正](2026-10-19-ui-availability-and-environments.md)へ続く。「UIコードは今回変更していない」は本記録のデータ再測定工程についての記述で、以後の工程の未着手を意味しない。

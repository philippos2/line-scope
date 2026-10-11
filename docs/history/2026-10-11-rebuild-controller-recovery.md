# Rebuild controllerの残存flag復旧

仕様正本はtransaction-design §11・§17・§20、operations §10。本記録は実装判断の履歴。

- 通常runは残存flagを拒否する契約を維持する。明示的recover入口で、呼出元が取得した新leaderの下、controllerがexclusive mutation lockを取得し、PG control観測→残存ticket取得→pointerがある場合の実Neo4j検証情報取得→resumeによる旧fenceの置換を行う。
- 新ticket取得後は既存のRestore staging、drain、正本Snapshot、fresh generation build/verify、公開手順を共用する。復旧前の観測・再検証にも同じdeadlineを使用する。
- 引継ぎ前に失敗した場合、旧ticketをfailせずflag/fatal/pointer/Outboxを保持する。観測済み旧IDは失敗ログの相関にだけ使用し、状態変更権限の代用にしない。
- 引継ぎ後の失敗は新ticketで失敗保存する。leader喪失・commit後の確認失敗では状態を巻き戻したと推測せず、unknownとして残存flagを次のcontrollerへ渡す。
- NULL pointerは既存の作業用generation生成手順へ進む。non-NULL pointerのGraph欠損・未検証・不正markerは引継ぎ前に拒否し、flagを消さない。DEADは引継ぎ後も通常drainの停止条件を維持する。
- flag解除済みの公開状態をrecoverで再実行しない。pointerに反映されていない検証済み候補を公開済みと推測せず、管理cleanupまで保持する。
- daemon/CLIからの起動、non-NULL pointerのGraph欠損修復、generation cleanup、hard deadlineのI/O伝播は後続。worker runtimeや全復旧ACの完了とは扱わない。

実PG/Neo4jでNULL/staged pointerの接続喪失からdrain・CURRENTまで、未検証pointer拒否、公開済み状態の再実行拒否、未公開候補保持、DEAD、引継ぎ前後のleader喪失、lock timeout、共通期限、引継ぎ後の失敗保存を検証する。正本文書・API・DB schemaを変更せず、LogiScopeコードは再利用しない。

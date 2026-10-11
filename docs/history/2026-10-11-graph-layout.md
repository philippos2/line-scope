# Graph関連コード・テストの配置整理

## 決定と範囲

利用者の指示に従い、まずソースとテストの配置を整理し、その後にRouter / Application / Persistenceの責務分離を改善する。今回はGraph同期関連9モジュールをbackend/src/linescope/graphへ、対応する10テストモジュールをbackend/tests/graphへ移動する第一段階。

Graph内部のimportは同一package、他責務へのimportは親packageへ更新する。呼出側とテストのimport・monkeypatch対象も更新する。pytestのpythonpathにtestsを追加し、graph.test_*で共有fixtureを明示参照する。root conftestの使い捨てDB fixtureを維持する。新規packageの__init__は説明だけとし、旧パスへの互換shimや再exportを増やさない。

core_outboxはPG Persistenceとして現位置に残す。今回のgraph packageは関連機能の配置単位であり、純粋なdomain層やClean Architectureの依存反転を完成したとは扱わない。SQL/Cypher、transaction、lock、状態遷移、権限、API/Tool、fixture数値、テストassertは変更しない。LogiScopeコードは再利用していない。

## 次工程・運用合意

残るコード・テストも影響範囲を限定して段階的に配置整理する。その後、/agentの振り分け、サービス内SQL、ProposalStoreの複数責務を改善する。単体テストは対応する責務単位へ、複数責務をまたぐIntegration/API/Business Scenarioは試験目的に沿って整理する。

READMEと文書群の全面整理はバックエンドが一段落してから行い、それまでは現行仕様の整合維持と重要判断の記録に限定する。

PRはCodexが「CI確認・結果追記・片付けまで完了しました。mergeできます」と報告した後にPOがmergeする。先にmergeされても未完了の確認や片付けを省略しない。mainへのforce-pushや履歴rewriteは行わない。

検証: Docker内全体2,474 passed / 1 skipped / 1 warning（186.85秒）。移動前と同じ件数。ruff check / format成功（150ファイル）。本体55モジュールのASTを比較し、import以外の処理変更がないことも確認した。

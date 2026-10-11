# 残存Rebuild flagのticket引継ぎ

## 今回の境界

transaction-design §17・20、operations §10に従い、新しいleaderが残存flagを引き継ぐ内部部品を追加した。`RebuildControl.resume`は呼出元が保持するleader・排他mutation lock、観測済み旧ticketを要求する。controllerの自動復旧・管理CLIへの接続は次工程とする。

公開pointerが非NULLなら、そのpointerと一致するVerifiedGenerationに加え、実Neo4j adapterの検証情報を確認する。DTOだけで検証済みと扱わない。NULLの場合は未公開として扱い、別generationの証明を持ち込まない。

既存のCore制御モジュールへ条件付きUPDATEを追加した。controlのflag=true、旧rebuild_id、旧pointerを照合し、新しいrebuild_idと更新時刻だけを一つの短いtransactionで変更する。Graph確認の前後とcommit直前にleader / lockを確認し、commit後にleaderを再確認する。再接続・自動retryは追加しない。

flag、fatal_error、active_generation、Outboxのstatus / attempt / payloadは維持する。旧ticketのheartbeat、failure、再引継ぎ、drain claimは拒否される。DEADも消さない。引継ぎだけでは正常公開やCURRENTにしない。

## 確定性と責務

DB更新失敗は旧ticketのままrollbackする。commit後のleader喪失は確定済み新ticketを巻き戻さず、呼出元へ例外を伝える。未検証generationや旧公開generationの削除は行わない。新しいownerは後続の復旧処理を行い、最終検証・公開前にflag / fatalを消してはならない。

新規Raw SQL、DB schema、API / Tool、業務更新・Approvalの変更はない。既存のApplicationによるtransaction所有権・lock順を維持する。LogiScopeコードは再利用していない。

## 検証と残件

既存control試験17件、追加途中のrecovery / control / staging試験43件がDockerで成功。追加試験は実PG/Neo4jで、全Outbox状態の保存、旧leaderの接続終了後の引継ぎ、旧ticket拒否、実Graph検証、未検証marker拒否、ID / pointer / flag競合、共有lock・無lock拒否、Graph確認中のlock喪失、DB更新失敗rollback、実commit後のleader喪失を検証する。最終Graph回帰・lint・CIの実測結果はPR本文へ記録する。

T-R12の残存flag復旧境界（AC-G15〜17）に対応するが、controller接続と切替前後の全crash復旧が完了したものではない。観測用control読込、marker情報取得、自動復旧の組立、非NULL pointer先のGraph欠損対応、runtime / CLI / 権限と全I/O期限伝播は残件。引継ぎ結果と復旧完了を混同しない。

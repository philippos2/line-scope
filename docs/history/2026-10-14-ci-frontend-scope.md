# Frontend変更時のCI負荷と検証方針

非正本の判断記録。

- 開発者はFrontendのみの変更でBackend全件CIを省略することを希望した。
- Frontendのテストは必要最小限、省略も許容するとの指示を受けた。通常CIはlint・型・format・buildに限定し、既存テストは任意実行用に維持する。業務・安全性に関するBackend検証を弱める指示ではない。
- PR #233ではFrontend専用pathだけBackendを省略し、未知のpath／CI／共通設定／判定不能時は実行する。集約checkは対象外skipだけ許容する。
- 14件の判定・集約テストと実Git差分3条件を検証した。Frontendテスト追加は0件。
- merge後、Frontend専用変更のPRでGitHub上のskipと集約成功を確認する。
- 運用文書の変更はコードPRへ混在させず、別PR用に退避する。

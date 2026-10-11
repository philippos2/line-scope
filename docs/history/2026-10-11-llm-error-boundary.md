# LLM adapterの例外境界

## 判断

`integrations/llm.py` の `LLMError` はApplicationの `ToolError` を継承していた。LLM接続が業務Toolの例外体系を直接知る依存を解消するため、独立した例外とし、Read Agentが `ToolError` に変換する。

providerの応答検証・通信・deadlineはadapterが担当し、Agent側が既存の公開error code / messageへ接続する。HTTP statusとresponse envelopeの変換はInterfaceに残す。診断用のexception chainは内部で保持し、provider bodyや内部情報をレスポンスへ追加しない。

## 検証と範囲

接続障害、budget超過、不正応答の3分類についてAgentの変換を直接試験し、API試験のprovider doubleも独立例外を投げる形に合わせる。既存adapter試験で通信・応答検証を維持する。AC-14の失敗報告に対応する部分試験であり、受入基準全体の完了を意味しない。

DB・Approval / Execute・Outbox・Graph・Tool schema・LLM promptは変更しない。全面的な依存反転やprovider共通frameworkは導入せず、今回必要な例外境界に限定する。

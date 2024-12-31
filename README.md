# I'm Noob🤡

# Works MQTT WebSocket Client

LINE Works MobileのMQTT
WebSocketを模倣し、通信を受け取るPythonクライアントの開発用リポジトリです。
認証にはCookieを使用します。

> **Note**:
> Cookieは、ブラウザの開発者ツール(F12)でメッセージ送信時(sendMessage)などの通信を確認し、そこで使用されているものを利用してください。

> **Note**: WMQTTの仕様により、同一メッセージが複数回帰ってくる場合があります。
> メッセージの重複を防ぐための工夫として、以下のIDをキーとして使用できます:
>
> - `notification-id`: 通知メッセージのユニークID
>   例:`msg.AAAAAAAAAABThVMSAAAAAJ4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`

## TODO

- メッセージタイプの定義の拡張
- AWAYなどの項目の詳細調査
- アップデートに伴う構造変更への対応

## 機能

- WebSocket経由でのMQTT接続
- Works通信の受信
- 自動再接続機能
- キープアライブ（PING送信）
- エラーハンドリング
- 詳細なログ出力

## 必要条件

- Python 3.11以上
- websockets
- rich

## 構造

[STRUCTURE.md](STRUCTURE.md)

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

# Works MQTT WebSocket Client

Works MobileのMQTTサービスに接続するためのPythonクライアントライブラリです。
WebSocketを介してリアルタイムメッセージングを実現します。

## 機能

- WebSocket経由でのMQTT接続
- メッセージの送受信
- 自動再接続
- キープアライブ処理
- エラーハンドリング
- リッチなログ出力

## 必要条件

- Python 3.11以上
- websockets
- rich

## インストール

```bash
pip install -r requirements.txt
```

## 使用方法

1. `cookie.json`を作成し、Works Mobileの認証情報を設定します：

```json
{
    "WORKS_COOKIE_NAME": "WORKS_COOKIE_VALUE"
}
```

2. クライアントを実行：

```python
from wmqtt import WMQTTClient

async def main():
    client = WMQTTClient()
    await client.start()

if __name__ == "__main__":
    asyncio.run(main())
```

## セキュリティ

- `cookie.json`は`.gitignore`に含まれており、リポジトリにはコミットされません
- すべての通信はSSL/TLSで暗号化されます

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

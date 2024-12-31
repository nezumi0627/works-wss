"""Works Mobile constants and configurations.

Works Mobileの定数と設定値を定義するモジュール。

含まれる定数:
- WebSocket接続設定
- MQTTプロトコル設定
- メッセージフィールド定義
- スタンプフィールド定義
- ログ設定
- コンソール表示設定
- ユーザーステータス定義
"""

from enum import IntEnum
from typing import Dict, Final

# WebSocket設定
WS_URL: Final[str] = "wss://jp1-web-noti.worksmobile.com/wmqtt"
WS_ORIGIN: Final[str] = "https://talk.worksmobile.com"
WS_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
WS_SUBPROTOCOL: Final[str] = "mqtt"


# MQTT設定
MQTT_PROTOCOL_VERSION: Final[int] = 4
MQTT_KEEP_ALIVE: Final[int] = 50
MQTT_PING_INTERVAL: Final[int] = 30
MQTT_PING_TIMEOUT: Final[int] = 10
MQTT_RETRY_INTERVAL: Final[int] = 5
MQTT_MAX_RETRIES: Final[int] = 3


class MessageFields:
    """メッセージ関連のフィールド名定義.

    Attributes:
        COMMAND: コマンドフィールド
        CHANNEL_ID: チャンネルIDフィールド
        BODY: メッセージ本文フィールド
        MESSAGE_ID: メッセージIDフィールド
        SENDER_ID: 送信者IDフィールド
        TIMESTAMP: タイムスタンプフィールド
        NOTIFICATION_TYPE: 通知種別フィールド
        CHANNEL_NO: チャンネル番号フィールド
        MESSAGE_NO: メッセージ番号フィールド
        FROM_USER_NO: 送信元ユーザー番号フィールド
        CREATE_TIME: 作成時刻フィールド
    """

    COMMAND: Final[str] = "command"
    CHANNEL_ID: Final[str] = "channelId"
    BODY: Final[str] = "body"
    MESSAGE_ID: Final[str] = "messageId"
    SENDER_ID: Final[str] = "senderId"
    TIMESTAMP: Final[str] = "timestamp"
    NOTIFICATION_TYPE: Final[str] = "nType"
    CHANNEL_NO: Final[str] = "chNo"
    MESSAGE_NO: Final[str] = "messageNo"
    FROM_USER_NO: Final[str] = "fromUserNo"
    CREATE_TIME: Final[str] = "createTime"


class StickerFields:
    """スタンプ関連のフィールド名定義.

    Attributes:
        TYPE: スタンプ種別フィールド
        PACKAGE_ID: パッケージIDフィールド
        STICKER_ID: スタンプIDフィールド
        OPTION: オプションフィールド
    """

    TYPE: Final[str] = "stkType"
    PACKAGE_ID: Final[str] = "pkgId"
    STICKER_ID: Final[str] = "stkId"
    OPTION: Final[str] = "stkOpt"


# ログとコンソール設定
LOG_FORMAT: Final[str] = "%(message)s"

CONSOLE_THEME: Final[Dict[str, str]] = {
    "info": "blue",
    "warning": "yellow",
    "error": "red",
    "debug": "dim white",
    "success": "green",
    "header": "magenta",
}


class StatusFlag(IntEnum):
    """WebSocket接続状態フラグ.

    WebSocketの現在の接続状態を表します。

    Attributes:
        DISCONNECTED: 未接続状態
        CONNECTING: 接続試行中
        CONNECTED: 接続完了
    """

    DISCONNECTED = 0  # 未接続状態
    CONNECTING = 1  # 接続試行中
    CONNECTED = 2  # 接続完了

    @classmethod
    def get_name(cls, value: int) -> str:
        """接続状態の名前を取得します.

        Args:
            value: 接続状態の値

        Returns:
            str: Human readable status name
        """
        try:
            name_map = {
                int(cls.DISCONNECTED): "Disconnected",
                int(cls.CONNECTING): "Connecting",
                int(cls.CONNECTED): "Connected",
            }
            return name_map.get(value, f"Unknown({value})")
        except ValueError:
            return f"Unknown({value})"

"""Constants definitions.

定数定義を提供するモジュール。
"""

from enum import IntEnum, unique
from typing import Final


@unique
class StatusFlag(IntEnum):
    """接続状態を表す列挙型.

    Attributes:
        DISCONNECTED (0): 未接続
        CONNECTING (1): 接続中
        CONNECTED (2): 接続済み
    """

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


# WebSocket設定
WS_URL: Final[str] = "wss://jp1-web-noti.worksmobile.com/wmqtt"
WS_ORIGIN: Final[str] = "https://talk.worksmobile.com"
WS_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
WS_SUBPROTOCOL: Final[str] = "mqtt"

# MQTT設定
MQTT_PROTOCOL_VERSION: Final[int] = 4
MQTT_KEEP_ALIVE: Final[int] = 50
MQTT_PING_INTERVAL: Final[int] = 30
MQTT_PING_TIMEOUT: Final[int] = 10
MQTT_RETRY_INTERVAL: Final[int] = 5
MQTT_MAX_RETRIES: Final[int] = 3

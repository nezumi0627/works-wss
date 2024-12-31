"""Core functionality.

コアとなる機能を提供するパッケージ。

以下の機能を提供します:
- ロギング機能
- 定数定義
- 例外クラス
"""

from .constants import (
    MQTT_KEEP_ALIVE,
    MQTT_MAX_RETRIES,
    MQTT_PING_INTERVAL,
    MQTT_PING_TIMEOUT,
    MQTT_PROTOCOL_VERSION,
    MQTT_RETRY_INTERVAL,
    WS_ORIGIN,
    WS_SUBPROTOCOL,
    WS_URL,
    WS_USER_AGENT,
    StatusFlag,
)
from .exceptions import (
    ERROR_MESSAGES,
    AuthenticationError,
    ConfigError,
    ConnectionError,
    CookieError,
    MessageError,
    PacketError,
    WorksError,
)
from .logging import log_error, log_packet, logger

__all__ = [
    # ロギング関連
    "logger",
    "log_packet",
    "log_error",
    # 定数関連
    "StatusFlag",
    "MQTT_PROTOCOL_VERSION",
    "MQTT_KEEP_ALIVE",
    "MQTT_PING_INTERVAL",
    "MQTT_PING_TIMEOUT",
    "MQTT_RETRY_INTERVAL",
    "MQTT_MAX_RETRIES",
    "WS_URL",
    "WS_ORIGIN",
    "WS_USER_AGENT",
    "WS_SUBPROTOCOL",
    # 例外クラス
    "WorksError",
    "ConfigError",
    "ConnectionError",
    "AuthenticationError",
    "MessageError",
    "PacketError",
    "CookieError",
    "ERROR_MESSAGES",
]

"""Works Mobile custom exceptions.

Works Mobile固有のエラーを定義するモジュール
"""


class WorksError(Exception):
    """Works Mobile関連の基本例外クラス."""

    pass


class ConfigError(WorksError):
    """設定関連のエラー."""

    pass


class ConnectionError(WorksError):
    """接続関連のエラー."""

    pass


class AuthenticationError(WorksError):
    """認証関連のエラー."""

    pass


class MessageError(WorksError):
    """メッセージ処理関連のエラー."""

    pass


class PacketError(WorksError):
    """MQTTパケット関連のエラー."""

    pass


class CookieError(WorksError):
    """クッキー関連のエラー."""

    pass


# エラーメッセージの定義
ERROR_MESSAGES = {
    # 設定関連
    "CONFIG_FILE_NOT_FOUND": "Config file not found: {path}",
    "INVALID_CONFIG_FORMAT": "Invalid config format: {path}",
    "MISSING_REQUIRED_CONFIG": "Missing required config: {field}",
    # 接続関連
    "CONNECTION_FAILED": "Connection failed: {reason}",
    "CONNECTION_TIMEOUT": "Connection timeout",
    "CONNECTION_CLOSED": "Connection closed: code={code}, reason={reason}",
    "MAX_RETRIES_EXCEEDED": "Max retries exceeded",
    # 認証関連
    "COOKIE_FILE_NOT_FOUND": "cookie.json not found",
    "INVALID_COOKIE_FORMAT": "Invalid cookie.json format",
    "AUTHENTICATION_FAILED": "Authentication failed: {reason}",
    # メッセージ関連
    "INVALID_MESSAGE_FORMAT": "Invalid message format: {detail}",
    "MISSING_REQUIRED_FIELD": "Missing required field: {field}",
    "MESSAGE_PARSE_ERROR": "Message parse error: {detail}",
    # パケット関連
    "INVALID_PACKET_FORMAT": "Invalid packet format: {detail}",
    "PACKET_TOO_SHORT": "Packet too short",
    "MALFORMED_LENGTH": "Malformed length field",
    "PACKET_PARSE_ERROR": "Packet parse error: {detail}",
    # その他
    "UNEXPECTED_ERROR": "Unexpected error: {detail}",
}

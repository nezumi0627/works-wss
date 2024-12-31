"""Exception definitions.

例外定義を提供するモジュール。

このモジュールはWorks Mobile APIで使用される例外クラスと
エラーメッセージの定義を提供します。
"""

from typing import Dict


class WorksError(Exception):
    """Works Mobile関連の基本例外クラス.

    全てのWorks Mobile関連の例外の基底クラスとして機能します。
    """


class ConfigError(WorksError):
    """設定関連のエラー.

    設定ファイルの読み込みや解析時に発生するエラーを表します。
    """


class ConnectionError(WorksError):
    """接続関連のエラー.

    ネットワーク接続やAPI通信時に発生するエラーを表します。
    """


class AuthenticationError(WorksError):
    """認証関連のエラー.

    認証情報の検証や認証プロセスで発生するエラーを表します。
    """


class MessageError(WorksError):
    """メッセージ処理のエラー.

    メッセージの送受信や処理時に発生するエラーを表します。
    """


class PacketError(WorksError):
    """パケット処理のエラー.

    データパケットの解析や処理時に発生するエラーを表します。
    """


class CookieError(WorksError):
    """クッキー関連のエラー.

    クッキーの読み書きや管理時に発生するエラーを表します。
    """


# エラーメッセージ定義
ERROR_MESSAGES: Dict[str, str] = {
    "COOKIE_FILE_NOT_FOUND": "クッキーファイルが見つかりません: {detail}",
    "INVALID_COOKIE_FORMAT": "クッキーファイルの形式が不正です: {detail}",
    "CONNECTION_FAILED": "接続に失敗しました: {reason}",
    "AUTHENTICATION_FAILED": "認証に失敗しました: {reason}",
    "MAX_RETRIES_EXCEEDED": "最大再試行回数を超えました",
    "PACKET_PARSE_ERROR": "パケットの解析に失敗しました: {detail}",
    "MESSAGE_PARSE_ERROR": "メッセージの解析に失敗しました: {detail}",
    "INVALID_MESSAGE_FORMAT": "不正なメッセージ形式です: {detail}",
    "UNEXPECTED_ERROR": "予期せぬエラーが発生しました: {detail}",
}

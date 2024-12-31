"""Works Mobile message type definitions.

メッセージタイプの定義と名前のマッピング
"""

from enum import IntEnum, unique


@unique
class ChannelType(IntEnum):
    """チャンネルの種類を定義する列挙型.

    Attributes:
        PERSONAL (6): 個人チャット
        GROUP (10): グループチャット
    """

    PERSONAL = 6  # 個人チャット
    GROUP = 10  # グループチャット


@unique
class MessageType(IntEnum):
    """メッセージタイプの定義.

    Attributes:
        NORMAL (101): テキスト
        AWAY (102): 不在(未解析)
        LEAVE (202): チャンネルからの退出通知
        INVITE (203): 新規メンバーの招待通知
        KICK (204): メンバーのキック通知
        CMD_READ (93004): 既読
        NOTIFICATION_MESSAGE (1): テキスト
        NOTIFICATION_STICKER (18): スタンプ
        NOTIFICATION_FILE (16): ファイル
        NOTIFICATION_SERVICE (100): システム
        NOTIFICATION_EMOJI (27): 絵文字
        NOTIFICATION_IMAGE (11): 画像
        NOTIFICATION_BADGE (41): バッジ更新(未解析)
    """

    # チャンネルメッセージタイプ
    NORMAL = 101
    AWAY = 102  # TODO: AWAYが何を指しているのか特定
    LEAVE = 202
    INVITE = 203
    KICK = 204

    # コマンドメッセージタイプ
    CMD_READ = 93004

    # 通知メッセージタイプ
    NOTIFICATION_MESSAGE = 1
    NOTIFICATION_STICKER = 18
    NOTIFICATION_FILE = 16
    NOTIFICATION_SERVICE = 100
    NOTIFICATION_EMOJI = 27
    NOTIFICATION_IMAGE = 11
    NOTIFICATION_BADGE = 41  # TODO: バッジ更新が何を指しているのか特定


# メッセージタイプと表示名の対応マップ
MESSAGE_TYPE_NAMES: dict[int, str] = {
    # チャンネルメッセージ
    MessageType.NORMAL: "テキスト",
    MessageType.AWAY: "不在(未解析)",
    MessageType.LEAVE: "退出",
    MessageType.INVITE: "招待",
    MessageType.KICK: "削除",
    # コマンドメッセージ
    MessageType.CMD_READ: "既読",
    # 通知メッセージ
    MessageType.NOTIFICATION_MESSAGE: "テキスト",
    MessageType.NOTIFICATION_STICKER: "スタンプ",
    MessageType.NOTIFICATION_FILE: "ファイル",
    MessageType.NOTIFICATION_SERVICE: "システム",
    MessageType.NOTIFICATION_EMOJI: "絵文字",
    MessageType.NOTIFICATION_IMAGE: "画像",
    MessageType.NOTIFICATION_BADGE: "バッジ更新(未解析)",
}


# チャンネルタイプと表示名の対応マップ
CHANNEL_TYPE_NAMES: dict[int, str] = {
    ChannelType.PERSONAL: "個人チャット",
    ChannelType.GROUP: "グループチャット",
}


def get_message_type_name(value: int) -> str:
    """メッセージタイプの数値から表示名を取得します.

    Args:
        value: メッセージタイプの数値

    Returns:
        str: Message type display name
    """
    return MESSAGE_TYPE_NAMES.get(value, f"不明({value})")


def get_channel_type_name(value: int) -> str:
    """チャンネルタイプの数値から表示名を取得します.

    Args:
        value: チャンネルタイプの数値

    Returns:
        str: Channel type display name
    """
    return CHANNEL_TYPE_NAMES.get(value, f"不明({value})")

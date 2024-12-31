"""Works Mobile message types.

メッセージタイプの定義を提供するモジュール。
"""

import logging
from dataclasses import dataclass
from enum import Enum, IntEnum, unique
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
        NORMAL (101): テキストメッセージ
        AWAY (102): 不在メッセージ(未解析)
        LEAVE (202): チャンネルからの退出通知
        INVITE (203): 新規メンバーの招待通知
        KICK (204): メンバーのキック通知
        CMD_READ (93004): 既読通知
        NOTIFICATION_MESSAGE (1): テキスト通知
        NOTIFICATION_STICKER (18): スタンプ通知
        NOTIFICATION_FILE (16): ファイル通知
        NOTIFICATION_SERVICE (100): システム通知
        NOTIFICATION_EMOJI (27): 絵文字通知
        NOTIFICATION_IMAGE (11): 画像通知
        NOTIFICATION_BADGE (41): バッジ更新通知(未解析)
    """

    # チャンネルメッセージタイプ
    NORMAL = 101
    AWAY = 102  # TODO: 不在メッセージの詳細仕様を確認
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
    NOTIFICATION_BADGE = 41  # TODO: バッジ更新通知の詳細仕様を確認


# メッセージタイプと表示名の対応マップ
MESSAGE_TYPE_NAMES: dict[int, str] = {
    # チャンネルメッセージ
    MessageType.NORMAL: "テキストメッセージ",
    MessageType.AWAY: "不在メッセージ(未解析)",
    MessageType.LEAVE: "チャンネル退出",
    MessageType.INVITE: "メンバー招待",
    MessageType.KICK: "メンバー削除",
    # コマンドメッセージ
    MessageType.CMD_READ: "既読通知",
    # 通知メッセージ
    MessageType.NOTIFICATION_MESSAGE: "テキスト通知",
    MessageType.NOTIFICATION_STICKER: "スタンプ通知",
    MessageType.NOTIFICATION_FILE: "ファイル通知",
    MessageType.NOTIFICATION_SERVICE: "システム通知",
    MessageType.NOTIFICATION_EMOJI: "絵文字通知",
    MessageType.NOTIFICATION_IMAGE: "画像通知",
    MessageType.NOTIFICATION_BADGE: "バッジ更新通知(未解析)",
}


# チャンネルタイプと表示名の対応マップ
CHANNEL_TYPE_NAMES: dict[int, str] = {
    ChannelType.PERSONAL: "個人チャット",
    ChannelType.GROUP: "グループチャット",
}


def get_message_type_name(value: int) -> str:
    """メッセージタイプの数値から表示名を取得します.

    Args:
        value (int): メッセージタイプの数値

    Returns:
        str: メッセージタイプの表示名
    """
    return MESSAGE_TYPE_NAMES.get(value, f"不明なメッセージタイプ({value})")


def get_channel_type_name(value: int) -> str:
    """チャンネルタイプの数値から表示名を取得します.

    Args:
        value (int): チャンネルタイプの数値

    Returns:
        str: チャンネルタイプの表示名
    """
    return CHANNEL_TYPE_NAMES.get(value, f"不明なチャンネルタイプ({value})")


class StickerType(str, Enum):
    """スタンプの種類を表す列挙型."""

    NONE = "none"
    LINE = "line"
    WORKS = "works"


@dataclass
class StickerInfo:
    """スタンプ情報を表すデータクラス.

    Attributes:
        sticker_type (StickerType): スタンプの種類
        package_id (str): パッケージID
        sticker_id (str): スタンプID
        options (Optional[str]): オプション情報
    """

    sticker_type: StickerType
    package_id: str
    sticker_id: str
    options: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StickerInfo":
        """辞書からStickerInfoを生成します.

        Args:
            data: スタンプ情報を含む辞書

        Returns:
            StickerInfo: 生成されたスタンプ情報オブジェクト

        Raises:
            ValueError: 不正なスタンプ情報の場合
        """
        try:
            sticker_type = data.get("stkType", "").lower()
            if not sticker_type:
                sticker_type = "none"

            return cls(
                sticker_type=StickerType(sticker_type),
                package_id=str(data.get("pkgId", "")),
                sticker_id=str(data.get("stkId", "")),
                options=data.get("stkOpt"),
            )
        except (ValueError, KeyError) as e:
            logger.error(f"スタンプ情報の解析に失敗しました: {e}")
            return cls(
                sticker_type=StickerType.NONE,
                package_id=str(data.get("pkgId", "")),
                sticker_id=str(data.get("stkId", "")),
                options=data.get("stkOpt"),
            )

    def to_dict(self) -> dict[str, Any]:
        """StickerInfoをJSON互換の辞書に変換します.

        Returns:
            dict[str, Any]: スタンプ情報の辞書表現
        """
        result = {
            "stkType": self.sticker_type.value,
            "pkgId": self.package_id,
            "stkId": self.sticker_id,
        }
        if self.options:
            result["stkOpt"] = self.options
        return result

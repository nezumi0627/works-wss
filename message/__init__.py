"""Message handling.

メッセージ処理を提供するパッケージ。

このパッケージは、メッセージの処理に関する機能を提供します。
主にメッセージの解析、スタンプ情報の処理、チャンネルとメッセージの型定義を含みます。
"""

# メッセージモデル
from .models import WorksMessage

# メッセージ解析
from .parser import parse_message

# 型定義
from .types import (
    ChannelType,
    MessageType,
    StickerInfo,
    StickerType,
    get_channel_type_name,
    get_message_type_name,
)

__all__ = [
    # メッセージ
    "WorksMessage",
    "parse_message",
    # スタンプ
    "StickerInfo",
    "StickerType",
    # 型定義
    "MessageType",
    "ChannelType",
    "get_channel_type_name",
    "get_message_type_name",
]

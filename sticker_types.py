"""Works Mobileのスタンプ関連の型定義.

LINEスタンプやWorksオリジナルスタンプの情報を扱うためのデータ型
"""

from dataclasses import dataclass
from enum import Enum, unique
from typing import Optional

from constants import StickerFields


@unique
class StickerType(str, Enum):
    """スタンプの種類.

    LINE: LINEスタンプ
    WORKS: Worksオリジナルスタンプ
    """

    LINE = "line"
    WORKS = "works"


@dataclass(frozen=True)
class StickerInfo:
    """スタンプの詳細情報.

    スタンプの種類、パッケージID、スタンプIDなどの情報を保持します。
    データの不変性を保証するためfrozen=Trueを指定しています。

    Attributes:
        sticker_type: スタンプの種類(LINE/Works)
        package_id: スタンプのパッケージID
        sticker_id: スタンプID
        options: アニメーションなどのオプション設定
    """

    sticker_type: StickerType
    package_id: str
    sticker_id: str
    options: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "StickerInfo":
        """辞書形式のデータからStickerInfoオブジェクトを生成.

        Args:
            data: スタンプ情報を含む辞書データ

        Returns:
            生成されたStickerInfoオブジェクト

        Raises:
            ValueError: 必須フィールドが不足している場合
            ValueError: スタンプタイプが不正な場合
        """
        required_fields = {
            StickerFields.TYPE,
            StickerFields.PACKAGE_ID,
            StickerFields.STICKER_ID,
        }

        missing_fields = required_fields - data.keys()
        if missing_fields:
            raise ValueError(
                f"Missing required fields: {', '.join(missing_fields)}"
            )

        return cls(
            sticker_type=StickerType(data[StickerFields.TYPE]),
            package_id=data[StickerFields.PACKAGE_ID],
            sticker_id=data[StickerFields.STICKER_ID],
            options=data.get(StickerFields.OPTION),
        )

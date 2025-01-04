"""Message models.

メッセージモデルを提供するモジュール。
"""

from dataclasses import dataclass
from typing import Any, ClassVar, Dict

from .types import MessageType


@dataclass
class WorksMessage:
    """Works Mobileメッセージを表現するデータクラス.

    Attributes:
        command (MessageType): メッセージコマンド
        channel_id (str): チャンネルID
        body (Dict[str, Any]): メッセージ本文
    """

    command: MessageType
    channel_id: str
    body: Dict[str, Any]

    # 必須フィールドの定義
    REQUIRED_FIELDS: ClassVar[Dict[str, str]] = {
        "cmd": "command",
        "cid": "channel_id",
        "bdy": "body",
    }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorksMessage":
        """辞書からWorkMessageインスタンスを生成する.

        Args:
            data (Dict[str, Any]): メッセージデータの辞書

        Returns:
            WorksMessage: 生成されたインスタンス

        Raises:
            ValueError: 必須フィールドが存在しない場合
        """
        if "relayDataList" in data:
            relay_data = data["relayDataList"][0]
            cmd = relay_data.get("cmd")
            if cmd is None:
                raise ValueError("Missing cmd in relay data")

            msg_type = None
            body = relay_data.get("bdy", {})
            if "msgTypeCode" in body:
                msg_type = MessageType(body["msgTypeCode"])
            else:
                msg_type = MessageType(cmd)

            return cls(
                command=msg_type,
                channel_id=str(relay_data.get("cid", "")),
                body=body,
            )

        missing_fields = [
            key for key in cls.REQUIRED_FIELDS if key not in data
        ]
        if missing_fields:
            raise ValueError(
                f"Missing required fields: {', '.join(missing_fields)}"
            )

        return cls(
            **{
                cls.REQUIRED_FIELDS[key]: data[key]
                for key in cls.REQUIRED_FIELDS
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        """WorksMessageをJSON互換の辞書に変換する.

        Returns:
            Dict[str, Any]: メッセージの辞書表現
        """
        return {
            key: getattr(self, attr_name)
            for key, attr_name in self.REQUIRED_FIELDS.items()
        }

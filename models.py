"""メッセージの構造をデータモデルとして整形するモジュール."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from constants import MessageFields


@dataclass
class WorksMessage:
    """Worksメッセージを表現するデータクラス.

    メッセージの基本情報とメタデータを保持し、辞書形式との相互変換を提供します。

    Attributes:
        command (int): メッセージコマンド
        channel_id (str): チャンネルID
        body (Dict[str, Any]): メッセージ本文
        message_id (Optional[str]): メッセージID
        sender_id (Optional[str]): 送信者ID
        timestamp (Optional[int]): タイムスタンプ
    """

    command: int
    channel_id: str
    body: Dict[str, Any]
    message_id: Optional[str] = None
    sender_id: Optional[str] = None
    timestamp: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorksMessage":
        """辞書からWorkMessageインスタンスを生成する.

        Args:
            data (Dict[str, Any]): メッセージデータを含む辞書

        Returns:
            WorksMessage: 生成されたインスタンス

        Raises:
            ValueError: 必須フィールドが欠けている、または不正なデータ形式
        """
        if not isinstance(data, dict):
            raise ValueError(
                "Invalid message format: data must be a dictionary"
            )

        # 通知メッセージの場合の変換
        if MessageFields.NOTIFICATION_TYPE in data:
            return cls(
                command=data.get(MessageFields.NOTIFICATION_TYPE, 0),
                channel_id=str(data.get(MessageFields.CHANNEL_NO, "")),
                body=data,
                message_id=str(data.get(MessageFields.MESSAGE_NO))
                if MessageFields.MESSAGE_NO in data
                else None,
                sender_id=str(data.get(MessageFields.FROM_USER_NO))
                if MessageFields.FROM_USER_NO in data
                else None,
                timestamp=int(data.get(MessageFields.CREATE_TIME, 0)),
            )

        # 通常のメッセージの場合の検証
        required_fields = [
            MessageFields.COMMAND,
            MessageFields.CHANNEL_ID,
            MessageFields.BODY,
        ]
        missing_fields = [
            field for field in required_fields if field not in data
        ]
        if missing_fields:
            raise ValueError(
                f"Missing required fields: {', '.join(missing_fields)}"
            )

        return cls(
            command=int(data[MessageFields.COMMAND]),
            channel_id=str(data[MessageFields.CHANNEL_ID]),
            body=data[MessageFields.BODY],
            message_id=str(data.get(MessageFields.MESSAGE_ID))
            if MessageFields.MESSAGE_ID in data
            else None,
            sender_id=str(data.get(MessageFields.SENDER_ID))
            if MessageFields.SENDER_ID in data
            else None,
            timestamp=int(data[MessageFields.TIMESTAMP])
            if MessageFields.TIMESTAMP in data
            else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        """メッセージを辞書形式に変換する.

        Returns:
            Dict[str, Any]: メッセージデータを含む辞書
        """
        result = {
            MessageFields.COMMAND: self.command,
            MessageFields.CHANNEL_ID: self.channel_id,
            MessageFields.BODY: self.body,
        }

        # オプションフィールドを追加
        optional_fields = {
            MessageFields.MESSAGE_ID: self.message_id,
            MessageFields.SENDER_ID: self.sender_id,
            MessageFields.TIMESTAMP: self.timestamp,
        }
        result.update(
            {
                key: value
                for key, value in optional_fields.items()
                if value is not None
            }
        )

        return result

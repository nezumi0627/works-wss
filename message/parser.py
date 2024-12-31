"""Message parser.

メッセージパーサーを提供するモジュール。
"""

import json
from typing import Any, Dict, Optional

from core import log_error, logger

from .models import WorksMessage
from .types import MessageType, StickerInfo


def parse_message(data: bytes) -> Optional[WorksMessage]:
    """バイナリデータからWorksMessageを生成する.

    Args:
        data (bytes): メッセージのバイナリデータ

    Returns:
        Optional[WorksMessage]: 生成されたWorksMessageインスタンス。
            パース失敗時はNone

    Note:
        JSONデコードエラーやフォーマットエラーが発生した場合はNoneを返します。
    """
    try:
        json_data = json.loads(data.decode("utf-8"))
        logger.debug(f"Received message: {json_data}")

        return (
            _parse_notification(json_data)
            if "nType" in json_data
            else WorksMessage.from_dict(json_data)
        )

    except json.JSONDecodeError as e:
        log_error("MESSAGE_PARSE_ERROR", {"detail": f"JSON decode error: {e}"})
        return None
    except ValueError as e:
        log_error("INVALID_MESSAGE_FORMAT", {"detail": str(e)})
        return None
    except Exception as e:
        log_error("UNEXPECTED_ERROR", {"detail": f"Message parse error: {e}"})
        return None


def _parse_notification(data: Dict[str, Any]) -> WorksMessage:
    """通知メッセージを解析する.

    Args:
        data (Dict[str, Any]): 通知メッセージのデータ

    Returns:
        WorksMessage: 生成されたWorkMessageインスタンス

    Raises:
        ValueError: 必須フィールドが存在しない場合

    Note:
        nTypeとchNoは必須フィールドです。
    """
    required_fields = {"nType", "chNo"}
    if not required_fields.issubset(data.keys()):
        raise ValueError("Missing required fields in notification data")

    msg_type = MessageType(data["nType"])
    body: Dict[str, Any] = {}

    if msg_type == MessageType.NOTIFICATION_STICKER and "stkInfo" in data:
        sticker = StickerInfo.from_dict(data["stkInfo"])
        body = sticker.to_dict()
    else:
        body = data

    return WorksMessage(
        command=msg_type,
        channel_id=str(data["chNo"]),
        body=body,
    )

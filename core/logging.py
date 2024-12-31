"""Logging configuration.

ロギング設定を提供するモジュール。
主な機能:
- ファイルとコンソールへのログ出力
- MQTTパケットのログ記録
- エラー情報のログ記録
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

from rich.console import Console
from rich.logging import RichHandler

# ログ設定
LOG_CONFIG = {
    "file": Path("works_mqtt.log"),
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "level": logging.DEBUG,
}


def setup_logger() -> logging.Logger:
    """ロガーの初期設定を行う.

    Returns:
        logging.Logger: 設定済みのロガーインスタンス
    """
    logger = logging.getLogger("works_mqtt")
    logger.setLevel(LOG_CONFIG["level"])

    # ファイルハンドラーの設定
    file_handler = logging.FileHandler(LOG_CONFIG["file"], encoding="utf-8")
    file_handler.setLevel(LOG_CONFIG["level"])
    file_handler.setFormatter(logging.Formatter(LOG_CONFIG["format"]))
    logger.addHandler(file_handler)

    # コンソールハンドラーの設定
    console = Console(color_system="auto")
    console_handler = RichHandler(
        console=console,
        show_time=False,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setLevel(LOG_CONFIG["level"])
    logger.addHandler(console_handler)

    # 標準出力のリダイレクト
    sys.stdout = console.file
    sys.stderr = console.file

    return logger


# ロガーのグローバルインスタンス
logger = setup_logger()


def log_packet(
    packet_type: str,
    packet_data: Union[bytes, Dict[str, Any]],
    direction: str = ">>",
    level: int = logging.DEBUG,
) -> None:
    """MQTTパケットをログに記録する.

    Args:
        packet_type (str): パケットの種類
        packet_data (Union[bytes, Dict[str, Any]]): パケットのデータ
            （バイト列または辞書）
        direction (str, optional): パケットの方向（>> = 送信、<< = 受信）.
            デフォルトは">>"
        level (int, optional): ログレベル. デフォルトはDEBUG
    """
    if isinstance(packet_data, bytes):
        hex_data = " ".join(f"{b:02x}" for b in packet_data)
        logger.log(level, f"{direction} {packet_type}: {hex_data}")
    else:
        json_data = json.dumps(packet_data, ensure_ascii=False, indent=2)
        logger.log(level, f"{direction} {packet_type}:\n{json_data}")


def log_error(
    error_code: str,
    detail: Optional[Dict[str, Any]] = None,
    level: int = logging.ERROR,
) -> None:
    """エラー情報をログに記録する.

    Args:
        error_code (str): エラーコード
        detail (Optional[Dict[str, Any]], optional): エラーの詳細情報.
            デフォルトはNone
        level (int, optional): ログレベル. デフォルトはERROR
    """
    from .exceptions import ERROR_MESSAGES

    error_msg = ERROR_MESSAGES.get(error_code, "Unknown error: {detail}")
    if detail:
        error_msg = error_msg.format(**detail)
    logger.log(level, error_msg)

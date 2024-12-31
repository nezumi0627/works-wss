"""Logging configuration.

ロギ設定を提供するモジュール。
シンプルでクリーンなログ出力を実現します。
"""

import logging
from typing import Any, Dict

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# ログファイルのパス
LOG_FILE = "works_mqtt.log"

# カスタムテーマの定義
THEME = Theme(
    {
        "info": "bright_blue",
        "warning": "yellow",
        "error": "red bold",
        "debug": "dim white",
        "success": "green",
        "notice": "magenta",
    }
)

# コンソールの設定
console = Console(theme=THEME)


def setup_logging(level: int = logging.INFO) -> None:
    """ロギングの設定をします.

    Args:
        level: ログレベル。デフォルトはINFO。
    """
    # ログフォーマットの設定
    log_format = "%(message)s"
    date_format = "%H:%M:%S"

    # ファイルハンドラの設定
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)8s] %(message)s",
            datefmt=date_format,
        )
    )

    # WebSocketのデバッグログをフィルタリング
    class WebSocketFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            return not (
                msg.startswith(("= connection", "> ", "< "))
                or "BINARY" in msg
                or "Received message:" in msg
            )

    # Richハンドラの設定
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        omit_repeated_times=True,
        show_level=True,
        keywords=[],
        markup=True,
        highlighter=None,
    )
    rich_handler.setFormatter(logging.Formatter(log_format))
    rich_handler.addFilter(WebSocketFilter())
    file_handler.addFilter(WebSocketFilter())

    # ルートロガーの設定
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=[rich_handler, file_handler],
        force=True,
    )


# ロガーの取得
logger = logging.getLogger("works_mqtt")


def log_packet(packet_type: str, data: bytes, direction: str = ">>") -> None:
    """パケット情報をログに記録します.

    Args:
        packet_type: パケットの種類
        data: パケットデータ
        direction: 通信の方向（>> or <<）
    """
    if logger.getEffectiveLevel() <= logging.DEBUG:
        hex_data = data.hex(" ")[:32]  # 最初の32バイトのみ表示
        if len(data) > 16:
            hex_data += "..."
        logger.debug(f"{direction} {packet_type}: {hex_data}")


def log_error(error_type: str, context: Dict[str, Any]) -> None:
    """エラー情報をログに記録します.

    Args:
        error_type: エラーの種類
        context: エラーのコンテキスト情報
    """
    logger.error(f"{error_type}: {context}")

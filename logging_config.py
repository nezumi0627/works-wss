"""Richライブラリを使用したログ設定モジュール."""

import logging

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

from constants import CONSOLE_THEME, LOG_FORMAT


class LoggerFactory:
    """ロガーインスタンスを生成と設定をするファクトリークラス."""

    def __init__(self) -> None:
        """LoggerFactoryの初期化."""
        self._console = Console(theme=Theme(CONSOLE_THEME))

    def create_logger(
        self, name: str = "wmqtt", level: int = logging.DEBUG
    ) -> logging.Logger:
        """ロガーインスタンスを生成し設定する.

        Args:
            name: ロガー名、デフォルト:"wmqtt"
            level: ログレベル、デフォルト:logging.DEBUG

        Returns:
            logging.Logger: 設定済みロガーインスタンス
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers.clear()

        rich_handler = RichHandler(
            console=self._console,
            rich_tracebacks=True,
            markup=True,
            show_time=False,
        )
        rich_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(rich_handler)

        return logger


# デフォルトのファクトリーとロガーを初期化
logger_factory = LoggerFactory()
logger = logger_factory.create_logger()

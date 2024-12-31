"""Works Mobile MQTT WebSocketクライアント.

Works MobileのMQTTサービスに接続するためのWebSocketクライアントです。
以下の機能を提供します:

- WebSocket経由でのMQTT接続の確立と維持
- メッセージの送受信
- 自動再接続
- キープアライブ処理
- エラーハンドリング
- パケット解析とログ出力
"""

import asyncio
import json
import logging
import ssl
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, cast

import websockets
from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from websockets.client import WebSocketClientProtocol
from websockets.typing import Data, Subprotocol

from core import (
    ERROR_MESSAGES,
    MQTT_KEEP_ALIVE,
    MQTT_MAX_RETRIES,
    MQTT_PING_INTERVAL,
    MQTT_PING_TIMEOUT,
    MQTT_PROTOCOL_VERSION,
    MQTT_RETRY_INTERVAL,
    WS_ORIGIN,
    WS_SUBPROTOCOL,
    WS_URL,
    WS_USER_AGENT,
    AuthenticationError,
    ConnectionError,
    CookieError,
    MessageError,
    PacketError,
    StatusFlag,
    log_packet,
    logger,
)
from message import (
    MessageType,
    StickerInfo,
    StickerType,
    WorksMessage,
    get_channel_type_name,
    get_message_type_name,
    parse_message,
)
from mqtt import (
    MQTTPacket,
    PacketType,
    build_connect_packet,
    build_disconnect_packet,
    build_ping_packet,
    build_publish_packet,
    parse_packet,
)
from mqtt.packet.parser import (
    analyze_packet,
    parse_packet,
    parse_publish,
)


@dataclass
class MQTTConfig:
    """MQTT接続の設定.

    MQTT接続のタイムアウトとリトライ設定を管理します。

    Attributes:
        protocol_version: MQTTプロトコルバージョン
        keep_alive: キープアライブ間隔(秒)
        ping_interval: PINGREQ送信間隔(秒)
        ping_timeout: PINGRESP待機タイムアウト(秒)
        retry_interval: 再接続リトライ間隔(秒)
        max_retries: 最大リトライ回数
    """

    protocol_version: int = MQTT_PROTOCOL_VERSION
    keep_alive: int = MQTT_KEEP_ALIVE
    ping_interval: int = MQTT_PING_INTERVAL
    ping_timeout: int = MQTT_PING_TIMEOUT
    retry_interval: int = MQTT_RETRY_INTERVAL
    max_retries: int = MQTT_MAX_RETRIES


@dataclass
class WebSocketConfig:
    """WebSocket接続の設定.

    WebSocket接続のURLとヘッダー情報を管理します。

    Attributes:
        url: WebSocketエンドポイントURL
        origin: Originヘッダーの値
        user_agent: User-Agentヘッダーの値
        subprotocol: WebSocketサブプロトコル
    """

    url: str = WS_URL
    origin: str = WS_ORIGIN
    user_agent: str = WS_USER_AGENT
    subprotocol: Subprotocol = Subprotocol(WS_SUBPROTOCOL)


class WMQTTClient:
    """Works Mobile MQTT WebSocketクライアント.

    WebSocket経由でメッセージングサービスと通信するためのクライアント
    自動再接続とキープアライブを処理します。

    Attributes:
        cookies_path: クッキーファイルのパス
        ws_config: WebSocket接続設定
        mqtt_config: MQTT接続設定
        running: クライアントの実行状態
        current_retry: 現在のリトライ試行回数
        message_id: メッセージID カウンター
        ws: WebSocket接続オブジェクト
        state: 現在の接続状態
    """

    def __init__(
        self,
        cookies_path: str | Path = "cookie.json",
        ws_config: Optional[WebSocketConfig] = None,
        mqtt_config: Optional[MQTTConfig] = None,
    ) -> None:
        """WMQTTClientを初期化します.

        Args:
            cookies_path: クッキーファイルのパス
            ws_config: WebSocket接続設定
            mqtt_config: MQTT接続設定
        """
        self.cookies_path = Path(cookies_path)
        self.cookies = self._load_cookies()
        self.ws_config = ws_config or WebSocketConfig()
        self.config = mqtt_config or MQTTConfig()

        self.headers = {
            "User-Agent": self.ws_config.user_agent,
            "Origin": self.ws_config.origin,
            "Sec-WebSocket-Protocol": "mqtt",
            "Cookie": self.cookies,
        }

        self.running = True
        self.current_retry = 0
        self.message_id = 0
        self.ws: Optional[WebSocketClientProtocol] = None
        self._pending_messages: Dict[int, asyncio.Future] = {}
        # メッセージIDと受信時刻を保持する辞書
        self._received_messages: Dict[str, float] = {}
        # 重複チェックの有効期限（秒）
        self._message_expiry = 60.0
        self.state = StatusFlag.DISCONNECTED
        self.console = Console()

    def _load_cookies(self) -> str:
        """クッキーファイルを読み込みます.

        Returns:
            str: Cookie string

        Raises:
            CookieError: クッキーファイルの読み込みに失敗した場合
        """
        try:
            with open(self.cookies_path) as f:
                cookie_dict = json.load(f)
            return "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        except FileNotFoundError as err:
            raise CookieError(ERROR_MESSAGES["COOKIE_FILE_NOT_FOUND"]) from err
        except json.JSONDecodeError as err:
            raise CookieError(ERROR_MESSAGES["INVALID_COOKIE_FORMAT"]) from err

    def _get_next_message_id(self) -> int:
        """次のメッセージIDを取得します.

        Returns:
            int: Unique message ID (0-65535)
        """
        self.message_id = (self.message_id + 1) % 65536
        return self.message_id

    async def start(self) -> None:
        """クライアントを開始し、必要に応じて再接続を試みます."""
        self.running = True
        while self.running and self.current_retry < self.config.max_retries:
            try:
                await self.connect()
            except (
                websockets.exceptions.WebSocketException,
                ConnectionError,
                asyncio.CancelledError,
            ) as e:
                self.current_retry += 1
                if self.current_retry < self.config.max_retries:
                    logger.error(
                        ERROR_MESSAGES["CONNECTION_FAILED"].format(
                            reason=f"{e.__class__.__name__}: {e}"
                        )
                    )
                    logger.info(
                        f"Attempting reconnection... "
                        f"({self.current_retry}/{self.config.max_retries})"
                    )
                    # Exponential backoff for retry delay
                    retry_delay = self.config.retry_interval * (
                        2 ** (self.current_retry - 1)
                    )
                    logger.info(f"Wait time: {retry_delay} seconds")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(ERROR_MESSAGES["MAX_RETRIES_EXCEEDED"])
                    break

    async def connect(self) -> None:
        """WebSocket接続を確立し、MQTTセッションを開始します.

        Raises:
            AuthenticationError: 認証に失敗した場合
            ConnectionError: 接続に失敗した場合
        """
        try:
            logger.debug("Starting WebSocket connection...")
            logger.debug(f"URL: {self.ws_config.url}")
            logger.debug(f"Origin: {self.ws_config.origin}")
            logger.debug(f"Protocol: {self.ws_config.subprotocol}")

            self.state = StatusFlag.CONNECTING
            self.ws = await websockets.connect(
                self.ws_config.url,
                ssl=ssl.create_default_context(),
                extra_headers=self.headers,
                subprotocols=[self.ws_config.subprotocol],
                ping_interval=None,
            )
            logger.info("WebSocket connection established successfully")
            await self._mqtt_connect()
            self.state = StatusFlag.CONNECTED

            # Reset retry counter on successful connection
            self.current_retry = 0

            # Start keepalive and message monitoring tasks
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._start_keepalive())
                tg.create_task(self.listen())

        except websockets.exceptions.InvalidStatusCode as err:
            self.state = StatusFlag.DISCONNECTED
            raise AuthenticationError(
                ERROR_MESSAGES["AUTHENTICATION_FAILED"].format(
                    reason=f"HTTP {err.status_code}"
                )
            ) from err
        except websockets.exceptions.ConnectionClosed as err:
            self.state = StatusFlag.DISCONNECTED
            raise ConnectionError(
                ERROR_MESSAGES["CONNECTION_CLOSED"].format(
                    code=err.code, reason=err.reason
                )
            ) from err
        except (
            websockets.exceptions.WebSocketException,
            ConnectionError,
            asyncio.CancelledError,
        ) as err:
            self.state = StatusFlag.DISCONNECTED
            raise ConnectionError(
                ERROR_MESSAGES["CONNECTION_FAILED"].format(
                    reason=f"{err.__class__.__name__}: {err}"
                )
            ) from err

    async def _mqtt_connect(self) -> None:
        """MQTT接続を確立します."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        client_id = f"web-beejs_{uuid.uuid4().hex[:12]}"
        packet = build_connect_packet(
            client_id=client_id,
            keep_alive=self.config.keep_alive,
            username="dummy",
        )

        # 送信前にパケットをログ出力
        log_packet("CONNECT", packet.packet, "<<")
        await self.ws.send(cast(Data, packet.packet))
        logger.info("MQTT connection request sent")

    async def listen(self) -> None:
        """受信メッセージを監視します."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    await self._handle_binary_message(message)
                else:
                    logger.warning(f"Non-binary message received: {message}")
        except websockets.exceptions.ConnectionClosed as err:
            logger.error(f"WebSocket connection closed: {err}")
        except asyncio.CancelledError:
            logger.info("Message monitoring task terminated")
            raise

    async def _handle_binary_message(self, data: bytes) -> None:
        """バイナリメッセージを処理します.

        Args:
            data: 受信したバイナリデータ
        """
        try:
            packet = parse_packet(data)
            if packet is None:
                raise PacketError("パケットの解析に失敗しました")

            # パケットの詳細な解析
            packet_info = analyze_packet(packet)

            # パケット情報をログに出力
            if packet_info:
                if "error" in packet_info:
                    logger.error(f"パケット解析エラー: {packet_info['error']}")
                else:
                    self._log_packet_info(packet_info)

            # パケットを処理
            await self._process_packet(packet)

        except Exception as err:
            raise PacketError(f"予期せぬエラー: {err}") from err

    def _is_duplicate_message(self, packet_info: dict[str, Any]) -> bool:
        """メッセージが重複しているかチェックします.

        Args:
            packet_info: パケット情報

        Returns:
            bool: 重複している場合はTrue
        """
        if packet_info.get("type") != "PUBLISH":
            return False

        payload = packet_info.get("payload", {})
        if not isinstance(payload, dict):
            return False

        # メッセージキーを取得
        message_key = None
        if "notification-id" in payload:
            message_key = payload["notification-id"]
        elif "relayDataList" in payload:
            relay_data = payload["relayDataList"][0]
            message_key = f"{relay_data['bdy'].get('msgSn', '')}"

        if not message_key:
            return False

        # 現在時刻を取得
        current_time = asyncio.get_event_loop().time()

        # 期限切れのメッセージを削除
        expired_keys = [
            key
            for key, timestamp in self._received_messages.items()
            if current_time - timestamp > self._message_expiry
        ]
        for key in expired_keys:
            del self._received_messages[key]

        # 重複チェック
        if message_key in self._received_messages:
            return True

        # 新しいメッセージを記録
        self._received_messages[message_key] = current_time
        return False

    def _log_packet_info(self, packet_info: dict[str, Any]) -> None:
        """パケット情報をログに出力します.

        Args:
            packet_info: パケット情報
        """
        # パケットタイプと基本情報を出力
        packet_type = packet_info["type"]
        flags = packet_info["flags"]
        length = packet_info["length"]

        # PUBLISHパケット以外の場合のみ基本情報を出力
        if packet_type != "PUBLISH":
            basic_info = (
                f"パケット解析: {packet_type} "
                f"(DUP: {flags['dup']}, QoS: {flags['qos']}, "
                f"Retain: {flags['retain']}, Length: {length})"
            )
            logger.debug(basic_info)

            # 生のパケットデータを16進数で表示
            if raw_packet := packet_info.get("raw_packet"):
                hex_dump = " ".join(f"{b:02x}" for b in raw_packet)
                self.console.print(
                    Panel(
                        hex_dump,
                        title="[bold cyan]Raw Packet Data[/bold cyan]",
                        border_style="cyan",
                        padding=(0, 1),
                    )
                )

    def _create_notification_panel(self, payload: dict[str, Any]) -> None:
        """通知メッセージのパネルを作成します.

        Args:
            payload: 通知メッセージのペイロード
        """
        notification_content = {
            "Channel": payload.get("chTitle", ""),
            "Channel Type": get_channel_type_name(payload.get("chType", 0)),
            "Message Type": (
                f"{payload.get('nType', 0)} "
                f"({get_message_type_name(payload.get('nType', 0))})"
            ),
            "Sender": payload.get("loc-args0", ""),
            "Content": payload.get("loc-args1", ""),
        }

        # スタンプ情報がある場合は追加
        if (
            payload.get("nType") == MessageType.NOTIFICATION_STICKER
            and "extras" in payload
        ):
            try:
                extras = json.loads(payload["extras"])
                sticker = StickerInfo.from_dict(extras)
                if sticker.sticker_type != StickerType.NONE:
                    notification_content.update(
                        {
                            "Sticker Type": sticker.sticker_type.value,
                            "Package ID": sticker.package_id,
                            "Sticker ID": sticker.sticker_id,
                        }
                    )
                    if sticker.options:
                        notification_content["Options"] = sticker.options
            except Exception as e:
                logger.error(f"スタンプ情報解析エラー: {e}")

        # デバッグモードの場合は追加情報を表示
        if logger.getEffectiveLevel() <= logging.DEBUG:
            debug_content = {
                "Created at": payload.get("createTime", ""),
                "Notification ID": payload.get("notification-id", ""),
                "Badge count": payload.get("badge", 0),
                "Channel number": payload.get("chNo", ""),
                "Status type": payload.get("sType", ""),
            }
            if "extras" in payload:
                debug_content["Raw Extras"] = payload["extras"]

            self.console.print(
                Panel(
                    self._create_content_table(debug_content),
                    title="[bold cyan]Debug Information[/bold cyan]",
                    border_style="cyan",
                    padding=(1, 2),
                )
            )

        self.console.print(
            Panel(
                self._create_content_table(notification_content),
                title="[bold blue]通知メッセージ[/bold blue]",
                border_style="blue",
                padding=(1, 2),
            )
        )

    def _create_content_table(self, content: dict[str, Any]) -> Table:
        """コンテンツテーブルを作成します.

        Args:
            content: 表示する内容の辞書

        Returns:
            Table: 整形されたテーブル
        """
        table = Table(box=ROUNDED, show_header=False, padding=(0, 1))
        table.add_column("Key", style="cyan", width=15)
        table.add_column("Value", style="green", overflow="fold")

        for key, value in content.items():
            # 長いテキストは折り返して表示
            if isinstance(value, str) and len(value) > 100:
                value = value[:97] + "..."
            table.add_row(key, str(value))

        return table

    def _create_channel_message_panel(self, payload: dict[str, Any]) -> None:
        """チャンネルメッセージのパネルを作成します.

        Args:
            payload: チャンネルメッセージのペイロード
        """
        relay_data = payload["relayDataList"][0]
        body = relay_data["bdy"]

        message_content = {
            "Channel": relay_data.get("cid", ""),
            "Command": relay_data.get("cmd", ""),
            "Message Type": (
                f"{body.get('msgTypeCode', 0)} "
                f"({get_message_type_name(body.get('msgTypeCode', 0))})"
            ),
            "Content": body.get("msg", ""),
            "Sender": body.get("writerInfo", {}).get("name", "Unknown"),
        }

        self.console.print(
            self._create_message_panel("チャンネルメッセージ", message_content)
        )

    async def _process_packet(self, packet: MQTTPacket) -> None:
        """MQTTパケットを処理します."""
        try:
            # パケットの詳細な解析
            packet_info = analyze_packet(packet)
            if not packet_info:
                return

            # パケットタイプに応じた処理
            if packet.packet_type == PacketType.PUBLISH:
                topic, payload, message_id = parse_publish(packet)

                try:
                    notification = json.loads(payload)

                    # 重複チェック
                    if self._is_duplicate_message(packet_info):
                        message_key = (
                            notification.get("notification-id")
                            or f"{notification.get('relayDataList', [{}])[0].get('bdy', {}).get('msgSn', '')}"
                        )
                        self.console.print(
                            Panel(
                                f"[dim]前のメッセージと同じ内容です (ID: {message_key})[/dim]",
                                border_style="dim blue",
                                padding=(0, 1),
                            )
                        )
                        await self._handle_qos(packet, message_id)
                        return

                    # パケット情報を出力
                    flags = packet_info["flags"]
                    length = packet_info["length"]
                    logger.debug(
                        f"パケット解析: PUBLISH "
                        f"(DUP: {flags['dup']}, QoS: {flags['qos']}, "
                        f"Retain: {flags['retain']}, Length: {length})"
                    )

                    # 生のパケットデータを表示
                    if raw_packet := packet_info.get("raw_packet"):
                        hex_dump = " ".join(f"{b:02x}" for b in raw_packet)
                        self.console.print(
                            Panel(
                                hex_dump,
                                title="[bold cyan]Raw Packet Data[/bold cyan]",
                                border_style="cyan",
                                padding=(0, 1),
                            )
                        )

                    # メッセージを処理
                    if message := parse_message(payload):
                        await self._route_message(topic, message)

                    await self._handle_qos(packet, message_id)
                except json.JSONDecodeError as err:
                    logger.error(f"JSONデコードエラー: {err}")

            elif packet.packet_type == PacketType.CONNACK:
                logger.info("MQTT connection established")
            elif packet.packet_type == PacketType.PINGRESP:
                logger.debug("Received PINGRESP")
            elif packet.packet_type == PacketType.SUBACK:
                self._handle_suback(packet)

        except Exception as err:
            logger.error(f"パケット処理エラー: {err}")

    async def _handle_qos(
        self, packet: MQTTPacket, message_id: Optional[int]
    ) -> None:
        """QoS処理を行います."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        qos = (packet.flags & 0x06) >> 1
        if qos > 0 and message_id is not None:
            puback = build_publish_packet(
                topic="",
                payload=b"",
                qos=0,
                retain=False,
                dup=False,
            )
            await self.ws.send(cast(Data, puback.packet))

    def _handle_suback(self, packet: MQTTPacket) -> None:
        """SUBACKパケットを処理します."""
        message_id = packet.get_message_id()
        if message_id in self._pending_messages:
            self._pending_messages[message_id].set_result(True)

    async def _process_payload(self, topic: str, payload: bytes) -> None:
        """ペイロードを処理します."""
        try:
            self._log_payload(topic, payload)
            data = json.loads(payload)
            works_message = WorksMessage.from_dict(data)
            await self._route_message(topic, works_message)
        except json.JSONDecodeError as err:
            raise MessageError(
                ERROR_MESSAGES["MESSAGE_PARSE_ERROR"].format(detail=str(err))
            ) from err
        except ValueError as err:
            raise MessageError(
                ERROR_MESSAGES["INVALID_MESSAGE_FORMAT"].format(
                    detail=str(err)
                )
            ) from err

    def _log_payload(self, topic: str, payload: bytes) -> None:
        """ペイロードの内容をログに記録します."""
        logger.debug("\nReceived data:")
        logger.debug(f"Topic: {topic}")
        logger.debug("Payload:")
        logger.debug(f"hex: {payload.hex()}")
        logger.debug(f"str: {payload.decode('utf-8', errors='replace')}")

    async def _route_message(self, topic: str, message: WorksMessage) -> None:
        """メッセージを適切なハンドラーにルーティングします."""
        if "nType" in message.body:
            await self._handle_channel_message(topic, message)
        elif message.command == MessageType.CMD_READ:
            await self._handle_read_notification(message)
        elif "msgTypeCode" in message.body:
            await self._handle_channel_message(topic, message)
        else:
            logger.debug(f"Unknown command: {message.command}")

    async def _handle_read_notification(self, message: WorksMessage) -> None:
        """既読通知を処理します.

        Args:
            message: 既読通知メッセージ
        """
        body = message.body
        logger.info("\nRead notification:")
        logger.info(f"Channel: {message.channel_id}")
        logger.info(f"User ID: {body.get('readerId')}")
        logger.info(f"Message number: {body.get('msgSn')}")

    def _format_sticker_info(self, sticker: StickerInfo) -> str:
        """スタンプ情報をフォーマットします.

        Args:
            sticker: スタンプ情報

        Returns:
            str: Formatted sticker information
        """
        parts = [
            "[yellow]Sticker info:[/yellow]",
            f"  [blue]Type[/blue]: {sticker.sticker_type.value}",
            f"  [blue]Package ID[/blue]: {sticker.package_id}",
            f"  [blue]Sticker ID[/blue]: {sticker.sticker_id}",
        ]
        if sticker.options:
            parts.append(f"  [blue]Options[/blue]: {sticker.options}")
        return "\n".join(parts)

    async def _handle_channel_message(
        self,
        topic: str,
        message: WorksMessage,
    ) -> None:
        """チャンネルメッセージを処理します.

        Args:
            topic: メッセージトピック
            message: 受信したメッセージ
        """
        body = message.body

        if "nType" in body:
            msg_type = body.get("nType", 0)
            ch_type = body.get("chType", 0)

            # 通知メッセージパネルを作成
            notification_content = {
                "Channel": body.get("chTitle", ""),
                "Channel Type": get_channel_type_name(ch_type),
                "Message Type": f"{msg_type} ({get_message_type_name(msg_type)})",
                "Sender": body.get("loc-args0", ""),
                "Sender ID": body.get("fromUserNo", ""),
            }

            # スタンプ情報がある場合は追加
            if (
                msg_type == MessageType.NOTIFICATION_STICKER
                and "extras" in body
            ):
                try:
                    extras = json.loads(body["extras"])
                    sticker = StickerInfo.from_dict(extras)
                    if sticker.sticker_type != StickerType.NONE:
                        notification_content.update(
                            {
                                "Sticker Type": sticker.sticker_type.value,
                                "Package ID": sticker.package_id,
                                "Sticker ID": sticker.sticker_id,
                                "Options": sticker.options or "None",
                            }
                        )
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Sticker info parse error: {e}")

            # デバッグ情報を追加
            debug_content = {
                "Created at": body.get("createTime", ""),
                "Notification ID": body.get("notification-id", ""),
                "Badge count": body.get("badge", 0),
                "Channel number": body.get("chNo", ""),
                "Status type": body.get("sType", ""),
            }

            self.console.print(
                self._create_message_panel(
                    "Notification Message", notification_content
                )
            )
            if logger.getEffectiveLevel() <= logging.DEBUG:
                self.console.print(
                    self._create_message_panel(
                        "Debug Information", debug_content
                    )
                )

        else:
            msg_type = body.get("msgTypeCode", 0)
            ch_type = body.get("chType", 0)

            # チャンネルメッセージパネルを作成
            message_content = {
                "Channel": message.channel_id,
                "Channel Type": get_channel_type_name(ch_type),
                "Message Type": f"{msg_type} ({get_message_type_name(msg_type)})",
                "Content": body.get("msg", ""),
                "Sender": body.get("writerInfo", {}).get("name", "Unknown"),
            }

            # デバッグ情報を追加
            debug_content = {
                "Created at": body.get("ctime", ""),
                "Updated at": body.get("utime", ""),
                "Member count": body.get("mbrCnt", 0),
                "Message ID": body.get("msgTid", ""),
                "Status": body.get("msgStatusType", ""),
            }

            self.console.print(
                self._create_message_panel("Channel Message", message_content)
            )
            if logger.getEffectiveLevel() <= logging.DEBUG:
                self.console.print(
                    self._create_message_panel(
                        "Debug Information", debug_content
                    )
                )

    async def _log_mqtt_info(
        self,
        message_type: int,
        dup_flag: int,
        qos_level: int,
        retain: int,
        payload_length: int,
    ) -> None:
        """MQTTパケット情報をログに記録します.

        Args:
            message_type: メッセージタイプ
            dup_flag: 重複フラグ
            qos_level: QoSレベル
            retain: 保持フラグ
            payload_length: ペイロード長
        """
        try:
            message_type_name = PacketType(message_type).name
        except ValueError:
            message_type_name = f"UNKNOWN({message_type})"

        logger.debug(
            f"MQTT: {message_type_name} "
            f"(DUP: {dup_flag}, QoS: {qos_level}, Retain: {retain}, "
            f"Length: {payload_length} bytes)",
        )

    async def stop(self) -> None:
        """クライアントを停止します."""
        self.running = False
        if self.ws:
            try:
                packet = build_disconnect_packet()
                await self.ws.send(cast(Data, packet.packet))
                await self.ws.close()
                self.state = StatusFlag.DISCONNECTED
                logger.info("Connection closed")
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

    async def _start_keepalive(self) -> None:
        """定期的にキープアライブパケットを送信します."""
        while self.running:
            try:
                await asyncio.sleep(self.config.ping_interval)
                if self.ws and not self.ws.closed:
                    await self._send_pingreq()
                    logger.debug("Sent keepalive packet")
            except (
                websockets.exceptions.WebSocketException,
                ConnectionError,
                asyncio.CancelledError,
            ) as e:
                if not isinstance(e, asyncio.CancelledError):
                    logger.error(f"Keepalive error: {e}")
                break

    async def _send_pingreq(self) -> None:
        """MQTT PINGREQパケットを送信します."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        try:
            packet = build_ping_packet()
            await self.ws.send(cast(Data, packet.packet))
        except Exception as e:
            logger.error(f"Error sending PINGREQ: {e}")

    async def _log_mqtt_packet(
        self, packet: MQTTPacket, direction: str = ">>"
    ) -> None:
        """MQTTパケットの詳細をログに出力します."""
        try:
            msg_type = packet.packet_type.name
            header_content = {
                "Type": f"0x{packet.packet_type:02x}",
                "DUP": str((packet.flags & 0x08) >> 3),
                "QoS": str((packet.flags & 0x06) >> 1),
                "Retain": str(packet.flags & 0x01),
                "Length": str(packet.remaining_length),
            }

            self.console.print(
                self._create_message_panel(
                    f"MQTT {direction} {msg_type}", header_content
                )
            )

            if packet.payload:
                payload_content: Dict[str, str] = {
                    "hex": packet.payload.hex(" ")
                }

                if packet.packet_type == PacketType.PUBLISH:
                    topic, payload, msg_id = parse_publish(packet)
                    payload_content["Topic"] = topic
                    payload_content["Message ID"] = (
                        str(msg_id) if msg_id else "None"
                    )

                    try:
                        decoded = payload.decode("utf-8", errors="replace")
                        payload_content["Content"] = decoded
                        self._parse_message_payload(decoded)
                    except UnicodeDecodeError:
                        payload_content["Content"] = "(binary data)"
                else:
                    try:
                        payload_content["str"] = packet.payload.decode(
                            "utf-8", errors="replace"
                        )
                    except UnicodeDecodeError:
                        pass

                self.console.print(
                    self._create_message_panel("Payload", payload_content)
                )

        except Exception as e:
            logger.error(f"パケットログ出力エラー: {e}")

    def _parse_connect_packet(self, packet: MQTTPacket) -> dict[str, Any]:
        """CONNECTパケットの内容を解析する.

        Args:
            packet: CONNECTパケット

        Returns:
            dict: 解析された接続情報
        """
        try:
            if packet.payload is None:
                raise ValueError("No payload in CONNECT packet")

            # プロトコル名の長さを取得
            protocol_name_len = struct.unpack("!H", packet.payload[0:2])[0]

            # プロトコル名を取得
            protocol_name = packet.payload[2 : 2 + protocol_name_len].decode(
                "utf-8"
            )

            # プロトコルレベルを取得
            protocol_level = packet.payload[2 + protocol_name_len]

            # 接続フラグを取得
            connect_flags = packet.payload[2 + protocol_name_len + 1]

            # キープアライブを取得
            keep_alive = struct.unpack(
                "!H",
                packet.payload[
                    2 + protocol_name_len + 2 : 2 + protocol_name_len + 4
                ],
            )[0]

            return {
                "protocol_name": protocol_name,
                "protocol_level": protocol_level,
                "clean_session": bool(connect_flags & 0x02),
                "will_flag": bool(connect_flags & 0x04),
                "will_qos": (connect_flags & 0x18) >> 3,
                "will_retain": bool(connect_flags & 0x20),
                "password_flag": bool(connect_flags & 0x40),
                "username_flag": bool(connect_flags & 0x80),
                "keep_alive": keep_alive,
            }
        except Exception as e:
            logger.error(f"CONNECTパケット解析エラー: {e}")
            return {}

    def _parse_message_payload(self, payload: str) -> None:
        """メッセージペイロードをJSONとして解析します."""
        try:
            data = json.loads(payload)
            if "relayDataList" in data:
                for relay_data in data["relayDataList"]:
                    cmd = relay_data.get("cmd")
                    body = relay_data.get("bdy", {})

                    relay_content = {
                        "Command": cmd,
                        "Service ID": relay_data.get("svcid"),
                        "Channel ID": relay_data.get("cid"),
                    }

                    if cmd == MessageType.CMD_READ:
                        read_content = {
                            "Channel": body.get("cid"),
                            "Reader": body.get("readerId"),
                            "Message": body.get("msgSn"),
                        }
                        self.console.print(
                            self._create_message_panel(
                                "Read Notification", read_content
                            )
                        )
                    elif "msgTypeCode" in body:
                        msg_type = body["msgTypeCode"]
                        message_content = {
                            "Type": get_message_type_name(msg_type),
                            "Channel": relay_data.get("cid"),
                            "Message ID": body.get("msgTid"),
                            "Content": body.get("msg", ""),
                            "Status": body.get("msgStatusType", ""),
                            "Sender": body.get("writerInfo", {}).get(
                                "name", "Unknown"
                            ),
                        }

                        if (
                            msg_type == MessageType.NOTIFICATION_STICKER
                            and "extras" in body
                        ):
                            try:
                                extras = json.loads(body["extras"])
                                sticker = StickerInfo.from_dict(extras)
                                message_content.update(
                                    {
                                        "Sticker Type": sticker.sticker_type.value,
                                        "Package ID": sticker.package_id,
                                        "Sticker ID": sticker.sticker_id,
                                        "Options": sticker.options or "None",
                                    }
                                )
                            except Exception as e:
                                logger.error(f"スタンプ情報解析エラー: {e}")

                        self.console.print(
                            self._create_message_panel(
                                "Message", message_content
                            )
                        )

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析エラー: {e}")

    def _create_message_panel(
        self, title: str, content: dict[str, Any]
    ) -> Panel:
        """メッセージパネルを作成します.

        Args:
            title: パネルのタイトル
            content: 表示する内容の辞書

        Returns:
            Panel: 整形されたパネル
        """
        table = Table(box=ROUNDED, show_header=False)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green", overflow="fold")

        for key, value in content.items():
            # 長いテキストは折り返して表示
            if isinstance(value, str) and len(value) > 100:
                value = value[:97] + "..."
            table.add_row(key, str(value))

        return Panel(
            table,
            title=f"[bold blue]{title}[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        )

    async def _handle_publish(self, packet: MQTTPacket) -> None:
        """PUBLISHパケットを処理します."""
        try:
            topic, payload, message_id = parse_publish(packet)

            try:
                notification = json.loads(payload)
                packet_info = analyze_packet(packet)

                # 重複チェック
                if self._is_duplicate_message(packet_info):
                    message_key = (
                        notification.get("notification-id")
                        or f"{notification.get('relayDataList', [{}])[0].get('bdy', {}).get('msgSn', '')}"
                    )
                    self.console.print(
                        Panel(
                            f"[dim]前のメッセージと同じ内容です (ID: {message_key})[/dim]",
                            border_style="dim blue",
                            padding=(0, 1),
                        )
                    )
                    await self._handle_qos(packet, message_id)
                    return

                # メッセージを処理
                if message := parse_message(payload):
                    await self._route_message(topic, message)

                await self._handle_qos(packet, message_id)
            except json.JSONDecodeError as err:
                logger.error(f"JSONデコードエラー: {err}")

        except ValueError as err:
            raise PacketError(
                ERROR_MESSAGES["PACKET_PARSE_ERROR"].format(detail=str(err))
            ) from err


async def main() -> None:
    """アプリケーションのメインエントリーポイント."""
    client = WMQTTClient()
    try:
        await client.start()
    except KeyboardInterrupt:
        logger.info("Starting shutdown...")
        await client.stop()
    except Exception as e:
        logger.error(f"Unexpected error occurred: {e}")
        await client.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())

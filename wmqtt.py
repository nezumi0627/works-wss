"""Works Mobile MQTT WebSocketクライアント.

Works MobileのMQTTサービスに接続するためのWebSocketクライアントです。
以下の機能を提供します:

- WebSocket経由でのMQTT接続の確立と維持
- メッセージの送受信
- 自動再接続
- キープアライブ処理
- エラーハンドリング
"""

import asyncio
import json
import ssl
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, cast

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.typing import Data, Subprotocol

from constants import (
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
    StatusFlag,
)
from exceptions import (
    ERROR_MESSAGES,
    AuthenticationError,
    ConnectionError,
    CookieError,
    MessageError,
    PacketError,
)
from logging_config import logger
from message_types import (
    MessageType,
    get_channel_type_name,
    get_message_type_name,
)
from models import WorksMessage
from mqtt_packet import MQTTMessageType, MQTTPacket
from sticker_types import StickerInfo


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
        self.state = StatusFlag.DISCONNECTED

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
        connect_packet = MQTTPacket.create_connect(
            client_id=client_id,
            protocol_version=self.config.protocol_version,
            keep_alive=self.config.keep_alive,
            username="dummy",
        )
        await self.ws.send(cast(Data, connect_packet.to_bytes()))
        logger.info("MQTT connection established")

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

    async def _handle_binary_message(self, message: bytes) -> None:
        """バイナリメッセージを処理します."""
        try:
            packet = MQTTPacket.from_bytes(message)
            await self._process_packet(packet)
            await self._log_mqtt_info(
                packet.header.message_type,
                packet.header.dup_flag,
                packet.header.qos_level,
                packet.header.retain,
                len(packet.payload),
            )
        except Exception as err:
            raise PacketError(
                ERROR_MESSAGES["UNEXPECTED_ERROR"].format(detail=str(err))
            ) from err

    async def _process_packet(self, packet: MQTTPacket) -> None:
        """MQTTパケットを処理します."""
        if packet.header.message_type == MQTTMessageType.PUBLISH:
            await self._handle_publish(packet)
        elif packet.header.message_type == MQTTMessageType.CONNACK:
            logger.info("MQTT connection established")
        elif packet.header.message_type == MQTTMessageType.PINGRESP:
            logger.debug("Received PINGRESP")
        elif packet.header.message_type == MQTTMessageType.SUBACK:
            self._handle_suback(packet)

    async def _handle_publish(self, packet: MQTTPacket) -> None:
        """PUBLISHパケットを処理します."""
        try:
            topic, payload, message_id = packet.get_topic_and_payload()
            await self._handle_qos(packet, message_id)
            if payload:
                await self._process_payload(topic, payload)
        except ValueError as err:
            raise PacketError(
                ERROR_MESSAGES["PACKET_PARSE_ERROR"].format(detail=str(err))
            ) from err

    async def _handle_qos(
        self, packet: MQTTPacket, message_id: Optional[int]
    ) -> None:
        """QoS処理を行います."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        if packet.header.qos_level > 0 and message_id is not None:
            puback = MQTTPacket.create_puback(message_id)
            await self.ws.send(cast(Data, puback.to_bytes()))

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

        # For notification messages
        if "nType" in body:
            msg_type = body.get("nType", 0)
            ch_type = body.get("chType", 0)
            logger.info("\nNotification message:")
            logger.info(f"Channel: {body.get('chTitle', '')}")
            logger.info(f"Channel type: {get_channel_type_name(ch_type)}")

            # Build message based on loc-key
            loc_key = body.get("loc-key", "")
            loc_args = []
            i = 0
            while f"loc-args{i}" in body:
                loc_args.append(body[f"loc-args{i}"])
                i += 1

            # Display notification type
            type_info = [f"{msg_type}"]
            if loc_key:
                type_info.append(f"({loc_key})")
            type_info.append(f"({get_message_type_name(msg_type)})")
            logger.info(f"Notification type: {' '.join(type_info)}")

            # Display sender info
            if len(loc_args) >= 1:
                logger.info(f"Sender: {loc_args[0]}")

            # Display sticker info
            if (
                msg_type == MessageType.NOTIFICATION_STICKER
                and "extras" in body
            ):
                try:
                    extras = json.loads(body["extras"])
                    sticker = StickerInfo.from_dict(extras)
                    logger.info(self._format_sticker_info(sticker))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Sticker info parse error: {e}")

            if "fromUserNo" in body:
                logger.info(f"Sender ID: {body.get('fromUserNo')}")

            # Debug info
            logger.debug("\nNotification details:")
            logger.debug(f"Created at: {body.get('createTime', '')}")
            logger.debug(f"Notification ID: {body.get('notification-id', '')}")
            logger.debug(f"Badge count: {body.get('badge', 0)}")
            logger.debug(f"Channel number: {body.get('chNo', '')}")
            logger.debug(f"Channel type: {ch_type}")
            logger.debug(f"Notification type: {msg_type}")
            logger.debug(f"Status type: {body.get('sType', '')}")
            return

        # For regular channel messages
        msg_type = body.get("msgTypeCode", 0)
        ch_type = body.get("chType", 0)
        logger.info("\nChannel message:")
        logger.info(f"Channel: {message.channel_id}")
        logger.info(f"Channel type: {get_channel_type_name(ch_type)}")
        logger.info(f"Type: {msg_type} ({get_message_type_name(msg_type)})")
        logger.info(f"Message: {body.get('msg', '')}")

        if "writerInfo" in body:
            writer = body["writerInfo"]
            logger.info(f"Sender: {writer.get('name', 'Unknown')}")

        # Debug info
        logger.debug("\nMessage details:")
        logger.debug(f"Created at: {body.get('ctime', '')}")
        logger.debug(f"Updated at: {body.get('utime', '')}")
        logger.debug(f"Member count: {body.get('mbrCnt', 0)}")
        logger.debug(f"Message ID: {body.get('msgTid', '')}")
        logger.debug(f"Status: {body.get('msgStatusType', '')}")

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
            message_type_name = MQTTMessageType(message_type).name
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
            pingreq_packet = MQTTPacket.create_pingreq()
            await self.ws.send(cast(Data, pingreq_packet.to_bytes()))
        except Exception as e:
            logger.error(f"Error sending PINGREQ: {e}")


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

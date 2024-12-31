"""Line Works WebSocket クライアント実装モジュール。

このモジュールは Line Works の WebSocket API を使用して
リアルタイムメッセージングを実現します。
"""

import asyncio
from dataclasses import dataclass
from enum import IntEnum
import json
import logging
from pathlib import Path
import struct

import websockets
from websockets.client import WebSocketClientProtocol

# ログ設定
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)


class LogLevel(IntEnum):
    """ログレベルの定義。"""

    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    FATAL = 5
    NONE = 99


class ConnectionState(IntEnum):
    """WebSocket接続状態の定義。"""

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class UserStatus(IntEnum):
    """Line Worksユーザーステータスの定義。"""

    OFFLINE = 0
    PC_ONLINE = 1
    AWAY = 2
    MOBILE_FOREGROUND = 4
    APP_INSTALLED = 8
    DO_NOT_DISTURB = 16
    ABSENCE = 32
    CALENDAR = 64
    WEB_ONLINE = 128
    NO_PC_PUSH = 256


@dataclass
class MQTTConfig:
    """MQTT接続の設定値を保持するデータクラス。"""

    protocol_version: int = 4
    keep_alive: int = 50
    ping_interval: int = 30
    ping_timeout: int = 10
    retry_interval: int = 5
    max_retries: int = 3


class LineWorksWS:
    """Line Works WebSocket クライアントクラス。"""

    WEBSOCKET_URL = "wss://jp1-web-noti.worksmobile.com/wmqtt"
    ORIGIN = "https://talk.worksmobile.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.6723.70 Safari/537.36"
    )

    def __init__(self, cookies_path: str | Path = "cookies.json") -> None:
        """LineWorksWSクライアントを初期化します。

        Args:
            cookies_path: クッキーファイルのパス
        """
        self.cookies_path = Path(cookies_path)
        self.cookies: dict[str, str] = {}
        self.websocket: WebSocketClientProtocol | None = None
        self.state = ConnectionState.DISCONNECTED
        self.config = MQTTConfig()
        self._load_cookies()
        self.client_id = f"web-beejs_{self._generate_random_id()}"

    def _generate_random_id(self) -> str:
        """ランダムなクライアントIDを生成します。"""
        import random

        return "".join(f"{random.randint(0, 255):02x}" for _ in range(8))

    def _load_cookies(self) -> None:
        """クッキーファイルを読み込みます。"""
        try:
            self.cookies = json.loads(
                self.cookies_path.read_text(encoding="utf-8"),
            )
        except Exception as error:
            logger.error("クッキーファイルの読み込みに失敗: %s", error)
            raise

    def _create_headers(self) -> dict[str, str]:
        """WebSocket接続用のヘッダーを生成します。"""
        return {
            "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
            "Origin": self.ORIGIN,
            "User-Agent": self.USER_AGENT,
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
        }

    def _create_mqtt_connect_packet(self) -> bytes:
        """MQTT CONNECT パケットを生成します。"""
        # Fixed header
        packet_type = 0x10  # CONNECT

        # Variable header
        protocol_name = b"\x00\x04MQTT"
        protocol_level = bytes([self.config.protocol_version])
        connect_flags = bytes([0xC2])  # Username + Password + Clean Session
        keep_alive = struct.pack("!H", self.config.keep_alive)

        # Payload
        client_id = self.client_id.encode("utf-8")
        client_id_len = struct.pack("!H", len(client_id))

        username = self.cookies.get("WORKS_USER_ID", "").encode("utf-8")
        username_len = struct.pack("!H", len(username))

        password = self.cookies.get("NEO_SES", "").encode("utf-8")
        password_len = struct.pack("!H", len(password))

        variable_header = (
            protocol_name + protocol_level + connect_flags + keep_alive
        )
        payload = (
            client_id_len
            + client_id
            + username_len
            + username
            + password_len
            + password
        )

        # Calculate remaining length
        remaining_length = len(variable_header) + len(payload)
        remaining_bytes = []
        while remaining_length > 0:
            byte = remaining_length % 128
            remaining_length = remaining_length // 128
            if remaining_length > 0:
                byte |= 0x80
            remaining_bytes.append(byte)

        return (
            bytes([packet_type])
            + bytes(remaining_bytes)
            + variable_header
            + payload
        )

    async def _wait_for_connack(self) -> bool:
        """CONNACK パケットを待機して処理します。"""
        try:
            response = await self.websocket.recv()
            if not isinstance(response, bytes):
                logger.error("CONNACKの応答がバイナリデータではありません")
                return False

            logger.debug("CONNACK受信: %s", response.hex(" "))
            if len(response) < 4:
                logger.error("不正なCONNACKパケット長")
                return False

            packet_type = response[0] >> 4
            if packet_type != 2:  # CONNACK
                logger.error("予期しないパケットタイプ: %d", packet_type)
                return False

            session_present = bool(response[2] & 0x01)
            return_code = response[3]

            logger.debug(
                "セッション存在: %s, リターンコード: %d",
                session_present,
                return_code,
            )

            if return_code == 0:
                logger.info("MQTTブローカーへの接続成功")
                return True

            logger.error("接続拒否, リターンコード: %d", return_code)
            return False

        except Exception as error:
            logger.error("CONNACK待機中にエラー: %s", error)
            return False

    def _create_subscribe_packet(
        self,
        topic: str,
        message_id: int = 1,
    ) -> bytes:
        """MQTT SUBSCRIBE パケットを生成します。"""
        packet_type = 0x82  # SUBSCRIBE
        message_id_bytes = struct.pack("!H", message_id)

        topic_bytes = topic.encode("utf-8")
        topic_length = struct.pack("!H", len(topic_bytes))
        qos = bytes([0x00])  # QoS 0

        variable_header = message_id_bytes
        payload = topic_length + topic_bytes + qos

        remaining_length = len(variable_header) + len(payload)
        remaining_bytes = []
        while remaining_length > 0:
            byte = remaining_length % 128
            remaining_length = remaining_length // 128
            if remaining_length > 0:
                byte |= 0x80
            remaining_bytes.append(byte)

        return (
            bytes([packet_type])
            + bytes(remaining_bytes)
            + variable_header
            + payload
        )

    async def subscribe_to_channel(self, channel_id: str) -> None:
        """チャンネルをサブスクライブ"""
        if self.state != ConnectionState.CONNECTED:
            logger.error("Not connected to MQTT broker")
            return

        topic = f"channel/{channel_id}"
        subscribe_packet = self._create_subscribe_packet(topic)
        logger.debug(f"Subscribing to channel: {channel_id}")
        logger.debug(f"Sending SUBSCRIBE packet: {subscribe_packet.hex(' ')}")
        await self.websocket.send(subscribe_packet)

    async def subscribe_to_status(self, user_id: str) -> None:
        """ユーザーステータスをサブスクライブ"""
        if self.state != ConnectionState.CONNECTED:
            logger.error("Not connected to MQTT broker")
            return

        topic = f"status/{user_id}"
        subscribe_packet = self._create_subscribe_packet(topic)
        logger.debug(f"Subscribing to status: {user_id}")
        logger.debug(f"Sending SUBSCRIBE packet: {subscribe_packet.hex(' ')}")
        await self.websocket.send(subscribe_packet)

    async def handle_message(self, message: str | bytes) -> None:
        """受信メッセージの処理"""
        try:
            if isinstance(message, bytes):
                packet_type = message[0] >> 4
                logger.debug(f"Received packet type: {packet_type}")
                logger.debug(f"Raw message: {message.hex(' ')}")

                if packet_type == 3:  # PUBLISH
                    # Extract topic length
                    topic_length = struct.unpack("!H", message[2:4])[0]
                    # Extract topic
                    topic = message[4 : 4 + topic_length].decode("utf-8")
                    # Extract payload
                    payload = message[4 + topic_length :]

                    try:
                        payload_str = payload.decode("utf-8")
                        payload_json = json.loads(payload_str)

                        if topic.startswith("works."):
                            # Line Works通知メッセージの処理
                            if "chTitle" in payload_json:
                                logger.info(
                                    f"Channel: {payload_json['chTitle']}",
                                )
                                if (
                                    "loc-args0" in payload_json
                                    and "loc-args1" in payload_json
                                ):
                                    sender = payload_json["loc-args0"]
                                    message_content = payload_json["loc-args1"]
                                    logger.info(
                                        f"Message from {sender}: {message_content}",
                                    )

                                # その他の重要な情報
                                logger.debug(
                                    f"Channel No: {payload_json.get('chNo')}",
                                )
                                logger.debug(
                                    f"Message No: {payload_json.get('messageNo')}",
                                )
                                logger.debug(
                                    f"Create Time: {payload_json.get('createTime')}",
                                )

                                # メッセージタイプの判定
                                message_type = payload_json.get("nType")
                                if message_type == 1:
                                    logger.info("Message type: Text message")
                                elif message_type == 2:
                                    logger.info("Message type: Image")
                                elif message_type == 3:
                                    logger.info("Message type: File")
                                # 他のメッセージタイプも必要に応じて追加

                        elif topic.startswith("channel/"):
                            logger.info(f"Channel message on {topic}")
                            logger.info(f"Content: {payload_json}")

                        elif topic.startswith("status/"):
                            # ステータス更新の処理
                            status_info = {
                                "user_id": payload_json.get("userNo"),
                                "status": payload_json.get("status"),
                                "timestamp": payload_json.get("timestamp"),
                            }
                            logger.info(f"Status update: {status_info}")

                        else:
                            logger.info(
                                f"Other message on topic {topic}: {payload_json}",
                            )

                    except json.JSONDecodeError:
                        logger.warning(f"Non-JSON payload on topic {topic}")
                        logger.debug(f"Raw payload: {payload}")
                    except UnicodeDecodeError:
                        logger.warning("Failed to decode payload as UTF-8")
                        logger.debug(f"Raw payload: {payload.hex(' ')}")

                elif packet_type == 9:  # SUBACK
                    message_id = struct.unpack("!H", message[2:4])[0]
                    return_code = message[4]
                    logger.info(
                        f"Subscription confirmed: message_id={message_id}, return_code={return_code}",
                    )

                elif packet_type == 13:  # PINGRESP
                    logger.debug("Received PINGRESP")

            else:
                logger.warning(f"Received non-binary message: {message}")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            logger.exception("Full traceback:")

    async def connect(self) -> None:
        """WebSocket接続を確立し、MQTTハンドシェイクを実行"""
        retry_count = 0

        while retry_count < self.config.max_retries:
            try:
                self.state = ConnectionState.CONNECTING
                async with websockets.connect(
                    self.WEBSOCKET_URL,
                    extra_headers=self._create_headers(),
                    ping_interval=self.config.ping_interval,
                    ping_timeout=self.config.ping_timeout,
                    subprotocols=["mqtt"],
                    compression=None,
                    max_size=None,
                ) as websocket:
                    self.websocket = websocket
                    logger.info("WebSocket connection established")

                    # Send CONNECT packet
                    connect_packet = self._create_mqtt_connect_packet()
                    logger.debug(
                        f"Sending CONNECT packet: {connect_packet.hex(' ')}",
                    )
                    await websocket.send(connect_packet)

                    # Wait for CONNACK
                    if not await self._wait_for_connack():
                        logger.error("Failed to receive CONNACK")
                        await asyncio.sleep(self.config.retry_interval)
                        continue

                    self.state = ConnectionState.CONNECTED
                    logger.info("MQTT connection established")

                    # Subscribe to own status and notifications
                    user_id = self.cookies.get("WORKS_USER_ID", "")
                    await self.subscribe_to_status(user_id)
                    await self.subscribe_to_channel(f"works.{user_id}")

                    # メインループ
                    while True:
                        try:
                            message = await websocket.recv()
                            await self.handle_message(message)
                        except websockets.exceptions.ConnectionClosed as e:
                            logger.warning(
                                f"Connection closed in main loop: {e}",
                            )
                            break

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
                self.state = ConnectionState.DISCONNECTED
                retry_count += 1
                await asyncio.sleep(self.config.retry_interval)

            except Exception as e:
                logger.error(f"Connection error: {e}")
                logger.exception("Full traceback:")
                self.state = ConnectionState.DISCONNECTED
                retry_count += 1
                await asyncio.sleep(self.config.retry_interval)

            logger.info("Attempting to reconnect...")

        logger.error("Max retries reached. Stopping connection attempts.")


async def main():
    client = LineWorksWS()
    try:
        await client.connect()
    except KeyboardInterrupt:
        logger.info("Program terminated by user")
    except Exception as e:
        logger.error(f"Error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())

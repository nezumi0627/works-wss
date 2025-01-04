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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, cast

import websockets
import websockets.client
from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    WebSocketException,
)
from websockets.legacy.client import WebSocketClientProtocol
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
    PacketError,
    StatusFlag,
    logger,
)
from core.logging import setup_logging
from message import (
    MessageType,
    StickerInfo,
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
from mqtt.packet.parser import parse_publish


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
                        f"再接続を試みます... "
                        f"({self.current_retry}/{self.config.max_retries})"
                    )
                    # Exponential backoff for retry delay
                    retry_delay = self.config.retry_interval * (
                        2 ** (self.current_retry - 1)
                    )
                    logger.info(f"待機時間: {retry_delay}秒")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(ERROR_MESSAGES["MAX_RETRIES_EXCEEDED"])
                    break

    async def connect(self) -> None:
        """WebSocket接続を確立し、MQTTセッションを開始します."""
        try:
            logger.info("-" * 50)
            logger.info("WebSocket接続を開始します")
            logger.info(f"接続先: {self.ws_config.url}")
            logger.info(f"プロトコル: {self.ws_config.subprotocol}")
            logger.debug(f"Origin: {self.ws_config.origin}")
            logger.debug(f"User-Agent: {self.ws_config.user_agent}")
            logger.debug("Cookie情報:")
            for cookie in self.cookies.split("; "):
                if any(
                    k in cookie.lower()
                    for k in ["session", "token", "user", "login"]
                ):
                    logger.debug(f"  {cookie}")

            self.state = StatusFlag.CONNECTING
            logger.info(f"接続状態: {self.state.name}")

            websocket = await websockets.connect(
                self.ws_config.url,
                ssl=ssl.create_default_context(),
                additional_headers=self.headers,
                subprotocols=[self.ws_config.subprotocol],
                ping_interval=None,
            )
            self.ws = cast(WebSocketClientProtocol, websocket)
            logger.info("WebSocket接続が確立されました")

            logger.info("-" * 50)
            logger.info("MQTT接続を開始します")
            logger.debug(
                f"プロトコルバージョン: {self.config.protocol_version}"
            )
            logger.debug(f"キープアライブ間隔: {self.config.keep_alive}秒")
            logger.debug(f"PING送信間隔: {self.config.ping_interval}秒")
            logger.debug(f"PING応答タイムアウト: {self.config.ping_timeout}秒")

            await self._mqtt_connect()
            self.state = StatusFlag.CONNECTED
            logger.info(f"接続状態: {self.state.name}")

            self.current_retry = 0
            logger.info("メッセージ監視を開始します")
            logger.info("-" * 50)

            await asyncio.gather(self._start_keepalive(), self.listen())

        except InvalidHandshake as err:
            self.state = StatusFlag.DISCONNECTED
            logger.error("-" * 50)
            logger.error(f"認証エラー: {err}")
            logger.error(f"接続状態: {self.state.name}")
            logger.error("-" * 50)
            raise AuthenticationError(
                ERROR_MESSAGES["AUTHENTICATION_FAILED"].format(reason=str(err))
            ) from err
        except websockets.exceptions.ConnectionClosed as err:
            self.state = StatusFlag.DISCONNECTED
            logger.error("-" * 50)
            logger.error(f"切断: コード {err.code}, 理由: {err.reason}")
            logger.error(f"接続状態: {self.state.name}")
            logger.error("-" * 50)
            raise ConnectionError(
                ERROR_MESSAGES["CONNECTION_CLOSED"].format(
                    code=err.code, reason=err.reason
                )
            ) from err
        except (
            WebSocketException,
            ConnectionError,
            asyncio.CancelledError,
        ) as err:
            self.state = StatusFlag.DISCONNECTED
            logger.error("-" * 50)
            logger.error(f"接続エラー: {err}")
            logger.error(f"接続状態: {self.state.name}")
            logger.error("-" * 50)
            raise ConnectionError(
                ERROR_MESSAGES["CONNECTION_FAILED"].format(reason=str(err))
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

        logger.debug(f"CONNECT送信 (クライアントID: {client_id})")
        logger.debug(f"パケット: {packet.packet.hex(' ')}")
        await self.ws.send(cast(Data, packet.packet))

    async def listen(self) -> None:
        """受信メッセージを監視します."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        try:
            logger.info("メッセージ監視タスクを開始します")
            async for message in self.ws:
                if isinstance(message, bytes):
                    await self._handle_binary_message(message)
                else:
                    logger.warning(
                        f"バイナリ以外のメッセージを受信: {message}"
                    )
        except ConnectionClosed as err:
            logger.error(f"WebSocket接続が切断されました: {err}")
            raise
        except asyncio.CancelledError:
            logger.info("メッセージ監視タスクを終了します")
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

            # パケットを処理
            await self._process_packet(packet)

        except Exception as err:
            logger.error(f"パケット処理エラー: {err}")

    async def _process_packet(self, packet: MQTTPacket) -> None:
        """MQTTパケットを処理します."""
        try:
            if packet.packet_type == PacketType.PUBLISH:
                topic, payload, message_id = parse_publish(packet)
                logger.debug(f"受信: {packet.packet_type.name}")
                logger.debug(f"パケット: {packet.packet.hex(' ')}")

                try:
                    if message := parse_message(payload):
                        await self._route_message(topic, message)

                    await self._handle_qos(packet, message_id)
                except json.JSONDecodeError as err:
                    logger.error(f"JSONデコードエラー: {err}")

            elif packet.packet_type == PacketType.CONNACK:
                logger.info("MQTT接続完了")
                logger.debug(f"パケット: {packet.packet.hex(' ')}")
            elif packet.packet_type == PacketType.PINGRESP:
                logger.debug("PING応答受信")
                logger.debug(f"パケット: {packet.packet.hex(' ')}")
            elif packet.packet_type == PacketType.SUBACK:
                self._handle_suback(packet)
                logger.debug(f"パケット: {packet.packet.hex(' ')}")

        except Exception as err:
            logger.error(f"パケット処理エラー: {err}")

    async def _route_message(self, topic: str, message: WorksMessage) -> None:
        """メッセージを適切なハンドラーにルーティングします."""
        try:
            if "nType" in message.body:
                await self._handle_notification(message)
            elif message.command == MessageType.CMD_READ:
                await self._handle_read_receipt(message)
            elif message.command == MessageType.GROUP_INFO:
                await self._handle_group_info(message)
            elif message.command == MessageType.AWAY_STATUS:
                await self._handle_away_status(message)
            elif message.command == MessageType.KICK_STATUS:
                await self._handle_kick_status(message)
            elif message.command == MessageType.KICKED:
                await self._handle_kicked(message)
            elif "msgTypeCode" in message.body:
                await self._handle_chat_message(message)
        except Exception as err:
            logger.error(f"メッセージルーティングエラー: {err}")

    async def _handle_notification(self, message: WorksMessage) -> None:
        """通知メッセージを処理します."""
        msg_type = message.body.get("nType", 0)

        if msg_type == MessageType.NOTIFICATION_BADGE:
            await self._handle_badge_update(message)
            return

        ch_type = message.body.get("chType", 0)
        ch_title = message.body.get("chTitle", "")
        status = message.body.get("sType", "不明")

        channel_type_name = get_channel_type_name(ch_type)
        message_type_name = get_message_type_name(msg_type)

        logger.info(
            f"通知: {ch_title} "
            f"({channel_type_name}, {message_type_name}, "
            f"ステータス: {status})"
        )

        if msg_type == MessageType.NOTIFICATION_MESSAGE:
            logger.debug(
                f"メッセージ詳細: "
                f"送信者={message.body.get('loc-args0', '')}, "
                f"内容={message.body.get('loc-args1', '')}"
            )
        elif msg_type == MessageType.NOTIFICATION_STICKER:
            self._log_sticker_info(message)

    def _log_sticker_info(self, message: WorksMessage) -> None:
        """スタンプ情報をログに出力します."""
        try:
            extras = json.loads(message.body.get("extras", "{}"))
            sticker_info = StickerInfo(
                sticker_type=extras.get("stkType", "none"),
                package_id=extras.get("pkgId", ""),
                sticker_id=extras.get("stkId", ""),
                options=extras.get("stkOpt"),
            )
            logger.debug(
                f"スタンプ詳細: "
                f"タイプ={sticker_info.sticker_type}, "
                f"パッケージ={sticker_info.package_id}, "
                f"ID={sticker_info.sticker_id}"
            )
        except json.JSONDecodeError:
            logger.warning("スタンプ情報の解析に失敗しました")

    async def _handle_read_receipt(self, message: WorksMessage) -> None:
        """既読通知を処理します."""
        body = message.body
        logger.info(
            f"既読通知: チャンネル {message.channel_id} "
            f"メッセージ #{body.get('msgSn')} "
            f"ユーザー {body.get('readerId')}"
        )

    async def _handle_chat_message(self, message: WorksMessage) -> None:
        """チャットメッセージを処理します."""
        msg_type = message.body.get("msgTypeCode", 0)
        ch_type = message.body.get("chType", 0)

        channel_type_name = get_channel_type_name(ch_type)
        message_type_name = get_message_type_name(msg_type)

        logger.info(
            f"メッセージ: チャンネル {message.channel_id} "
            f"({channel_type_name}, {message_type_name})"
        )

        if msg_type == MessageType.NORMAL:
            logger.debug(f"テキスト内容: {message.body.get('content', '')}")
        elif msg_type == MessageType.LEAVE:
            user_id = message.body.get("userId", "")
            user_name = message.body.get("userName", "")
            logger.info(
                f"退出通知: {user_name} (ID: {user_id}) が "
                f"チャンネル {message.channel_id} から退出しました"
            )
        elif msg_type == MessageType.INVITE:
            inviter = message.body.get("inviter", {})
            invitee = message.body.get("invitee", {})
            logger.info(
                f"招待通知: {inviter.get('name', '')} が "
                f"{invitee.get('name', '')} を "
                f"チャンネル {message.channel_id} に招待しました"
            )
        elif msg_type == MessageType.KICKED:
            kicked_user = message.body.get("kickedUser", {})
            logger.info(
                f"キック通知: {kicked_user.get('name', '')} が "
                f"チャンネル {message.channel_id} からキックされました"
            )
            logger.debug(
                f"キック詳細: ID={kicked_user.get('id', '')}, "
                f"理由={kicked_user.get('reason', '')}"
            )
        elif msg_type == MessageType.AWAY:
            user = message.body.get("user", {})
            logger.info(
                f"不在通知: {user.get('name', '')} が "
                f"チャンネル {message.channel_id} で不在になりました"
            )
            logger.debug(f"不在理由: {message.body.get('reason', '')}")

    async def stop(self) -> None:
        """クライアントを停止します."""
        self.running = False
        if self.ws:
            try:
                packet = build_disconnect_packet()
                logger.debug("DISCONNECT送信")
                await self.ws.send(cast(Data, packet.packet))
                await self.ws.close()
                self.state = StatusFlag.DISCONNECTED
                logger.debug(f"状態: {self.state.name}")
            except Exception as e:
                logger.error(f"切断エラー: {e}")

    async def _start_keepalive(self) -> None:
        """定期的にキープアライブパケットを送信します."""
        while self.running:
            try:
                await asyncio.sleep(self.config.ping_interval)
                if self.ws and not self.ws.close:
                    await self._send_pingreq()
            except (
                WebSocketException,
                ConnectionError,
                asyncio.CancelledError,
            ) as e:
                if not isinstance(e, asyncio.CancelledError):
                    logger.error(f"キープアライブエラー: {e}")
                break

    async def _send_pingreq(self) -> None:
        """MQTT PINGREQパケットを送信します."""
        if not self.ws:
            raise ConnectionError("WebSocket connection not established")

        try:
            packet = build_ping_packet()
            logger.debug("PING送信")
            logger.debug(f"パケット: {packet.packet.hex(' ')}")
            await self.ws.send(cast(Data, packet.packet))
        except Exception as e:
            logger.error(f"PING送信エラー: {e}")

    def _is_duplicate_message(self, payload: dict) -> bool:
        """メッセージが重複しているかチェックします.

        Args:
            payload: メッセージペイロード

        Returns:
            bool: 重複している場合はTrue
        """
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

    async def _handle_qos(
        self, packet: MQTTPacket, message_id: Optional[int]
    ) -> None:
        """QoS処理を行います.

        Args:
            packet: MQTTパケット
            message_id: メッセージID
        """
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
        """SUBACKパケットを処理します.

        Args:
            packet: SUBACKパケット
        """
        message_id = packet.get_message_id()
        if message_id in self._pending_messages:
            self._pending_messages[message_id].set_result(True)

    async def _handle_group_info(self, message: WorksMessage) -> None:
        """グループ情報更新を処理します."""
        body = message.body
        extras = json.loads(body.get("extras", "{}"))

        logger.info(
            f"グループ情報更新: チャンネル {message.channel_id} "
            f"タイトル: {extras.get('title', '')}"
        )

        active_users = extras.get("activeUserList", [])
        if active_users:
            logger.info(f"メンバー数: {len(active_users)}")
            logger.debug("アクティブユーザー:")
            for user in active_users:
                logger.debug(
                    f"  {user.get('name', '')} "
                    f"(ID: {user.get('id', '')}, "
                    f"ドメイン: {user.get('domainId', '')})"
                )

        # 新規参加者の情報
        if "inviter" in extras and extras["inviter"].get("id"):
            inviter = extras["inviter"]
            logger.info(
                f"新規参加: 招待者 {inviter.get('name', '')} "
                f"(ID: {inviter.get('id', '')})"
            )

    async def _handle_away_status(self, message: WorksMessage) -> None:
        """不在ステータス更新を処理します."""
        body = message.body
        extras = json.loads(body.get("extras", "{}"))

        away_users = extras.get("awayUserList", [])
        if away_users:
            logger.info(
                f"不在ステータス更新: チャンネル {message.channel_id} "
                f"不在ユーザー数: {extras.get('awayUserCount', 0)}"
            )
            logger.debug("不在ユーザー:")
            for user in away_users:
                logger.debug(
                    f"  {user.get('name', '')} "
                    f"(ID: {user.get('id', '')}, "
                    f"理由: {user.get('reason', '')})"
                )

    async def _handle_kick_status(self, message: WorksMessage) -> None:
        """キック状態更新を処理します."""
        body = message.body
        extras = json.loads(body.get("extras", "{}"))

        kicked_user = extras.get("kickedUser", {})
        if kicked_user:
            logger.info(f"キック状態更新: チャンネル {message.channel_id}")
            logger.debug(
                f"キックされたユーザー: {kicked_user.get('name', '')} "
                f"(ID: {kicked_user.get('id', '')}, "
                f"ドメイン: {kicked_user.get('domainId', '')}, "
                f"理由: {kicked_user.get('reason', '')})"
            )

    async def _handle_kicked(self, message: WorksMessage) -> None:
        """キックされた通知を処理します."""
        body = message.body
        extras = json.loads(body.get("extras", "{}"))

        kicked_user = extras.get("kickedUser", {})
        if kicked_user:
            logger.info(
                f"キックされた通知: チャンネル {message.channel_id} "
                f"ユーザー: {kicked_user.get('name', '')}"
            )
            logger.debug(
                f"詳細: ID={kicked_user.get('id', '')}, "
                f"ドメイン={kicked_user.get('domainId', '')}, "
                f"理由={kicked_user.get('reason', '')}"
            )

    async def _handle_badge_update(self, message: WorksMessage) -> None:
        """バッジ更新通知を処理します."""
        body = message.body
        logger.info(
            f"バッジ更新: "
            f"ドメイン {body.get('domain_id', '')}, "
            f"ユーザー {body.get('userNo', '')}"
        )
        logger.debug(
            f"バッジ詳細: "
            f"badge={body.get('badge', 0)}, "
            f"cBadge={body.get('cBadge', 0)}, "
            f"aBadge={body.get('aBadge', 0)}, "
            f"mBadge={body.get('mBadge', 0)}, "
            f"hBadge={body.get('hBadge', 0)}, "
            f"wpaBadge={body.get('wpaBadge', 0)}"
        )


async def main() -> None:
    """アプリケーションのメインエントリーポイント."""
    # ロギングの設定を初期化
    setup_logging(level=logging.DEBUG)  # デバッグレベルで詳細なログを出力

    client = WMQTTClient()
    try:
        await client.start()
    except KeyboardInterrupt:
        logger.info("シャットダウンを開始します...")
        await client.stop()
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}")
        await client.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())

"""MQTT packet models.

MQTTパケットの構造を表現するデータモデルを提供するモジュール。
"""

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple


class MQTTMessageType(IntEnum):
    """MQTTメッセージタイプの定義."""

    CONNECT = 1
    CONNACK = 2
    PUBLISH = 3
    PUBACK = 4
    SUBSCRIBE = 8
    SUBACK = 9
    PINGREQ = 12
    PINGRESP = 13
    DISCONNECT = 14


@dataclass
class MQTTHeader:
    """MQTTヘッダー情報を保持するデータクラス."""

    message_type: int
    dup_flag: bool
    qos_level: int
    retain: bool
    remaining_length: int

    @classmethod
    def from_bytes(cls, data: bytes) -> "MQTTHeader":
        """バイトデータからMQTTヘッダーを解析する.

        Args:
            data: MQTTパケットの先頭バイト

        Returns:
            MQTTHeader: 解析されたヘッダー情報

        Raises:
            ValueError: パケットが短すぎる、または不正な形式の場合
        """
        if len(data) < 2:
            raise ValueError("Invalid MQTT packet: too short")

        first_byte = data[0]
        message_type = (first_byte & 0xF0) >> 4
        dup_flag = bool((first_byte & 0x08) >> 3)
        qos_level = (first_byte & 0x06) >> 1
        retain = bool(first_byte & 0x01)

        # 可変長の残りの長さを解析
        multiplier = 1
        remaining_length = 0
        index = 1

        while True:
            if index >= len(data):
                raise ValueError("Malformed remaining length")

            byte = data[index]
            remaining_length += (byte & 127) * multiplier
            multiplier *= 128

            if not byte & 128:
                break

            if multiplier > 128 * 128 * 128:
                raise ValueError("Malformed remaining length")

            index += 1

        return cls(
            message_type=message_type,
            dup_flag=dup_flag,
            qos_level=qos_level,
            retain=retain,
            remaining_length=remaining_length,
        )


@dataclass
class MQTTPacket:
    """MQTTパケット全体を表現するデータクラス."""

    header: MQTTHeader
    payload: bytes

    @classmethod
    def create_connect(
        cls,
        client_id: str,
        protocol_version: int = 4,
        keep_alive: int = 60,
        username: Optional[str] = None,
        password: Optional[str] = None,
        clean_session: bool = True,
    ) -> "MQTTPacket":
        """CONNECT パケットを生成する."""
        protocol_name = b"\x00\x04MQTT"
        protocol_level = bytes([protocol_version])

        connect_flags = 0
        if clean_session:
            connect_flags |= 0x02
        if username is not None:
            connect_flags |= 0x80
        if password is not None:
            connect_flags |= 0x40

        keep_alive_bytes = struct.pack("!H", keep_alive)

        # ペイロードの構築
        payload = cls._encode_string(client_id)
        if username is not None:
            payload += cls._encode_string(username)
        if password is not None:
            payload += cls._encode_string(password)

        # 可変ヘッダーとペイロードの結合
        variable_header = (
            protocol_name
            + protocol_level
            + bytes([connect_flags])
            + keep_alive_bytes
        )
        complete_payload = variable_header + payload

        header = MQTTHeader(
            message_type=MQTTMessageType.CONNECT,
            dup_flag=False,
            qos_level=0,
            retain=False,
            remaining_length=len(complete_payload),
        )

        return cls(header=header, payload=complete_payload)

    @classmethod
    def create_subscribe(
        cls,
        topic: str,
        message_id: int,
        qos: int = 0,
    ) -> "MQTTPacket":
        """SUBSCRIBE パケットを生成する."""
        payload = (
            struct.pack("!H", message_id)
            + cls._encode_string(topic)
            + bytes([qos])
        )

        header = MQTTHeader(
            message_type=MQTTMessageType.SUBSCRIBE,
            dup_flag=False,
            qos_level=1,  # SUBSCRIBEは常にQoS 1
            retain=False,
            remaining_length=len(payload),
        )

        return cls(header=header, payload=payload)

    @classmethod
    def create_puback(cls, message_id: int) -> "MQTTPacket":
        """PUBACK パケットを生成する."""
        payload = struct.pack("!H", message_id)

        header = MQTTHeader(
            message_type=MQTTMessageType.PUBACK,
            dup_flag=False,
            qos_level=0,
            retain=False,
            remaining_length=len(payload),
        )

        return cls(header=header, payload=payload)

    @classmethod
    def create_pingreq(cls) -> "MQTTPacket":
        """PINGREQ パケットを生成する."""
        header = MQTTHeader(
            message_type=MQTTMessageType.PINGREQ,
            dup_flag=False,
            qos_level=0,
            retain=False,
            remaining_length=0,
        )
        return cls(header=header, payload=b"")

    def to_bytes(self) -> bytes:
        """パケットをバイト列に変換する."""
        first_byte = (
            (self.header.message_type << 4)
            | (int(self.header.dup_flag) << 3)
            | (self.header.qos_level << 1)
            | int(self.header.retain)
        )

        remaining_bytes = self._encode_remaining_length(
            self.header.remaining_length
        )
        return bytes([first_byte]) + remaining_bytes + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "MQTTPacket":
        """バイトデータからMQTTパケットを解析する."""
        header = MQTTHeader.from_bytes(data)
        payload_start = cls._calculate_payload_start(data)
        payload = data[payload_start : payload_start + header.remaining_length]
        return cls(header=header, payload=payload)

    def get_topic_and_payload(self) -> Tuple[str, bytes, Optional[int]]:
        """PUBLISHパケットからトピック、ペイロード、メッセージIDを取得する."""
        if self.header.message_type != MQTTMessageType.PUBLISH:
            raise ValueError("Not a PUBLISH packet") from None

        if len(self.payload) < 2:
            raise ValueError(
                "Invalid PUBLISH packet: payload too short"
            ) from None

        try:
            topic_length = struct.unpack("!H", self.payload[0:2])[0]
            if len(self.payload) < 2 + topic_length:
                raise ValueError(
                    "Invalid PUBLISH packet: topic length exceeds payload"
                ) from None

            topic = self.payload[2 : 2 + topic_length].decode("utf-8")

            # QoS > 0の場合、メッセージIDが含まれる
            message_id = None
            payload_start = 2 + topic_length

            if self.header.qos_level > 0:
                if len(self.payload) < payload_start + 2:
                    raise ValueError(
                        "Invalid PUBLISH packet: missing message ID"
                    ) from None
                message_id = struct.unpack(
                    "!H", self.payload[payload_start : payload_start + 2]
                )[0]
                payload_start += 2

            payload = self.payload[payload_start:]
            return topic, payload, message_id

        except (struct.error, UnicodeDecodeError) as err:
            raise ValueError(f"Failed to parse PUBLISH packet: {err}") from err

    def get_message_id(self) -> Optional[int]:
        """パケットからメッセージIDを取得する.

        Returns:
            Optional[int]: メッセージID（存在する場合）
        """
        try:
            if len(self.payload) >= 2:
                return struct.unpack("!H", self.payload[0:2])[0]
        except struct.error:
            pass
        return None

    @staticmethod
    def _encode_string(text: str) -> bytes:
        """文字列をMQTTエンコード形式に変換する."""
        encoded = text.encode("utf-8")
        return struct.pack("!H", len(encoded)) + encoded

    @staticmethod
    def _encode_remaining_length(length: int) -> bytes:
        """残りの長さをエンコードする."""
        remaining_bytes = []
        while True:
            byte = length % 128
            length = length // 128
            if length > 0:
                byte |= 0x80
            remaining_bytes.append(byte)
            if length == 0:
                break
        return bytes(remaining_bytes)

    @staticmethod
    def _calculate_payload_start(data: bytes) -> int:
        """ペイロードの開始位置を計算する."""
        if len(data) < 2:
            raise ValueError("Invalid packet: too short")

        index = 1
        while index < len(data):
            if not (data[index] & 0x80):
                return index + 1
            index += 1

        raise ValueError("Invalid packet: malformed remaining length")

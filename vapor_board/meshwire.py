"""Minimal Meshtastic protobuf wire codec for the few messages Vapor Board uses.

Hand-written so the app needs no third-party packages. Field numbers follow
meshtastic/protobufs mesh.proto (FromRadio, ToRadio, MeshPacket, Data, MyNodeInfo);
tests compare the output with the official Python bindings when they are installed.

Decoding returns plain dicts. Encoding covers only: want_config_id and heartbeat (local
TCP API control messages that never go on the air) and a direct text message.
"""
import struct
from .meshtastic_frames import MAGIC, MAX_PAYLOAD

TEXT_MESSAGE_APP = 1
BROADCAST = 0xFFFFFFFF
MAX_TEXT_BYTES = 200  # stays inside the 233-byte Data payload even with PKI overhead

FROM_RADIO_VARIANTS = {1: "id", 2: "packet", 3: "my_info", 4: "node_info", 5: "config", 6: "log_record",
                       7: "config_complete_id", 8: "rebooted", 9: "moduleConfig", 10: "channel", 11: "queueStatus",
                       12: "xmodemPacket", 13: "metadata", 14: "mqttClientProxyMessage", 15: "fileInfo",
                       16: "clientNotification", 17: "deviceuiConfig"}


class WireError(ValueError):
    """Bytes that are not a well-formed protobuf message."""


# ---- low-level wire format -------------------------------------------------------------
def _varint(value):
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(data, index):
    shift = result = 0
    while True:
        if index >= len(data):
            raise WireError("truncated varint")
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, index
        shift += 7
        if shift > 63:
            raise WireError("varint too long")


def fields(data):
    """[(field number, wire type, value)] for one message. Length-delimited values are bytes."""
    data = bytes(data)
    index, out = 0, []
    while index < len(data):
        key, index = _read_varint(data, index)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise WireError("field number 0")
        if wire == 0:
            value, index = _read_varint(data, index)
        elif wire == 1:
            if index + 8 > len(data):
                raise WireError("truncated 64-bit field")
            value, index = struct.unpack_from("<Q", data, index)[0], index + 8
        elif wire == 2:
            size, index = _read_varint(data, index)
            if index + size > len(data):
                raise WireError("truncated length-delimited field")
            value, index = data[index:index + size], index + size
        elif wire == 5:
            if index + 4 > len(data):
                raise WireError("truncated 32-bit field")
            value, index = struct.unpack_from("<I", data, index)[0], index + 4
        else:
            raise WireError(f"unsupported wire type {wire}")
        out.append((number, wire, value))
    return out


def _first(parsed, number, default=None):
    return next((value for n, _wire, value in parsed if n == number), default)


def _key(number, wire):
    return _varint((number << 3) | wire)


def _len_field(number, payload):
    return _key(number, 2) + _varint(len(payload)) + payload


def _fixed32(number, value):
    return _key(number, 5) + struct.pack("<I", value & 0xFFFFFFFF)


def _uint(number, value):
    return _key(number, 0) + _varint(value)


def frame(payload):
    """Meshtastic TCP stream frame: 0x94 0xC3, 2-byte big-endian length, protobuf bytes."""
    if not 0 < len(payload) <= MAX_PAYLOAD:
        raise ValueError("frame payload must be 1–512 bytes")
    return MAGIC + len(payload).to_bytes(2, "big") + payload


# ---- decoding --------------------------------------------------------------------------
def node_id(number):
    """'!a1b2c3d4' text form of a node number."""
    return f"!{number & 0xFFFFFFFF:08x}"


def decode_from_radio(payload):
    """A small dict describing one FromRadio message.

    Text is included only for TEXT_MESSAGE_APP packets; other payloads are not exposed.
    """
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise WireError("nonempty payload required")
    parsed = fields(payload)
    variant = next((FROM_RADIO_VARIANTS[n] for n, _w, _v in parsed if n in FROM_RADIO_VARIANTS and n != 1), "unknown")
    if variant == "my_info":
        info = fields(_first(parsed, 3, b""))
        return {"variant": "my_info", "node_num": _first(info, 1, 0)}
    if variant != "packet":
        return {"variant": variant}
    packet = fields(_first(parsed, 2, b""))
    decoded = _first(packet, 4)
    result = {"variant": "packet", "from": _first(packet, 1, 0), "to": _first(packet, 2, 0),
              "channel": _first(packet, 3, 0), "id": _first(packet, 6, 0), "via_mqtt": bool(_first(packet, 14, 0)),
              "encrypted": decoded is None and _first(packet, 5) is not None, "portnum": None, "text": None}
    if decoded is not None:
        data = fields(decoded)
        result["portnum"] = _first(data, 1, 0)
        if result["portnum"] == TEXT_MESSAGE_APP:
            result["text"] = bytes(_first(data, 2, b"")).decode("utf-8", errors="replace")
    return result


# ---- encoding --------------------------------------------------------------------------
def want_config(nonce):
    """ToRadio{want_config_id}: asks the radio over TCP to start streaming. Nothing goes on the air."""
    if not 1 <= nonce <= 0xFFFFFFFF:
        raise ValueError("nonce must be a nonzero 32-bit number")
    return frame(_uint(3, nonce))


def heartbeat():
    """ToRadio{heartbeat}: keeps the TCP API session open. Nothing goes on the air."""
    return frame(_len_field(7, b""))


def text_message(destination, text, packet_id, channel=0, hop_limit=3, want_ack=True):
    """ToRadio{packet}: one direct text message to a single node. Broadcasts are refused."""
    if not 1 <= destination < BROADCAST:
        raise ValueError("a single destination node is required; broadcasts are not sent")
    body = text.encode("utf-8")
    if not 0 < len(body) <= MAX_TEXT_BYTES:
        raise ValueError(f"text must be 1–{MAX_TEXT_BYTES} bytes")
    if not 1 <= packet_id <= 0xFFFFFFFF:
        raise ValueError("packet id must be a nonzero 32-bit number")
    data = _uint(1, TEXT_MESSAGE_APP) + _len_field(2, body)
    packet = (_fixed32(2, destination) + (_uint(3, channel) if channel else b"") + _len_field(4, data)
              + _fixed32(6, packet_id) + _uint(9, hop_limit) + (_uint(10, 1) if want_ack else b""))
    return frame(_len_field(1, packet))


def split_text(text, limit=MAX_TEXT_BYTES, parts=3):
    """Split a reply into at most `parts` chunks of at most `limit` UTF-8 bytes, on word boundaries."""
    words, chunks, current = text.split(" "), [], ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if len(candidate.encode("utf-8")) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(word.encode("utf-8")) > limit:  # a single very long word
            cut = limit
            while len(word[:cut].encode("utf-8")) > limit:
                cut -= 1
            chunks.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        chunks.append(current)
    if len(chunks) > parts:
        chunks = chunks[:parts]
        last = chunks[-1]
        while len((last + "…").encode("utf-8")) > limit:
            last = last[:-1]
        chunks[-1] = last.rstrip() + "…"
    return chunks

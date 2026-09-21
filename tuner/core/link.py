"""The tuner's side of the ECU link.

The framing here has to agree byte for byte with fw/src/proto.c. It is
written twice on purpose: the firmware cannot import Python and the
tuner should not need a C toolchain to run. tests/test_serial_link.py
drives this code against the real firmware binary, so the two cannot
drift apart without a test going red.

    A5 5A  cmd  len_lo len_hi  payload...  crc_lo crc_hi
"""
import struct
import zlib

import numpy as np

from .connection import CHANNELS, ECUConnection, ProtocolError

SYNC = b"\xA5\x5A"
VERSION = 1

CMD_IDENTIFY = 0x01
CMD_DESCRIBE = 0x02
CMD_READ_TABLE = 0x03
CMD_WRITE_CELL = 0x04
CMD_WRITE_TABLE = 0x05
CMD_BURN = 0x06
CMD_TABLE_CRC = 0x07
CMD_CHANNELS = 0x08

CH_OP_DESCRIBE = 0x00
CH_OP_VALUES = 0x01
CHAN_NAME_LEN = 16

STATUS = {
    0x00: "ok",
    0x01: "unknown command",
    0x02: "wrong payload length",
    0x03: "no such table",
    0x04: "index outside the table",
    0x05: "value the ECU will not accept",
    0x06: "the tune does not fit this ECU's layout",
    0x07: "not allowed in this state",
}


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE, matching proto_crc16 in the firmware."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def frame(cmd: int, payload: bytes = b"") -> bytes:
    head = bytes([cmd]) + struct.pack("<H", len(payload))
    return SYNC + head + payload + struct.pack("<H", crc16(head + payload))


class FrameReader:
    """Reassembles frames from a byte stream that may deliver them in any
    sized pieces, and recovers if it is joined mid-frame."""

    def __init__(self):
        self.buf = bytearray()
        self.dropped = 0
        self.bad_crc = 0

    def feed(self, data: bytes):
        self.buf.extend(data)
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                # keep one byte in case a sync marker straddles the split
                if len(self.buf) > 1:
                    self.dropped += len(self.buf) - 1
                    del self.buf[:-1]
                return
            if i:
                self.dropped += i
                del self.buf[:i]
            if len(self.buf) < 7:
                return
            n = struct.unpack("<H", self.buf[3:5])[0]
            if n > 1024:
                self.bad_crc += 1
                del self.buf[:2]
                continue
            if len(self.buf) < n + 7:
                return
            body = bytes(self.buf[2:5 + n])
            want = struct.unpack("<H", self.buf[5 + n:7 + n])[0]
            cmd = self.buf[2]
            payload = bytes(self.buf[5:5 + n])
            del self.buf[:n + 7]
            if crc16(body) != want:
                self.bad_crc += 1
                continue
            yield cmd, payload


class SerialConnection(ECUConnection):
    """An ECU on the other end of a byte stream.

    `stream` is anything with read(n) and write(b): a pyserial port, a
    socket file, or a subprocess pipe. Nothing here knows which.
    """

    name = "ECU (serial)"
    writable = True

    def __init__(self, stream, table_keys=None, timeout_reads=4096):
        super().__init__()
        self.stream = stream
        self.reader = FrameReader()
        self._pending = []
        self._timeout_reads = timeout_reads
        self._keys = list(table_keys) if table_keys else []
        self._index = {}
        self._desc = {}
        self._chan_keys = []
        self._chan_hash = 0

    # -- transport ------------------------------------------------------
    def _exchange(self, cmd: int, payload: bytes = b"") -> bytes:
        # A cable pulled mid-session is an ordinary event in a workshop.
        # It has to arrive as something the UI can show, not as an OSError
        # out of the transport layer.
        try:
            self.stream.write(frame(cmd, payload))
            flush = getattr(self.stream, "flush", None)
            if flush:
                flush()
        except OSError as e:
            self._fail(f"lost the link to the ECU: {e}")

        for _ in range(self._timeout_reads):
            while self._pending:
                rcmd, rpl = self._pending.pop(0)
                if rcmd == cmd:
                    return self._check(cmd, rpl)
            try:
                chunk = self.stream.read(1)
            except OSError as e:
                self._fail(f"lost the link to the ECU: {e}")
            if not chunk:
                self._fail("the ECU stopped responding")
            self._pending.extend(self.reader.feed(chunk))
        self._fail(f"no reply to command 0x{cmd:02X}")

    def _fail(self, message: str):
        """Report a dead link once, mark the connection down, and raise."""
        if self._connected:
            self._connected = False
            self.state_changed.emit(False)
        self.error.emit(message)
        raise ProtocolError(message)

    @staticmethod
    def _check(cmd: int, payload: bytes) -> bytes:
        if not payload:
            raise ProtocolError(f"empty reply to command 0x{cmd:02X}")
        status = payload[0]
        if status != 0:
            raise ProtocolError(STATUS.get(status, f"status 0x{status:02X}"))
        return payload[1:]

    # -- the contract ---------------------------------------------------
    def connect_ecu(self):
        ident = self.identify()
        if ident["protocol_version"] != VERSION:
            raise ProtocolError(
                f"ECU speaks protocol version {ident['protocol_version']}, "
                f"this tuner speaks {VERSION}")
        self._load_layout(ident["n_tables"])
        self.describe_channels()
        super().connect_ecu()

    def identify(self) -> dict:
        body = self._exchange(CMD_IDENTIFY)
        if len(body) < 22:
            raise ProtocolError("truncated identify reply")
        version, n_tables = body[0], body[1]
        name = body[2:18].split(b"\x00")[0].decode("ascii", "replace")
        layout = struct.unpack("<I", body[18:22])[0]
        return {"ecu_id": name, "firmware": name, "protocol_version": version,
                "n_tables": n_tables, "layout_hash": f"{layout:08x}"}

    def _load_layout(self, n_tables: int):
        self._index, self._desc = {}, {}
        for i in range(n_tables):
            body = self._exchange(CMD_DESCRIBE, bytes([i]))
            key = body[0:16].split(b"\x00")[0].decode("ascii", "replace")
            n_x, n_y = body[16], body[17]
            lo, hi = struct.unpack("<ff", body[18:26])
            self._index[key] = i
            self._desc[key] = {"n_x": n_x, "n_y": n_y, "lo": lo, "hi": hi,
                               "unit": ""}

    def describe_tables(self) -> dict:
        if not self._desc:
            self._load_layout(self.identify()["n_tables"])
        return dict(self._desc)

    def _idx(self, key: str) -> int:
        if key not in self._index:
            raise ProtocolError(f"this ECU has no table {key!r}")
        return self._index[key]

    def read_table(self, key: str):
        body = self._exchange(CMD_READ_TABLE, bytes([self._idx(key)]))
        n_x, n_y = body[0], body[1]
        off = 2 + 4 * (n_x + n_y)
        vals = np.frombuffer(body, dtype="<f4", count=n_x * n_y,
                             offset=off).astype(float)
        return vals.reshape(n_y, n_x)

    def read_axes(self, key: str):
        body = self._exchange(CMD_READ_TABLE, bytes([self._idx(key)]))
        n_x, n_y = body[0], body[1]
        x = np.frombuffer(body, dtype="<f4", count=n_x, offset=2).astype(float)
        y = np.frombuffer(body, dtype="<f4", count=n_y,
                          offset=2 + 4 * n_x).astype(float)
        return x, y

    def write_cell(self, key: str, j: int, i: int, value: float):
        idx = self._idx(key)
        d = self._desc[key]
        if not (0 <= j < d["n_y"] and 0 <= i < d["n_x"]):
            raise ProtocolError(f"{key}[{j},{i}] is outside the ECU layout "
                                f"({d['n_y']}x{d['n_x']})")
        body = self._exchange(
            CMD_WRITE_CELL,
            bytes([idx, j, i]) + struct.pack("<f", float(value)))
        echoed = struct.unpack("<f", body[:4])[0]
        self.write_acked.emit(key, j, i, float(echoed))
        return echoed

    def write_table(self, key: str, values, x=None, y=None):
        idx = self._idx(key)
        d = self._desc[key]
        values = np.asarray(values, dtype="<f4")
        if values.shape != (d["n_y"], d["n_x"]):
            raise ProtocolError(f"{key}: {values.shape} does not fit the ECU "
                                f"layout ({d['n_y']}, {d['n_x']})")
        if x is None or y is None:
            x, y = self.read_axes(key)
        payload = (bytes([idx, d["n_x"], d["n_y"]])
                   + np.asarray(x, dtype="<f4").tobytes()
                   + np.asarray(y, dtype="<f4").tobytes()
                   + values.tobytes())
        body = self._exchange(CMD_WRITE_TABLE, payload)
        return struct.unpack("<I", body[:4])[0]

    def table_crc(self, key: str) -> int:
        body = self._exchange(CMD_TABLE_CRC, bytes([self._idx(key)]))
        return struct.unpack("<I", body[:4])[0]

    # -- live data ------------------------------------------------------
    # The ECU owns the channel list. The tuner asks for it at connect and
    # keeps the order it was given, because the values come back as a
    # bare block of floats indexed by that order -- which is also why the
    # hash is checked on every poll. A firmware that gained a channel
    # would otherwise shift every gauge one place to the left and look
    # entirely plausible doing it.
    def describe_channels(self) -> list:
        body = self._exchange(CMD_CHANNELS, bytes([CH_OP_DESCRIBE]))
        if len(body) < 5:
            raise ProtocolError("truncated channel list")
        count = body[0]
        self._chan_hash = struct.unpack("<I", body[1:5])[0]
        want = 5 + count * CHAN_NAME_LEN
        if len(body) < want:
            raise ProtocolError(
                f"the ECU described {count} channels and sent "
                f"{(len(body) - 5) // CHAN_NAME_LEN}")
        keys = []
        for i in range(count):
            off = 5 + i * CHAN_NAME_LEN
            name = body[off:off + CHAN_NAME_LEN].split(b"\x00")[0]
            keys.append(name.decode("ascii", "replace"))
        self._chan_keys = keys
        return list(keys)

    def poll_channels(self) -> dict:
        if not self._chan_keys:
            self.describe_channels()
        body = self._exchange(CMD_CHANNELS, bytes([CH_OP_VALUES]))
        if len(body) < 5:
            raise ProtocolError("truncated channel reply")
        count = body[0]
        hash_ = struct.unpack("<I", body[1:5])[0]
        if count != len(self._chan_keys) or hash_ != self._chan_hash:
            # Not recoverable by reading it anyway: these values belong
            # to a channel list this tuner has never seen.
            self._chan_keys = []
            raise ProtocolError(
                "the ECU's channel list changed under the connection")
        values = np.frombuffer(body, dtype="<f4", count=count,
                               offset=5).astype(float)
        self._channels.update(dict(zip(self._chan_keys, values.tolist())))
        self.channels_updated.emit(self.channels())
        return self.channels()

    def burn(self) -> dict:
        body = self._exchange(CMD_BURN)
        n = body[0]
        crcs = struct.unpack(f"<{n}I", body[1:1 + 4 * n])
        by_index = {i: c for i, c in enumerate(crcs)}
        return {key: by_index[i] for key, i in self._index.items()}


def expected_crc(key: str, x, y, values) -> int:
    """What the ECU should report for this table, computed the same way
    it does: key, axes and values as little-endian float32."""
    b = (np.ascontiguousarray(x, dtype="<f4").tobytes()
         + np.ascontiguousarray(y, dtype="<f4").tobytes()
         + np.ascontiguousarray(values, dtype="<f4").tobytes())
    return zlib.crc32(key.encode() + b) & 0xFFFFFFFF


__all__ = ["SerialConnection", "FrameReader", "frame", "crc16",
           "expected_crc", "CHANNELS"]

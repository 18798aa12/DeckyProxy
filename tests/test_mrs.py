"""MRS envelopes are bounded before the privileged core parses their strategy."""
import ctypes
import ctypes.util
import struct

import pytest
from decky_proxy.errors import ProxyError
from decky_proxy.mrs import validate_mrs


def compress(value: bytes) -> bytes:
    path = ctypes.util.find_library("zstd") or "/opt/homebrew/lib/libzstd.dylib"
    if not path:
        pytest.skip("system libzstd unavailable")
    try:
        library = ctypes.CDLL(path)
    except OSError:
        pytest.skip("system libzstd unavailable")
    library.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    library.ZSTD_compressBound.restype = ctypes.c_size_t
    library.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    library.ZSTD_compress.restype = ctypes.c_size_t
    output = ctypes.create_string_buffer(library.ZSTD_compressBound(len(value)))
    size = library.ZSTD_compress(output, len(output), value, len(value), 3)
    return output.raw[:size]


def domain_strategy() -> bytes:
    # One domain, "x": one edge/root-child, terminal node 1, LOUDS bits 110.
    return (b"\x01" + struct.pack(">qQ", 1, 2) + struct.pack(">qQ", 1, 6)
            + struct.pack(">q", 1) + b"x")


def ip_strategy() -> bytes:
    return b"\x01" + struct.pack(">q", 1) + b"\x00" * 16 + b"\xff" * 16


def envelope(behavior: int = 0, count: int = 1, extra: int = 0,
             strategy: bytes | None = None) -> bytes:
    if strategy is None:
        strategy = domain_strategy() if behavior == 0 else ip_strategy()
    return b"MRS\x01" + bytes([behavior]) + struct.pack(">qq", count, extra) + strategy


def test_valid_mrs_envelope():
    validate_mrs(compress(envelope()), "domain")
    validate_mrs(compress(envelope(1)), "ipcidr")


@pytest.mark.parametrize("payload", [b"garbage", b"\x28\xb5\x2f\xfdtruncated",
                                     b"not-MRS", envelope(count=-1),
                                     envelope(count=2_000_001), envelope(extra=1000000),
                                     envelope(1)])
def test_invalid_mrs_rejected(payload):
    with pytest.raises(ProxyError):
        validate_mrs(compress(payload) if payload.startswith((b"MRS", b"not-"))
                     else payload, "domain")


def test_decompression_limit_enforced(monkeypatch):
    monkeypatch.setattr("decky_proxy.mrs.MAX_EXPANDED_BYTES", 64)
    with pytest.raises(ProxyError):
        validate_mrs(compress(envelope() + b"a" * 1000), "domain")


def test_absent_system_library_is_clear_error(monkeypatch):
    monkeypatch.setattr("decky_proxy.mrs._load_library", lambda: None)
    with pytest.raises(ProxyError, match="libzstd"):
        validate_mrs(compress(envelope()), "domain")


@pytest.mark.parametrize("strategy", [
    b"", b"\x00" + domain_strategy()[1:], b"\x01" + struct.pack(">q", 1 << 60),
    b"\x01" + struct.pack(">q", -1), b"\x01" + struct.pack(">q", 0),
    b"\x01" + struct.pack(">qQq", 1, 2, 1 << 60),
    b"\x01" + struct.pack(">qQq", 1, 2, -1),
    b"\x01" + struct.pack(">qQqQq", 1, 2, 1, 6, 1 << 60),
    b"\x01" + struct.pack(">qQqQq", 1, 2, 1, 6, -1),
    domain_strategy()[:-1], domain_strategy() + b"trailing",
])
def test_domain_internal_allocation_lengths_are_bounded(strategy):
    with pytest.raises(ProxyError):
        validate_mrs(compress(envelope(strategy=strategy)), "domain")


@pytest.mark.parametrize("strategy", [
    b"", b"\x00" + ip_strategy()[1:], b"\x01" + struct.pack(">q", 1 << 60),
    b"\x01" + struct.pack(">q", -1), b"\x01" + struct.pack(">q", 0),
    ip_strategy()[:-1], ip_strategy() + b"trailing",
])
def test_ipcidr_internal_allocation_lengths_are_bounded(strategy):
    with pytest.raises(ProxyError):
        validate_mrs(compress(envelope(1, strategy=strategy)), "ipcidr")


def test_bounded_mrs_extra_section_supported():
    validate_mrs(compress(envelope(extra=2, strategy=b"xx" + domain_strategy())), "domain")

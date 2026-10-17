"""Bound Zstandard expansion and all pinned MRSv1 allocation lengths."""
import ctypes
import ctypes.util
import struct
import sys

from .errors import ProxyError

MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_RULE_COUNT = 2_000_000


def _load_library() -> ctypes.CDLL | None:
    name = "libzstd.so.1" if sys.platform == "linux" else (
        ctypes.util.find_library("zstd") or "/opt/homebrew/lib/libzstd.dylib")
    if not name:
        return None
    try:
        return ctypes.CDLL(name)
    except OSError:
        return None


def validate_mrs(payload: bytes, behavior: str) -> None:
    library = _load_library()
    if library is None:
        raise ProxyError("MRS 规则需要系统 libzstd；可改用 YAML/text 规则集")
    library.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                      ctypes.c_void_p, ctypes.c_size_t]
    library.ZSTD_decompress.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    output = ctypes.create_string_buffer(MAX_EXPANDED_BYTES)
    size = library.ZSTD_decompress(output, MAX_EXPANDED_BYTES, payload, len(payload))
    if library.ZSTD_isError(size) or size < 21 or size > MAX_EXPANDED_BYTES:
        raise ProxyError("MRS 压缩内容无效或解压后超过 32 MiB")
    data = memoryview(output).cast("B")[:size]
    header = data[:21]
    expected = {"domain": 0, "ipcidr": 1}.get(behavior)
    if bytes(header[:4]) != b"MRS\x01" or header[4] != expected:
        raise ProxyError("MRS 文件格式或 behavior 不匹配")
    count, extra = struct.unpack(">qq", header[5:])
    if not 1 <= count <= MAX_RULE_COUNT or not 0 <= extra <= min(65536, size - 21):
        raise ProxyError("MRS 规则条数或扩展字段超过限制")
    _validate_strategy(data, 21 + extra, behavior)


def _validate_strategy(data: memoryview, offset: int, behavior: str) -> None:
    # Pinned Mihomo domain_set_bin.go/ipcidr_set_bin.go allocate before reading
    # each section. The outer rule count does not bound these independent int64
    # lengths, so check every multiplication against the bytes actually present.
    if offset >= len(data) or data[offset] != 1:
        raise ProxyError("MRS 策略版本或内容无效")
    offset += 1
    widths = (8, 8, 1) if behavior == "domain" else (32,)
    for width in widths:
        if offset + 8 > len(data):
            raise ProxyError("MRS 策略长度字段不完整")
        count = struct.unpack_from(">q", data, offset)[0]
        offset += 8
        if count < 1 or count > (len(data) - offset) // width:
            raise ProxyError("MRS 策略字段长度超过文件内容限制")
        offset += count * width
    if offset != len(data):
        raise ProxyError("MRS 策略包含多余或无效内容")

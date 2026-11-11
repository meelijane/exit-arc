"""Read and write Mozilla's .jsonlz4 files (mozLz40) without the lz4 package.

Format: 8-byte magic b"mozLz40\\0", uint32 little-endian decompressed size,
then one LZ4 block. The writer emits a single literal run, which is always a
valid LZ4 block (just not compressed). Firefox and Zen read it fine.
"""

import json
import os
import struct
from pathlib import Path

MAGIC = b"mozLz40\0"


def _decode_block(src, size):
    dst = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(dst):
            raise ValueError("corrupt LZ4 block (bad offset)")
        match = token & 15
        if match == 15:
            while True:
                b = src[i]
                i += 1
                match += b
                if b != 255:
                    break
        match += 4
        start = len(dst) - offset
        for k in range(match):  # byte by byte: matches may overlap themselves
            dst.append(dst[start + k])
    if len(dst) != size:
        raise ValueError(f"corrupt LZ4 block (got {len(dst)} bytes, expected {size})")
    return bytes(dst)


def _encode_literals(data):
    n = len(data)
    out = bytearray()
    if n < 15:
        out.append(n << 4)
    else:
        out.append(0xF0)
        rest = n - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    return bytes(out) + data


def decompress(raw):
    if raw[:8] != MAGIC:
        raise ValueError("not a mozLz4 file")
    (size,) = struct.unpack("<I", raw[8:12])
    return _decode_block(raw[12:], size)


def compress(data):
    return MAGIC + struct.pack("<I", len(data)) + _encode_literals(data)


def read(path):
    return decompress(Path(path).read_bytes())


def write(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(compress(data))
    os.replace(tmp, path)


def read_json(path):
    return json.loads(read(path).decode("utf-8"))


def write_json(path, obj):
    write(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

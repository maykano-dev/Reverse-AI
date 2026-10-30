"""Dependency-free image decoding for embedding in generated files.

Supports the two formats that matter for documents:
  * JPEG  - embedded as-is (PDF /DCTDecode), only the dimensions are parsed.
  * PNG   - 8-bit truecolor (RGB) or truecolor+alpha (RGBA), non-interlaced,
            decoded to raw RGB bytes (alpha flattened over white).

Returns a small record the PDF/OOXML writers can embed. No Pillow, no numpy.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass


class ImageError(Exception):
    pass


@dataclass
class DecodedImage:
    width: int
    height: int
    fmt: str                 # "jpeg" | "rgb"
    data: bytes              # jpeg: original file bytes; rgb: raw RGB samples
    raw_jpeg: bytes = b""    # original bytes (for OOXML, which embeds the file)
    mime: str = ""


def _jpeg_dims(data: bytes) -> tuple[int, int]:
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0..SOF15 except DHT(C4)/DAC(CC)/RSTn carry frame dims.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg_len
    raise ImageError("could not read JPEG dimensions")


def _decode_png(data: bytes) -> DecodedImage:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageError("not a PNG")
    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # 4 len + 4 type + data + 4 crc
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", chunk[:13])
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise ImageError("unsupported PNG (need 8-bit RGB/RGBA, non-interlaced)")
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    out = bytearray(width * height * 3)
    prev = bytearray(stride)
    p = 0
    oi = 0
    for _ in range(height):
        ftype = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        _unfilter(line, prev, ftype, channels)
        prev = line
        if channels == 3:
            out[oi:oi + stride] = line
            oi += stride
        else:  # RGBA -> flatten over white
            for x in range(0, stride, 4):
                a = line[x + 3]
                if a == 255:
                    out[oi] = line[x]; out[oi + 1] = line[x + 1]; out[oi + 2] = line[x + 2]
                else:
                    ia = 255 - a
                    out[oi] = (line[x] * a + 255 * ia) // 255
                    out[oi + 1] = (line[x + 1] * a + 255 * ia) // 255
                    out[oi + 2] = (line[x + 2] * a + 255 * ia) // 255
                oi += 3
    return DecodedImage(width=width, height=height, fmt="rgb", data=bytes(out),
                        mime="image/png")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(line: bytearray, prev: bytearray, ftype: int, bpp: int) -> None:
    if ftype == 0:
        return
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        x = line[i]
        if ftype == 1:
            line[i] = (x + a) & 0xFF
        elif ftype == 2:
            line[i] = (x + b) & 0xFF
        elif ftype == 3:
            line[i] = (x + ((a + b) >> 1)) & 0xFF
        elif ftype == 4:
            line[i] = (x + _paeth(a, b, c)) & 0xFF
        else:
            raise ImageError(f"bad PNG filter {ftype}")


def decode_image(data: bytes) -> DecodedImage:
    if not data or len(data) < 8:
        raise ImageError("empty image")
    if data[:2] == b"\xff\xd8":
        w, h = _jpeg_dims(data)
        return DecodedImage(width=w, height=h, fmt="jpeg", data=data,
                            raw_jpeg=data, mime="image/jpeg")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        img = _decode_png(data)
        img.raw_jpeg = data  # original PNG bytes, for OOXML embedding
        return img
    raise ImageError("unsupported image format (use PNG or JPEG)")

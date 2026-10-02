"""Bounded wire format and trusted PNG reconstruction; no image decoder in the API."""

from __future__ import annotations

import socket
import struct
import zlib

MAX_IMAGE_INPUT = 8 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 4_000_000
MAX_IMAGE_OUTPUT = MAX_IMAGE_PIXELS * 4 + 65536
IMAGE_SOCKET = "/run/office-images/decoder.sock"


class OfficeImageInvalid(ValueError):
    pass


class OfficeImageUnavailable(RuntimeError):
    pass


def image_dimensions(width: int, height: int) -> None:
    if not (
        1 <= width <= MAX_IMAGE_DIMENSION and 1 <= height <= MAX_IMAGE_DIMENSION and width * height <= MAX_IMAGE_PIXELS
    ):
        raise OfficeImageInvalid("Image dimensions exceed the admitted limits")


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        part = connection.recv(min(65536, length - len(result)))
        if not part:
            raise OfficeImageUnavailable("Image decoder response is incomplete")
        result.extend(part)
    return bytes(result)


def png_from_pixels(width: int, height: int, rgba: bytes) -> bytes:
    image_dimensions(width, height)
    if len(rgba) != width * height * 4:
        raise OfficeImageInvalid("Image pixel count is invalid")

    def chunk(kind: bytes, content: bytes) -> bytes:
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))

    stride = width * 4
    rows = b"".join(b"\0" + rgba[offset : offset + stride] for offset in range(0, len(rgba), stride))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def normalize_image(content: bytes, mime_type: str, *, socket_path: str = IMAGE_SOCKET) -> tuple[bytes, int, int]:
    if not 1 <= len(content) <= MAX_IMAGE_INPUT or mime_type not in {"image/png", "image/jpeg"}:
        raise OfficeImageInvalid("Only bounded PNG and JPEG files are supported")
    kind = b"P" if mime_type == "image/png" else b"J"
    if (kind == b"P" and not content.startswith(b"\x89PNG\r\n\x1a\n")) or (
        kind == b"J" and not content.startswith(b"\xff\xd8\xff")
    ):
        raise OfficeImageInvalid("Image signature does not match its media type")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(12)
            connection.connect(socket_path)
            connection.sendall(kind + struct.pack(">I", len(content)) + content)
            header = receive_exact(connection, 9)
            if header[:1] != b"O":
                raise OfficeImageInvalid("Image could not be normalized")
            width, height = struct.unpack(">II", header[1:])
            image_dimensions(width, height)
            pixels = receive_exact(connection, width * height * 4)
            return png_from_pixels(width, height, pixels), width, height
    except (OSError, TimeoutError) as exc:
        raise OfficeImageUnavailable("Image decoder unavailable") from exc

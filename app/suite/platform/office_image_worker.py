"""Credential-free, network-none decoder. Each file is decoded in a fresh bounded child."""

from __future__ import annotations

import io
import os
import resource
import socket
import struct
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

from suite.platform.office_image_codec import IMAGE_SOCKET, MAX_IMAGE_INPUT, MAX_IMAGE_PIXELS, image_dimensions, receive_exact


def decode() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_IMAGE_PIXELS * 4 + 9, MAX_IMAGE_PIXELS * 4 + 9))
    from PIL import Image, ImageOps  # type: ignore[import-not-found]

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    data = sys.stdin.buffer.read(MAX_IMAGE_INPUT + 2)
    if not 2 <= len(data) <= MAX_IMAGE_INPUT + 1:
        raise ValueError("Invalid image input")
    expected = {b"P": "PNG", b"J": "JPEG"}[data[:1]]
    with Image.open(io.BytesIO(data[1:]), formats=[expected]) as source:
        image_dimensions(*source.size)
        if source.format != expected or getattr(source, "n_frames", 1) != 1:
            raise ValueError("Unsupported image")
        source.load()
        # Apply camera orientation, then return only pixels. EXIF/ICC/text are not retained.
        result = ImageOps.exif_transpose(source).convert("RGBA")
        image_dimensions(*result.size)
        sys.stdout.buffer.write(b"O" + struct.pack(">II", *result.size) + result.tobytes())


def serve() -> None:
    path = Path(IMAGE_SOCKET)
    path.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        os.chmod(path, 0o660)
        server.listen(8)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(12)
                try:
                    header = receive_exact(connection, 5)
                    length = struct.unpack(">I", header[1:])[0]
                    if header[:1] not in {b"P", b"J"} or not 1 <= length <= MAX_IMAGE_INPUT:
                        raise ValueError("Invalid decoder request")
                    content = receive_exact(connection, length)
                    with tempfile.TemporaryFile() as output:
                        subprocess.run(
                            [sys.executable, "-m", "suite.platform.office_image_worker", "decode"],
                            input=header[:1] + content, stdout=output, stderr=subprocess.DEVNULL,
                            timeout=8, check=True, env={"PYTHONPATH": "/workspace/app", "PYTHONDONTWRITEBYTECODE": "1"},
                        )
                        output.seek(0)
                        connection.sendall(output.read(MAX_IMAGE_PIXELS * 4 + 9))
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    try:
                        connection.sendall(b"E" + b"\0" * 8)
                    except OSError:
                        pass


if __name__ == "__main__":
    if sys.argv[1:] == ["decode"]:
        decode()
    elif not sys.argv[1:]:
        serve()
    else:
        raise SystemExit(2)

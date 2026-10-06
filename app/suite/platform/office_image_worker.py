"""Credential-free, network-none decoder. Each file is decoded in a fresh bounded child."""

from __future__ import annotations

import io
import math
import os
import re
import resource
import socket
import struct
import subprocess
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

from suite.platform.office_image_codec import (
    IMAGE_SOCKET,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_INPUT,
    MAX_IMAGE_OUTPUT,
    MAX_IMAGE_PIXELS,
    image_dimensions,
    receive_exact,
)

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
SVG_BLOCKED_ELEMENTS = {"script", "foreignObject", "iframe", "object", "embed", "audio", "video"}
SVG_BLOCKED_CSS = re.compile(r"@import|url\s*\(\s*(?!#)", re.IGNORECASE)
EPS_BOUNDING_BOX = re.compile(
    rb"^%%(?:HiRes)?BoundingBox:\s*([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+"
    rb"([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)


def _bounded_raster_size(width: float, height: float, *, minimum_long_edge: int) -> tuple[int, int]:
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError("Invalid vector dimensions")
    scale = max(1.0, minimum_long_edge / max(width, height))
    scale = min(scale, MAX_IMAGE_DIMENSION / width, MAX_IMAGE_DIMENSION / height)
    scale = min(scale, math.sqrt(MAX_IMAGE_PIXELS / (width * height)))
    result = max(1, round(width * scale)), max(1, round(height * scale))
    image_dimensions(*result)
    return result


def _svg_length(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?|\.\d+)\s*(px|pt|pc|mm|cm|in)?\s*", value)
    if not match:
        raise ValueError("Unsupported SVG dimension")
    factors = {None: 1.0, "px": 1.0, "pt": 96 / 72, "pc": 16.0, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0}
    result = float(match.group(1)) * factors[match.group(2)]
    if result <= 0:
        raise ValueError("Invalid SVG dimension")
    return result


def svg_raster_size(content: bytes) -> tuple[int, int]:
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered or b"<?xml-stylesheet" in lowered:
        raise ValueError("Unsafe SVG declaration")
    text = content.decode("utf-8-sig")
    root = ET.fromstring(text)
    if root.tag != f"{{{SVG_NAMESPACE}}}svg" and root.tag != "svg":
        raise ValueError("Invalid SVG root")
    nodes = 0
    for element in root.iter():
        nodes += 1
        if nodes > 10_000 or element.tag.rsplit("}", 1)[-1] in SVG_BLOCKED_ELEMENTS:
            raise ValueError("Unsupported SVG content")
        if element.text and SVG_BLOCKED_CSS.search(element.text):
            raise ValueError("External SVG resource")
        for name, value in element.attrib.items():
            local_name = name.rsplit("}", 1)[-1].lower()
            if local_name.startswith("on") or SVG_BLOCKED_CSS.search(value):
                raise ValueError("Active SVG content")
            if local_name in {"href", "src"} and value.strip() and not value.strip().startswith("#"):
                raise ValueError("External SVG resource")
    width, height = _svg_length(root.get("width")), _svg_length(root.get("height"))
    view_box = root.get("viewBox") or root.get("viewbox")
    if view_box:
        try:
            _, _, view_width, view_height = (float(entry) for entry in re.split(r"[\s,]+", view_box.strip()))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid SVG viewBox") from exc
        if width is None and height is None:
            width, height = view_width, view_height
        elif width is None and height is not None:
            width = height * view_width / view_height
        elif height is None and width is not None:
            height = width * view_height / view_width
    return _bounded_raster_size(width or 300, height or 150, minimum_long_edge=1600)


def eps_raster_profile(content: bytes) -> tuple[int, int, float]:
    first_line = content.splitlines()[0] if content else b""
    if not first_line.startswith(b"%!PS-Adobe-") or b" EPSF-" not in first_line:
        raise ValueError("Only EPS input is accepted")
    matches = list(EPS_BOUNDING_BOX.finditer(content))
    if not matches:
        raise ValueError("EPS bounding box is required")
    values = tuple(float(value) for value in matches[-1].groups())
    width, height = values[2] - values[0], values[3] - values[1]
    output_width, output_height = _bounded_raster_size(width * 2, height * 2, minimum_long_edge=800)
    dpi = min(600.0, output_width * 72.0 / width, output_height * 72.0 / height)
    return output_width, output_height, dpi


def rasterize_vector(kind: bytes, content: bytes, directory: Path) -> bytes:
    output = directory / "normalized.png"
    environment = {"HOME": str(directory), "TMPDIR": str(directory), "PATH": "/usr/bin:/bin"}
    if kind == b"S":
        width, height = svg_raster_size(content)
        source = directory / "source.svg"
        command = [
            "/usr/bin/cairosvg", str(source), "--output", str(output),
            "--output-width", str(width), "--output-height", str(height),
        ]
    else:
        width, height, dpi = eps_raster_profile(content)
        source = directory / "source.eps"
        command = [
            "/usr/bin/gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop",
            "-dFirstPage=1", "-dLastPage=1", "-sDEVICE=pngalpha", "-dBackgroundColor=16#00000000",
            f"-r{dpi:.6f}", f"-sOutputFile={output}", str(source),
        ]
    source.write_bytes(content)
    subprocess.run(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=8, check=True, env=environment,
    )
    if not output.is_file() or not 1 <= output.stat().st_size <= MAX_IMAGE_PIXELS * 4 + 65536:
        raise ValueError("Invalid vector rendition")
    return output.read_bytes()


def decode() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_IMAGE_OUTPUT, MAX_IMAGE_OUTPUT))
    from PIL import Image, ImageOps  # type: ignore[import-not-found]

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    data = sys.stdin.buffer.read(MAX_IMAGE_INPUT + 2)
    if not 2 <= len(data) <= MAX_IMAGE_INPUT + 1:
        raise ValueError("Invalid image input")
    kind, content = data[:1], data[1:]
    expected = {b"P": "PNG", b"J": "JPEG", b"S": "PNG", b"E": "PNG"}[kind]
    if kind in {b"S", b"E"}:
        with tempfile.TemporaryDirectory() as directory:
            content = rasterize_vector(kind, content, Path(directory))
    with Image.open(io.BytesIO(content), formats=[expected]) as source:
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
                    if header[:1] not in {b"P", b"J", b"S", b"E"} or not 1 <= length <= MAX_IMAGE_INPUT:
                        raise ValueError("Invalid decoder request")
                    content = receive_exact(connection, length)
                    with tempfile.TemporaryFile() as output:
                        subprocess.run(
                            [sys.executable, "-m", "suite.platform.office_image_worker", "decode"],
                            input=header[:1] + content,
                            stdout=output,
                            stderr=subprocess.DEVNULL,
                            timeout=8,
                            check=True,
                            env={"PYTHONPATH": "/workspace/app", "PYTHONDONTWRITEBYTECODE": "1"},
                        )
                        output.seek(0)
                        connection.sendall(output.read(MAX_IMAGE_PIXELS * 4 + 9))
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    with suppress(OSError):
                        connection.sendall(b"E" + b"\0" * 8)


if __name__ == "__main__":
    if sys.argv[1:] == ["decode"]:
        decode()
    elif not sys.argv[1:]:
        serve()
    else:
        raise SystemExit(2)

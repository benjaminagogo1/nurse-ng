"""Inspect conversation files in a bounded child process before release.

The parent storage layer invokes this parser as a child process. Type checks
examine actual bytes rather than trusting extensions; passing validation is
separate from malware scanning and permission to download.
"""

import io
import json
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

DOCUMENTS = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".rtf": "application/rtf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}
IMAGES = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "GIF"}
MEDIA = {
    ".mp3": ("audio", "audio/mpeg", "mp3"),
    ".wav": ("audio", "audio/wav", "wav"),
    ".m4a": ("audio", "audio/mp4", "mov"),
    ".aac": ("audio", "audio/aac", "aac"),
    ".ogg": ("audio", "audio/ogg", "ogg"),
    ".opus": ("audio", "audio/ogg", "ogg"),
    ".flac": ("audio", "audio/flac", "flac"),
    ".mp4": ("video", "video/mp4", "mov"),
    ".m4v": ("video", "video/mp4", "mov"),
    ".mov": ("video", "video/quicktime", "mov"),
    ".webm": ("video", "video/webm", "matroska"),
}
EXTENSIONS = frozenset(DOCUMENTS) | frozenset(IMAGES) | frozenset(MEDIA)


def image(data, extension):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 20_000_000
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format != IMAGES[extension] or getattr(picture, "n_frames", 1) > 200:
                raise ValueError("Unsupported image")
            content_type = Image.MIME[picture.format]
            picture.verify()
        with Image.open(io.BytesIO(data)) as picture:
            pixels = 0
            for frame in range(getattr(picture, "n_frames", 1)):
                picture.seek(frame)
                pixels += picture.width * picture.height
                if pixels > 100_000_000:
                    raise ValueError("Image expands beyond its limit")
                picture.load()
    return content_type


def office(data, extension):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 2000 or len({e.filename for e in entries}) != len(entries):
            raise ValueError("Invalid office document")
        if sum(e.file_size for e in entries) > 100 * 1024 * 1024:
            raise ValueError("Document expands beyond its limit")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            lower = entry.filename.lower()
            if (
                entry.flag_bits & 1
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or entry.file_size > 20 * 1024 * 1024
                or entry.file_size > max(1, entry.compress_size) * 300
                or any(
                    name in lower for name in ("vbaproject", "activex/", "embeddings/", "scripts/")
                )
            ):
                raise ValueError("Unsupported embedded or encrypted content")
            if entry.is_dir():
                continue
            with archive.open(entry) as stream:
                payload = stream.read()
            if lower.endswith((".xml", ".rels")):
                if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
                    raise ValueError("Unsupported XML")
                tree = ElementTree.fromstring(payload)
                if b"macroenabled" in payload.lower() or b"script:script" in payload.lower():
                    raise ValueError("Macros are unavailable")
                if lower.endswith(".rels"):
                    for relation in tree:
                        if relation.get("TargetMode") == "External" and not relation.get(
                            "Type", ""
                        ).endswith("/hyperlink"):
                            raise ValueError("External document content is unavailable")
        names = {entry.filename for entry in entries}
        if extension in {".docx", ".xlsx", ".pptx"}:
            required, root_tag = {
                ".docx": ("word/document.xml", "document"),
                ".xlsx": ("xl/workbook.xml", "workbook"),
                ".pptx": ("ppt/presentation.xml", "presentation"),
            }[extension]
            if not {required, "[Content_Types].xml", "_rels/.rels"}.issubset(names):
                raise ValueError("Incomplete office document")
            root = ElementTree.fromstring(archive.read(required))
            if root.tag.rsplit("}", 1)[-1] != root_tag:
                raise ValueError("Wrong document type")
        else:
            if not {"mimetype", "content.xml", "META-INF/manifest.xml"}.issubset(names):
                raise ValueError("Incomplete document")
            if archive.read("mimetype").decode("ascii") != DOCUMENTS[extension]:
                raise ValueError("Wrong document type")


def media(path, data, extension):
    import imageio_ffmpeg

    kind, content_type, container = MEDIA[extension]
    signatures = {
        "mov": len(data) >= 12 and data[4:8] == b"ftyp",
        "wav": data[:4] == b"RIFF" and data[8:12] == b"WAVE",
        "ogg": data.startswith(b"OggS"),
        "flac": data.startswith(b"fLaC"),
        "matroska": data.startswith(b"\x1a\x45\xdf\xa3"),
        "mp3": data.startswith(b"ID3")
        or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224),
        "aac": len(data) > 1 and data[0] == 255 and data[1] & 246 == 240,
    }
    if not signatures[container]:
        raise ValueError("Wrong media type")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-max_alloc",
        "67108864",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        container,
    ]
    if container == "mov":
        command += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    command += [
        "-f",
        container,
        "-i",
        str(path.resolve()),
        "-map",
        "0:a:0" if kind == "audio" else "0:v:0",
        "-t",
        "0.1",
        "-threads",
        "1",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise ValueError("Incomplete media")
    return kind, content_type


def validate(path, extension):
    if extension not in EXTENSIONS or not 0 < path.stat().st_size <= 200 * 1024 * 1024:
        raise ValueError("Unsupported file")
    data = path.read_bytes()
    if extension in IMAGES:
        return {"kind": "image", "content_type": image(data, extension)}
    if extension in MEDIA:
        kind, content_type = media(path, data, extension)
        return {"kind": kind, "content_type": content_type}
    if extension == ".pdf":
        from app.core.evidence_validation import validate as validate_pdf

        if (
            not data.startswith(b"%PDF-")
            or validate_pdf(data, max_pdf_pages=500) != "application/pdf"
        ):
            raise ValueError("Invalid PDF")
    elif extension in {".txt", ".csv"}:
        text = data.decode("utf-16" if data[:2] in {b"\xff\xfe", b"\xfe\xff"} else "utf-8-sig")
        if any(ord(c) < 32 and c not in "\t\r\n" for c in text):
            raise ValueError("Invalid text")
    elif extension == ".rtf":
        if not data.startswith(b"{\\rtf") or any(
            word in data.lower() for word in (b"\\object", b"\\objdata", b"\\bin")
        ):
            raise ValueError("Invalid RTF")
    else:
        office(data, extension)
    return {"kind": "document", "content_type": DOCUMENTS[extension]}


if __name__ == "__main__":
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    try:
        print(json.dumps(validate(Path(sys.argv[1]), sys.argv[2])))
    except Exception:
        sys.exit(1)

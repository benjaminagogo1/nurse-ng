"""Parse untrusted documents in a short-lived process with memory and CPU limits."""

import io
import sys
import warnings
from pathlib import Path


def validate(data, *, max_pdf_pages=25):
    if data.startswith(b"%PDF-"):
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= max_pdf_pages:
            raise ValueError("Encrypted or oversized PDF")
        forbidden = {"/JS", "/JavaScript", "/Launch", "/EmbeddedFiles", "/EmbeddedFile",
                     "/RichMedia", "/XFA", "/OpenAction", "/AA", "/SubmitForm",
                     "/ImportData", "/GoToR", "/GoToE"}
        stack, seen, count, decoded = [reader.trailer], set(), 0, 0
        while stack:
            value = stack.pop()
            if isinstance(value, IndirectObject):
                key = (value.idnum, value.generation)
                if key in seen:
                    continue
                seen.add(key)
                value = value.get_object()
            count += 1
            if count > 50000:
                raise ValueError("PDF is too complex")
            if isinstance(value, DictionaryObject):
                if forbidden.intersection(value) or str(value.get("/S", "")) in forbidden:
                    raise ValueError("PDF contains active or embedded content")
                if isinstance(value, StreamObject):
                    decoded += len(value.get_data())
                    if decoded > 64 * 1024 * 1024:
                        raise ValueError("PDF expands beyond the document limit")
                stack.extend(value.values())
            elif isinstance(value, ArrayObject):
                stack.extend(value)
        for page in reader.pages:
            if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                raise ValueError("Invalid page dimensions")
        return "application/pdf"

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 20_000_000
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {"JPEG", "PNG"} or getattr(picture, "n_frames", 1) != 1:
                raise ValueError("Unsupported image")
            content_type = Image.MIME[picture.format]
            picture.verify()
        with Image.open(io.BytesIO(data)) as picture:
            picture.load()
    return content_type


if __name__ == "__main__":
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    try:
        print(validate(Path(sys.argv[1]).read_bytes()))
    except Exception:
        sys.exit(1)

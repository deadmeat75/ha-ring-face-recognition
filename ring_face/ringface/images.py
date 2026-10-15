import io
from datetime import datetime
import os
from pathlib import Path
import re
import stat
import time
import warnings
from PIL import Image, ImageOps

MAX_BYTES = 6 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 12_000_000
ID = re.compile(r"[A-Za-z0-9_-]{8,100}\Z")


def decode(raw, with_metadata=False):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Image must be between 1 byte and 6 MiB")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {"JPEG", "PNG"} or im.width * im.height > 12_000_000:
                raise ValueError("Only bounded JPEG/PNG images are accepted")
            exif = im.getexif()
            metadata = {"format":im.format, "width":im.width, "height":im.height,
                        "exif_datetime":str(exif.get(306,""))[:64] or None}
            # DateTimeOriginal may live inside the EXIF sub-IFD. It is diagnostic,
            # not authenticated source-frame evidence.
            try:
                original = exif.get_ifd(34665)
                metadata["exif_original"] = str(original.get(36867,""))[:64] or None
                metadata["exif_offset"] = str(original.get(36881,""))[:16] or None
            except (KeyError, ValueError, TypeError):
                pass
            im.load()
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1280, 1280))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=90)
            return (out.getvalue(), metadata) if with_metadata else out.getvalue()


def compare_metadata(metadata, captured_at):
    source = metadata.get("exif_original") or metadata.get("exif_datetime")
    offset = metadata.get("exif_offset")
    if not source:
        metadata["source_time_comparison"] = "unavailable"
    elif not offset:
        metadata["source_time_comparison"] = "timezone_missing"
    else:
        try:
            parsed = datetime.strptime(source, "%Y:%m:%d %H:%M:%S").replace(
                tzinfo=datetime.strptime(offset, "%z").tzinfo)
            age = captured_at - parsed.timestamp()
            metadata["source_age_seconds"] = round(age, 1)
            metadata["source_time_comparison"] = "outside_capture_window" if age > 120 or age < -5 else "within_window_unverified"
        except (ValueError, TypeError):
            metadata["source_time_comparison"] = "unparseable"
    return metadata


def capture_read(directory, event_id, attempt, captured_at):
    if not ID.fullmatch(event_id) or type(attempt) is not int or not 1 <= attempt <= 3:
        raise ValueError("Invalid capture identifier")
    directory = Path(directory)
    filename = f"{event_id}_{attempt}.jpg"
    # Open relative to a fixed directory; never follow a user-supplied symlink.
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError("Invalid capture file")
            if not captured_at - 5 <= info.st_mtime <= time.time() + 5 or time.time() - info.st_mtime > 120:
                raise ValueError("Capture file timestamp out of range")
            with os.fdopen(fd, "rb", closefd=False) as f:
                raw = f.read(MAX_BYTES + 1)
            image, metadata = decode(raw, with_metadata=True)
            metadata["file_mtime"] = info.st_mtime
            compare_metadata(metadata, captured_at)
            return image, metadata
        finally:
            os.close(fd)
    finally:
        os.close(dfd)

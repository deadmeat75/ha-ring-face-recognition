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


class CaptureError(ValueError):
    """A safe, specific handoff diagnostic without exposing image bytes."""
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"{code}: {detail}")


def share_mount_present(mountinfo=Path("/proc/self/mountinfo")):
    # stat-based is_mount() misses bind mounts on the same device. Supervisor
    # uses bind mounts; mountinfo is authoritative on Linux/HAOS.
    try:
        for line in Path(mountinfo).read_text().splitlines():
            fields = line.split()
            if len(fields) >= 6 and fields[4] == "/share" and "rw" in fields[5].split(","):
                return not Path("/share").is_symlink()
    except OSError:
        pass
    return False


def prepare_capture_directory(directory):
    directory = Path(directory)
    # /data keeps umask 077. Only these dedicated exchange directories are shared.
    # Never chmod /share itself or silently follow a replacement symlink.
    parent = directory.parent
    for path, mode in ((parent, 0o755), (directory, 0o1777)):
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(f"Unsafe snapshot exchange directory: {path}")
        path.chmod(mode)
    # Exercise an actual write/read/delete, rather than relying on os.access as root.
    import tempfile
    with tempfile.TemporaryFile(dir=directory) as probe:
        probe.write(b"handoff-check")
        probe.flush()
        probe.seek(0)
        if probe.read() != b"handoff-check":
            raise RuntimeError("Snapshot exchange self-check failed")


def capture_read(directory, event_id, attempt, captured_at):
    if not ID.fullmatch(event_id) or type(attempt) is not int or not 1 <= attempt <= 3:
        raise CaptureError("invalid_identifier", "Invalid capture identifier")
    directory = Path(directory)
    filename = f"{event_id}_{attempt}.jpg"
    if directory.parent.is_symlink():
        raise CaptureError("unsafe_file", "Exchange parent must not be a symlink")
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise CaptureError("unsafe_file", "Snapshot must be a regular file")
                if info.st_size == 0:
                    raise CaptureError("empty", "Snapshot file is empty")
                if info.st_size > MAX_BYTES:
                    raise CaptureError("too_large", "Snapshot exceeds 6 MiB")
                now = time.time()
                if not captured_at - 5 <= info.st_mtime <= now + 5 or now - info.st_mtime > 120:
                    raise CaptureError("stale", "Snapshot modification time is outside capture window")
                with os.fdopen(fd, "rb", closefd=False) as f:
                    raw = f.read(MAX_BYTES + 1)
                after = os.fstat(fd)
                if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise CaptureError("writing", "Snapshot changed during read; waiting for completion")
                try:
                    # Pillow may accept a JPEG without its end marker. A partially
                    # written capture must not be accepted just because it decodes.
                    if raw.startswith(b"\xff\xd8") and not raw.rstrip().endswith(b"\xff\xd9"):
                        raise ValueError("JPEG end marker missing")
                    image, metadata = decode(raw, with_metadata=True)
                except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                    raise CaptureError("invalid_image", "Snapshot is not a complete, valid JPEG/PNG") from error
                metadata["file_mtime"] = info.st_mtime
                compare_metadata(metadata, captured_at)
                return image, metadata
            finally:
                os.close(fd)
        finally:
            os.close(dfd)
    except FileNotFoundError as error:
        raise CaptureError("missing", "Snapshot file or exchange directory does not exist") from error
    except PermissionError as error:
        raise CaptureError("permission_denied", "Cannot read snapshot/exchange directory; check shared permissions") from error
    except OSError as error:
        import errno
        code = "unsafe_file" if error.errno in {errno.ELOOP, errno.ENOTDIR} else "io_error"
        raise CaptureError(code, f"Snapshot filesystem error (errno={error.errno})") from error


def wait_for_capture(directory, event_id, attempt, captured_at, timeout=10, stop=None):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return capture_read(directory, event_id, attempt, captured_at)
        except CaptureError as error:
            remaining = deadline - time.monotonic()
            if error.code in {"unsafe_file", "permission_denied", "invalid_identifier", "too_large"}:
                raise
            if remaining <= 0:
                raise CaptureError(error.code, f"After {timeout:g}s: {str(error).split(': ',1)[1]}") from error
            delay = min(0.25, remaining)
            if stop is not None:
                if stop.wait(delay):
                    raise CaptureError("cancelled", "App stopped while waiting for snapshot")
            else:
                time.sleep(delay)

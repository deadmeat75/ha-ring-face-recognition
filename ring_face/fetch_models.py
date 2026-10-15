"""Acquire immutable OpenCV Zoo models with mandatory upstream LFS SHA-256 checks."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request


def acquire(destination):
    spec = json.loads(Path(__file__).with_name("models.json").read_text())
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for model in spec["models"]:
        target = destination / model["file"]
        def valid(path):
            return path.exists() and path.stat().st_size == model["size"] and hashlib.sha256(path.read_bytes()).hexdigest() == model["sha256"]
        if valid(target):
            continue
        base = "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
        url = base + spec["source_commit"] + "/models/" + model["path"] + "/" + model["file"]
        temporary = target.with_suffix(".download")
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                while chunk := response.read(65536):
                    output.write(chunk)
            if not valid(temporary):
                raise RuntimeError("Model checksum/size mismatch: " + model["file"])
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        print("Verified", model["file"], model["sha256"])


if __name__ == "__main__":
    acquire(sys.argv[1])

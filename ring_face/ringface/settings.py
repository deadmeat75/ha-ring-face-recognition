import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass
class Settings:
    data: Path = Path("/data")
    captures: Path = Path("/share/ring_face/capture")
    models: Path = Path("/opt/models")
    mqtt_host: str = "core-mosquitto"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_tls: bool = False
    timezone: str = "America/Los_Angeles"
    similarity_threshold: float = 0.55
    ambiguity_margin: float = 0.08
    opencv_threads: int = 1
    processing_timeout: int = 20
    capture_timeout: int = 10
    history_days: int = 30
    image_days: int = 0

    def validate(self):
        ZoneInfo(self.timezone)
        if not 0.4 <= self.similarity_threshold <= 0.95 or not 0.01 <= self.ambiguity_margin <= 0.5:
            raise ValueError("Invalid recognition thresholds")
        if not 1 <= self.opencv_threads <= 2 or not 5 <= self.processing_timeout <= 60:
            raise ValueError("Invalid processing limits")
        if type(self.capture_timeout) is not int or not 1 <= self.capture_timeout <= 60:
            raise ValueError("Capture timeout must be 1–60 seconds")
        if not 1 <= self.history_days <= 365 or not 0 <= self.image_days <= 30:
            raise ValueError("Invalid retention")
        if not 1 <= self.mqtt_port <= 65535:
            raise ValueError("Invalid MQTT port")
        return self

    @classmethod
    def load(cls):
        path = Path("/data/options.json")
        opts = json.loads(path.read_text()) if path.exists() else {}
        return cls(**{k: v for k, v in opts.items() if k in cls.__dataclass_fields__ and k not in {"data", "captures", "models"}}).validate()

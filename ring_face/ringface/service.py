import hashlib
import json
import logging
from pathlib import Path
import queue
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .images import ID, CaptureError, wait_for_capture, prepare_capture_directory, share_mount_present
from .engine import rank

LOG = logging.getLogger(__name__)
BASE = "ring_face_recognition"


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.timestamp()


class Service:
    def __init__(self, settings, store, engine):
        self.settings, self.store, self.engine = settings, store, engine
        self.queue = queue.Queue(maxsize=2)
        self.stop = threading.Event()
        self.publish = lambda *a, **kw: None
        self.active = False
        self.health = "starting"
        self.thread = None
        self.enqueue_lock = threading.Lock()
        self.mqtt_connected = False
        self.last_command_at = None
        self.last_command_result = "No capture commands received since startup"

    def reject(self, reason):
        self.last_command_result = reason
        LOG.info(json.dumps({"event":"command_rejected", "reason":reason}))
        return False

    def submit(self, payload, retained=False):
        # MQTT commands must never be retained. Date and dedup checks survive restarts.
        self.last_command_at = datetime.now(timezone.utc).isoformat()
        if retained or len(payload) > 2048:
            return self.reject("retained_or_oversized_command")
        try:
            item = json.loads(payload)
            if not isinstance(item,dict):
                return self.reject("invalid_payload")
            for key in ("event_id", "source_event_id"):
                if not isinstance(item.get(key),str) or not ID.fullmatch(item[key]):
                    return self.reject("invalid_identifier")
            if type(item.get("attempt")) is not int or not 1 <= item["attempt"] <= 3:
                return self.reject("invalid_attempt")
            epoch = timestamp(item["pressed_at"])
            captured = timestamp(item["captured_at"])
            now = time.time()
            if not now - 300 <= epoch <= now + 5 or not epoch - 5 <= captured <= now + 5:
                return self.reject("expired_or_invalid_command_time")
            item["epoch"], item["capture_epoch"] = epoch, captured
            with self.enqueue_lock:
                previous = self.store.event(item["event_id"])
                if previous and (previous["status"] not in {"capture_failed", "no_face"} or item["attempt"] <= previous["attempt"]):
                    return self.reject("duplicate_event_or_attempt")
                if not previous and self.store.duplicate(item["source_event_id"], epoch):
                    return self.reject("duplicate_source_or_10_second_debounce")
                self.queue.put_nowait(item)
                self.last_command_result = "accepted"
            return True
        except (ValueError, KeyError, TypeError, queue.Full):
            return self.reject("invalid_payload_or_queue_full")

    def process(self, item):
        previous = self.store.event(item["event_id"])
        if previous and (previous["status"] not in {"capture_failed", "no_face"} or item["attempt"] <= previous["attempt"]):
            return
        if not previous and self.store.duplicate(item["source_event_id"], item["epoch"]):
            return
        started = time.monotonic()
        event = dict(id=item["event_id"], timestamp=datetime.fromtimestamp(item["epoch"], timezone.utc).isoformat(),
                     local_time=datetime.fromtimestamp(item["epoch"], ZoneInfo(self.settings.timezone)).isoformat(),
                     epoch=item["epoch"], person_id=None, identity="Unknown", score=None, status="capture_failed",
                     face_count=0, snapshot=None, trusted=0, duration_ms=0, freshness="unverified", error=None,
                     attempt=item["attempt"], image_hash=None, corrected_identity=None, source_event_id=item["source_event_id"])
        try:
            expected = self.settings.captures / f"{item['event_id']}_{item['attempt']}.jpg"
            supplied = item.get("snapshot_path")
            if supplied is not None and supplied != str(expected):
                raise CaptureError("path_mismatch", "Automation snapshot_path differs from the app's expected shared path")
            LOG.info(json.dumps({"event":"capture_wait", "id":item["event_id"], "attempt":item["attempt"],
                                 "path":str(expected), "timeout_seconds":self.settings.capture_timeout}))
            raw, metadata = wait_for_capture(self.settings.captures, item["event_id"], item["attempt"],
                                             item["capture_epoch"], self.settings.capture_timeout, self.stop)
            digest = hashlib.sha256(raw).hexdigest()
            event["image_hash"] = digest
            event["image_metadata"] = json.dumps(metadata)
            if self.store.repeated_image(digest):
                event["freshness"] = "repeated"
            # Preserve proof of a successful capture even if model inference fails.
            if self.store.setting("image_days", self.settings.image_days) > 0:
                path = self.settings.data / "images" / (event["id"] + ".jpg")
                path.write_bytes(raw)
                event["snapshot"] = path.name
            event["status"] = "error"
            result = self.engine.analyze(raw)
            features = result["features"]
            if any(v is None for v in features):
                event.update(status="ambiguous" if len(features)>1 else "unknown", face_count=len(features))
            else:
                event.update(rank(features, self.store.people(vectors=True), self.settings.similarity_threshold, self.settings.ambiguity_margin))
            person = next((p for p in self.store.people() if p["id"] == event["person_id"]), None)
            if person:
                event.update(identity=person["name"], trusted=int(person["trusted"]))
            if metadata.get("source_time_comparison") == "outside_capture_window":
                result.setdefault("warnings",[]).append("Source EXIF time is outside capture window; freshness remains unverified")
            if result.get("warnings"):
                event["error"] = "; ".join(result["warnings"])
        except Exception as e:
            # Deliberately do not log payloads, credentials or image bytes.
            event["error"] = str(e)[:180]
            LOG.warning(json.dumps({"event":"processing_failed", "id":event["id"], "status":event["status"],
                                    "reason":getattr(e,"code","processing_error"), "detail":event["error"],
                                    "path":str(self.settings.captures / f"{item['event_id']}_{item['attempt']}.jpg")}))
        finally:
            event["duration_ms"] = round((time.monotonic() - started) * 1000)
            self.store.save_event(event)
            # Keep one short-lived diagnostic no-face image, not an accumulating
            # empty-porch gallery. An image_days=0 setting remains authoritative.
            self.store.retention(self.store.setting("history_days",self.settings.history_days),
                                 self.store.setting("image_days",self.settings.image_days))
            self.health = "inference_error" if event["status"] == "error" else ("capture_failed" if event["status"] == "capture_failed" else "ready")
            path = self.settings.captures / f"{item['event_id']}_{item['attempt']}.jpg"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                LOG.warning(json.dumps({"event":"capture_cleanup_failed", "path":str(path)}))
            # State is live-only. Availability and expiration prevent old recognition
            # state being represented as a newly observed visitor after reconnect.
            self.publish(BASE + "/state", self.state(event), retain=False)
            self.publish(BASE + "/events", self.state(event), retain=False)

    def state(self, event):
        return {"event_id":event["id"], "identity":event["identity"], "status":event["status"],
                "score":event["score"], "last_seen":event["timestamp"], "freshness":event["freshness"],
                "trusted":bool(event["trusted"]), "face_count":event["face_count"], "attempt":event["attempt"]}

    def maintenance(self):
        self.store.retention(self.store.setting("history_days",self.settings.history_days), self.store.setting("image_days",self.settings.image_days))
        for path in self.settings.captures.glob("*.jpg"):
            if path.is_file() and time.time() - path.lstat().st_mtime > 180:
                path.unlink(missing_ok=True)

    def run(self):
        last_maintenance = 0
        self.health = "ready"
        while not self.stop.is_set():
            try:
                if time.monotonic() - last_maintenance > 60:
                    self.maintenance()
                    last_maintenance = time.monotonic()
                try:
                    item = self.queue.get(timeout=1)
                except queue.Empty:
                    continue
                try:
                    self.active = True
                    self.process(item)
                finally:
                    self.active = False
                    self.queue.task_done()
            except Exception:
                self.health = "storage_error"
                LOG.exception(json.dumps({"event":"worker_failed"}))
                self.stop.wait(2)


    def start(self):
        if self.settings.captures == Path("/share/ring_face/capture") and not share_mount_present():
            raise RuntimeError("share_mount_missing: /share must be mounted by Supervisor; update the app with share read/write access")
        prepare_capture_directory(self.settings.captures)
        LOG.info(json.dumps({"event":"capture_directory_ready", "path":str(self.settings.captures),
                             "directory_mode":"1777", "capture_timeout":self.settings.capture_timeout}))
        self.maintenance()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.settings.capture_timeout + self.settings.processing_timeout + 5)

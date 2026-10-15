import json
import logging
import threading
import paho.mqtt.client as mqtt
from .service import BASE

LOG = logging.getLogger(__name__)
SENSORS = {
    "last_visitor": ("Last visitor", "{{ value_json.identity }}"),
    "recognition_status": ("Recognition status", "{{ value_json.status }}"),
    "recognition_confidence": ("Recognition confidence", "{{ value_json.score | default(none) }}"),
    "last_seen": ("Last seen", "{{ value_json.last_seen }}"),
    "recognition_health": ("Recognition health", "{{ value_json.health }}"),
}


def discovery():
    for key, (name, template) in SENSORS.items():
        health = key == "recognition_health"
        payload = {
            "name":name, "unique_id":"ring_face_front_door_" + key,
            "default_entity_id":"sensor.front_door_" + key,
            "state_topic":BASE + ("/health" if health else "/state"),
            "value_template":template, "availability_topic":BASE + "/availability",
            "payload_available":"online", "payload_not_available":"offline",
            "expire_after":90 if health else 300,
            "device":{"identifiers":["ring_face_front_door"],"name":"Front door","manufacturer":"Ring Face Recognition","model":"YuNet + SFace CPU"},
        }
        if key == "last_seen":
            payload["device_class"] = "timestamp"
        if key == "recognition_confidence":
            payload["icon"] = "mdi:approximately-equal"
            payload["suggested_display_precision"] = 3
        yield "homeassistant/sensor/ring_face_front_door/" + key + "/config", payload


class Broker:
    def __init__(self, settings, service):
        self.settings, self.service = settings, service
        self.connected = False
        self.stopped = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ring-face-front-door", clean_session=True)
        if not settings.mqtt_username or not settings.mqtt_password:
            raise ValueError("Set MQTT username and password in app configuration")
        self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set()  # System CAs and hostname verification remain enabled.
        self.client.will_set(BASE + "/availability", "offline", qos=1, retain=True)
        self.client.reconnect_delay_set(1, 60)
        self.client.max_queued_messages_set(10)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        service.publish = self.publish

    def publish(self, topic, payload, retain=False):
        if not self.connected:
            return
        self.client.publish(topic, json.dumps(payload) if isinstance(payload,dict) else payload, qos=1, retain=retain)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.warning(json.dumps({"event":"mqtt_auth_or_connection_failed"}))
            return
        self.connected = True
        client.subscribe([(BASE + "/capture",1),("homeassistant/status",1)])
        self.announce()

    def announce(self):
        for topic, payload in discovery():
            self.publish(topic,payload,retain=True)
        # Clear any old retained state from earlier versions/misconfigured publishers.
        self.client.publish(BASE + "/state", b"", qos=1, retain=True)
        self.client.publish(BASE + "/events", b"", qos=1, retain=True)
        self.publish(BASE + "/availability", "online", retain=True)
        self.heartbeat()

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def on_message(self, client, userdata, message):
        if message.topic == "homeassistant/status" and message.payload == b"online":
            self.announce()
        elif message.topic == BASE + "/capture":
            self.service.submit(message.payload, retained=message.retain)

    def heartbeat(self):
        self.publish(BASE + "/health", {"health":self.service.health, "busy":self.service.active,
                     "engine_peak_rss_kib":self.service.engine.peak_rss_kib}, retain=False)

    def _heartbeats(self):
        while not self.stopped.wait(30):
            self.heartbeat()

    def start(self):
        self.client.connect_async(self.settings.mqtt_host,self.settings.mqtt_port,keepalive=45)
        self.client.loop_start()
        self.thread = threading.Thread(target=self._heartbeats,daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        info = self.client.publish(BASE + "/availability", "offline", qos=1, retain=True)
        try:
            info.wait_for_publish(timeout=2)
        except RuntimeError:
            pass
        self.client.disconnect()
        self.client.loop_stop()

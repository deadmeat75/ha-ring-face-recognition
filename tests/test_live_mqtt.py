"""Opt-in test for an existing broker. Never starts or installs a broker.
Uses temporary topics, never the production app's discovery/state topics.
Credentials must be supplied through a private process environment, not a file.
"""
import os
import ssl
import threading
import uuid
import pytest
import paho.mqtt.client as mqtt


@pytest.mark.broker
def test_existing_broker_authenticated_roundtrip_and_reconnect():
    host=os.environ.get('RING_TEST_MQTT_HOST')
    if not host:
        pytest.skip('Existing HA Mosquitto is not reachable/configured from cloud; opt-in only')
    username=os.environ.get('RING_TEST_MQTT_USERNAME');password=os.environ.get('RING_TEST_MQTT_PASSWORD')
    assert username and password,'Configure test credentials securely, never in source or chat'
    topic='ring_face_recognition/test/'+uuid.uuid4().hex
    subscribed=threading.Event();received=threading.Event()
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='ring-face-test-'+uuid.uuid4().hex)
    client.username_pw_set(username,password)
    if os.environ.get('RING_TEST_MQTT_TLS','true')=='true':client.tls_set()
    def connect(c,u,f,r,p):
        assert not r.is_failure
        c.subscribe(topic,1)
    client.on_connect=connect
    client.on_subscribe=lambda *args:subscribed.set()
    def message(c,u,m):
        if m.topic==topic and m.payload==b'protocol-test' and not m.retain:received.set()
    client.on_message=message
    try:
        client.connect(host,int(os.environ.get('RING_TEST_MQTT_PORT','8883')),30);client.loop_start()
        assert subscribed.wait(10),'MQTT connection/subscription failed'
        client.publish(topic,b'protocol-test',qos=1,retain=False).wait_for_publish(timeout=5)
        assert received.wait(10),'MQTT roundtrip failed'
        client.disconnect();client.loop_stop();subscribed.clear();received.clear()
        client.reconnect();client.loop_start()
        assert subscribed.wait(10),'MQTT reconnect failed'
        client.publish(topic,b'protocol-test',qos=1,retain=False).wait_for_publish(timeout=5)
        assert received.wait(10)
    finally:
        client.disconnect();client.loop_stop()

import json
from types import SimpleNamespace
from ringface.mqtt import Broker,discovery


class Client:
    def __init__(self):self.sent=[];self.subscriptions=[]
    def publish(self,topic,payload,qos=0,retain=False):self.sent.append((topic,payload,qos,retain))
    def subscribe(self,topics):self.subscriptions.extend(topics)


def test_discovery_schema():
    configs=list(discovery());assert len(configs)==5
    expected={'sensor.front_door_'+x for x in ['last_visitor','recognition_status','recognition_confidence','last_seen','recognition_health']}
    assert {p['default_entity_id'] for _,p in configs}==expected
    assert len({p['unique_id'] for _,p in configs})==5
    for topic,p in configs:
        assert topic.startswith('homeassistant/sensor/') and topic.endswith('/config')
        assert p['availability_topic']=='ring_face_recognition/availability'
        assert p['expire_after']>0 and p['device']['identifiers']==['ring_face_front_door']
        assert 'vectors' not in json.dumps(p) and 'embedding' not in json.dumps(p)


def test_connect_reconnect_ha_birth_retained_rejection(setup):
    settings,store,engine,service=setup
    settings.mqtt_username='test';settings.mqtt_password='test'
    broker=Broker(settings,service);fake=Client();broker.client=fake
    broker.on_connect(fake,None,None,SimpleNamespace(is_failure=False),None)
    assert broker.connected and len(fake.subscriptions)==2
    assert len([m for m in fake.sent if m[0].endswith('/config')])==5
    assert all(m[3] for m in fake.sent if m[0].endswith('/config'))
    assert ('ring_face_recognition/state',b'',1,True) in fake.sent
    fake.sent.clear()
    broker.on_message(fake,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
    assert len([m for m in fake.sent if m[0].endswith('/config')])==5
    broker.on_disconnect(fake,None,None,None,None);assert not broker.connected
    broker.on_connect(fake,None,None,SimpleNamespace(is_failure=True),None);assert not broker.connected


def test_discovery_templates_render_valid_states():
    from datetime import datetime
    from jinja2 import Environment,StrictUndefined
    env=Environment(undefined=StrictUndefined)
    state={'identity':'Alice','status':'recognized','score':.76,'last_seen':'2026-10-15T18:00:00+00:00','health':'ready'}
    for _,payload in discovery():
        rendered=env.from_string(payload['value_template']).render(value_json=state)
        assert rendered
        if payload['default_entity_id'].endswith('confidence'):
            assert float(rendered)==.76
        if payload.get('device_class')=='timestamp':
            assert datetime.fromisoformat(rendered).tzinfo is not None
        assert json.loads(json.dumps(payload))==payload

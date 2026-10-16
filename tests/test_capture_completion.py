from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import yaml
from jinja2 import Environment,StrictUndefined
from ringface.mqtt import discovery

ROOT=Path(__file__).resolve().parents[1]


def automation():return yaml.safe_load((ROOT/'home_assistant/motion_automation.yaml').read_text())


def test_completion_wait_accepts_result_already_received_and_checks_attempt():
    flow=automation()
    seq=next(a['repeat']['sequence'] for a in flow['actions'] if 'repeat' in a)
    wait=next(a for a in seq if 'wait_template' in a)
    env=Environment(undefined=StrictUndefined)
    state={'event_id':'capture_12345678','attempt':1,'status':'no_face'}
    def attr(entity,key):
        assert entity=='sensor.front_door_last_visitor'
        return state.get(key)
    args={'state_attr':attr,'capture_id':'capture_12345678','attempt':1}
    # Result received BEFORE wait starts: predicate must immediately succeed.
    assert env.from_string(wait['wait_template']).render(**args).strip()=='True'
    args['attempt']=2
    assert env.from_string(wait['wait_template']).render(**args).strip()=='False'
    state.update(attempt=2)
    assert env.from_string(wait['wait_template']).render(**args).strip()=='True'
    state['event_id']='different_event'
    assert env.from_string(wait['wait_template']).render(**args).strip()=='False'
    assert not any('wait_for_trigger' in a for a in seq)


def test_discovery_exposes_completion_fields_without_embeddings():
    payload=next(p for _,p in discovery() if p['default_entity_id']=='sensor.front_door_last_visitor')
    assert payload['json_attributes_topic']=='ring_face_recognition/state'
    env=Environment();env.filters['to_json']=json.dumps
    state=dict(event_id='capture_12345678',attempt=2,status='recognized',freshness='unverified',vectors=['PRIVATE'])
    attrs=json.loads(env.from_string(payload['json_attributes_template']).render(value_json=state))
    assert attrs=={k:state[k] for k in ('event_id','attempt','status','freshness')}
    assert 'PRIVATE' not in json.dumps(attrs)


def test_motion_and_press_share_cooldown_and_new_changes_get_new_source_ids():
    flow=automation()
    assert {t['entity_id'] for t in flow['triggers']}=={'sensor.doorbell_camera_last_motion','binary_sensor.doorbell_camera_ding'}
    assert flow['mode']=='single'
    env=Environment(undefined=StrictUndefined)
    now=datetime.now(timezone.utc)
    variables=flow['actions'][0]['variables']
    source=env.from_string(variables['source_id'])
    def render(changed):
        trigger=SimpleNamespace(to_state=SimpleNamespace(context=SimpleNamespace(id='reused_context'),last_changed=changed))
        return source.render(trigger=trigger,now=lambda:now)
    assert render(now)!=render(now+timedelta(minutes=2))
    cooldown=flow['conditions'][1]['value_template']
    args={'now':lambda:now,'as_timestamp':lambda dt:dt.timestamp()}
    assert env.from_string(cooldown).render(this=SimpleNamespace(attributes={'last_triggered':now-timedelta(seconds=10)}),**args).strip()=='False'
    assert env.from_string(cooldown).render(this=SimpleNamespace(attributes={'last_triggered':now-timedelta(seconds=61)}),**args).strip()=='True'


def test_no_face_attempt_can_retry_and_then_stop_on_unknown_detected_face(setup):
    from conftest import jpeg
    from test_service import command,run
    settings,store,engine,service=setup
    store.set_retention(30,7)
    first=command();engine.features=[]
    (settings.captures/(first['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,first)
    assert store.event(first['event_id'])['status']=='no_face'
    second=command(attempt=2);engine.features=[[1.,0.]]
    (settings.captures/(second['event_id']+'_2.jpg')).write_bytes(jpeg(color='white'))
    run(service,second)
    assert len(store.history())==1
    event=store.event(second['event_id'])
    assert event['status']=='unknown' and event['face_count']==1 and event['attempt']==2
    assert not service.submit(json.dumps(command(attempt=3)))
    flow=automation()
    seq=next(a['repeat']['sequence'] for a in flow['actions'] if 'repeat' in a)
    stop=next(a for a in seq if 'if' in a)['if'][0]['value_template']
    env=Environment()
    args={'wait':SimpleNamespace(completed=True),'state_attr':lambda entity,key:'no_face'}
    assert env.from_string(stop).render(**args).strip()=='False'
    args['state_attr']=lambda entity,key:'unknown'
    assert env.from_string(stop).render(**args).strip()=='True'

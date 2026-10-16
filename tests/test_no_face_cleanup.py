from conftest import jpeg
from test_service import command,run
from ringface.web import create_app


def capture(setup,event_id,source_id,features):
    settings,store,engine,service=setup
    engine.features=features
    item=command(event_id,source_id)
    (settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    return store.event(event_id)


def age_events(store,seconds=30):
    with store.lock,store.db:
        store.db.execute('UPDATE events SET epoch=epoch-?',(seconds,))


def test_keep_only_latest_no_face_diagnostic_and_keep_unknown_faces(setup):
    settings,store,_,_=setup
    store.set_retention(30,7)
    first=capture(setup,'capture_00000001','source_00000001',[])
    assert first['status']=='no_face' and first['snapshot']
    assert store.people()==[]
    age_events(store)
    second=capture(setup,'capture_00000002','source_00000002',[])
    assert second['snapshot'] and (settings.data/'images'/second['snapshot']).exists()
    assert store.event(first['id'])['snapshot'] is None
    assert not (settings.data/'images'/first['snapshot']).exists()
    age_events(store)
    visitor=capture(setup,'capture_00000003','source_00000003',[[1.,0.]])
    assert visitor['status']=='unknown' and visitor['snapshot']
    assert (settings.data/'images'/visitor['snapshot']).exists()


def test_no_face_diagnostic_expires_and_history_stays_opt_in(setup):
    settings,store,engine,service=setup
    store.set_retention(30,7)
    event=capture(setup,'capture_00000001','source_00000001',[])
    client=create_app(settings,store,engine,service).test_client()
    client.environ_base['REMOTE_ADDR']='172.30.32.2'
    assert client.get('/api/history').json==[]
    assert client.get('/api/history?include_no_face=true').json[0]['status']=='no_face'
    status=client.get('/api/capture-status').json
    assert status['latest']['id']==event['id'] and status['latest']['snapshot']
    assert status['last_command_result']=='accepted'
    assert client.get('/api/history/'+event['id']+'/image').status_code==200
    age_events(store,86401)
    store.retention(30,7)
    assert store.event(event['id'])['snapshot'] is None
    assert not (settings.data/'images'/event['snapshot']).exists()
    assert client.get('/api/history/'+event['id']+'/image').status_code==404


def test_disabled_image_retention_still_discards_all_images(setup):
    settings,store,engine,service=setup
    store.set_retention(30,0)
    event=capture(setup,'capture_00000001','source_00000001',[])
    assert event['snapshot'] is None
    assert list((settings.data/'images').iterdir())==[]


def test_capture_status_reports_no_commands_and_rejections(setup):
    settings,store,engine,service=setup
    client=create_app(settings,store,engine,service).test_client()
    assert client.get('/api/capture-status').status_code==403
    client.environ_base['REMOTE_ADDR']='172.30.32.2'
    status=client.get('/api/capture-status').json
    assert status['latest'] is None and status['last_command_at'] is None
    assert status['mqtt_connected'] is False
    assert not service.submit('not JSON')
    status=client.get('/api/capture-status').json
    assert status['last_command_at'] and status['last_command_result']=='invalid_payload_or_queue_full'


def test_valid_capture_image_survives_inference_error_for_diagnosis(setup):
    from unittest.mock import Mock
    settings,store,engine,service=setup
    store.set_retention(30,7)
    engine.analyze=Mock(side_effect=RuntimeError('Model unavailable'))
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    event=store.event(item['event_id'])
    assert event['status']=='error' and event['snapshot']
    assert (settings.data/'images'/event['snapshot']).exists()

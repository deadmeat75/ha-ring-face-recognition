from conftest import jpeg
from test_service import command,run
from ringface.web import create_app


def test_no_face_snapshots_discarded_before_enrollment_but_unknown_faces_kept(setup):
    settings,store,engine,service=setup
    store.set_retention(30,7)
    engine.features=[]
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    event=store.event(item['event_id'])
    assert event['status']=='no_face' and event['snapshot'] is None
    assert not list((settings.data/'images').iterdir())
    assert store.people()==[]
    with store.lock,store.db:
        store.db.execute('UPDATE events SET epoch=epoch-30')
    engine.features=[[1.,0.]]
    item=command('capture_00000002','source_00000002')
    (settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    event=store.event(item['event_id'])
    assert event['status']=='unknown' and event['snapshot']
    assert (settings.data/'images'/event['snapshot']).is_file()


def test_old_no_face_images_purged_and_history_diagnostics_opt_in(setup):
    settings,store,engine,service=setup
    store.set_retention(30,7)
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    snapshot=store.event(item['event_id'])['snapshot']
    assert snapshot
    with store.lock,store.db:
        store.db.execute("UPDATE events SET status='no_face',face_count=0")
    store.retention(30,7)
    assert not (settings.data/'images'/snapshot).exists()
    assert store.event(item['event_id'])['snapshot'] is None
    client=create_app(settings,store,engine,service).test_client()
    client.environ_base['REMOTE_ADDR']='172.30.32.2'
    assert client.get('/api/history').json==[]
    assert client.get('/api/history?include_no_face=true').json[0]['status']=='no_face'
    assert client.get('/api/history/'+item['event_id']+'/image').status_code==404

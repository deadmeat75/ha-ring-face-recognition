import io
import json
import os
import time
from datetime import datetime,timezone
import pytest
from ringface.engine import rank
from ringface.images import capture_read,decode
from ringface.service import timestamp
from conftest import jpeg


def command(event='capture_00000001', source='source_00000001', epoch=None, attempt=1):
    epoch=epoch or time.time()
    now=datetime.fromtimestamp(epoch,timezone.utc).isoformat()
    return {'event_id':event,'source_event_id':source,'pressed_at':now,'captured_at':now,'attempt':attempt}


def run(service,item):
    assert service.submit(json.dumps(item))
    service.process(service.queue.get_nowait())


def test_ranking_conservative():
    people=[{'id':'alice','vectors':[[1.,0.]]}]
    assert rank([],people,.55,.08)['status']=='no_face'
    assert rank([[1.,0.],[1.,0.]],people,.55,.08)['status']=='ambiguous'
    assert rank([[1.,0.]],people,.55,.08)['person_id']=='alice'
    assert rank([[0.,1.]],people,.55,.08)['status']=='unknown'
    people.append({'id':'bob','vectors':[[.99,.01]]})
    result=rank([[1.,0.]],people,.55,.08)
    assert result['status']=='ambiguous' and result['person_id'] is None
    assert rank([[1.,0.]],[],.55,.08)['score'] is None


def test_valid_capture_recognition_and_restart(setup):
    settings,store,engine,service=setup
    pid=store.person('Alice',True,[[1.,0.]])
    item=command();path=settings.captures/(item['event_id']+'_1.jpg');path.write_bytes(jpeg())
    published=[];service.publish=lambda topic,payload,**kw:published.append((topic,payload,kw))
    run(service,item)
    e=store.event(item['event_id'])
    assert e['status']=='recognized' and e['person_id']==pid and e['trusted']==1
    assert e['freshness']=='unverified' and not path.exists()
    assert all(not x[2]['retain'] for x in published)
    assert not service.submit(json.dumps(item))
    from ringface.store import Store
    reopened=Store(settings.data)
    assert reopened.event(item['event_id'])['identity']=='Alice'
    assert reopened.duplicate(item['source_event_id'],time.time())
    reopened.close()
    assert engine.calls==1


@pytest.mark.parametrize('change',[
 {'event_id':'../../escape'}, {'source_event_id':'x'}, {'attempt':True}, {'attempt':4},
 {'pressed_at':'2020-01-01T00:00:00+00:00'}, {'pressed_at':'not-time'},
 {'captured_at':'2099-01-01T00:00:00+00:00'}, {'pressed_at':'2026-01-01'},
])
def test_reject_commands(setup,change):
    service=setup[3];item=command();item.update(change)
    assert not service.submit(json.dumps(item))


def test_retained_and_queue_bound(setup):
    service=setup[3]
    assert not service.submit(json.dumps(command()),retained=True)
    assert not service.submit('x'*2049)
    assert not service.submit('[]')
    assert service.submit(json.dumps(command('capture_00000001')))
    assert service.submit(json.dumps(command('capture_00000002')))
    assert not service.submit(json.dumps(command('capture_00000003')))


def test_duplicate_source_and_nearby_press(setup):
    settings,store,engine,service=setup
    first=command();(settings.captures/(first['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,first)
    assert not service.submit(json.dumps(command('capture_00000002')))
    assert not service.submit(json.dumps(command('capture_00000003','other_source_0001')))


def test_invalid_capture_retry(setup,monkeypatch):
    settings,store,engine,service=setup
    # Failure path without a two-second test delay.
    import ringface.service as module
    counter=iter([0,0,3,4])
    monkeypatch.setattr(module.time,'monotonic',lambda:next(counter))
    item=command();run(service,item)
    assert store.event(item['event_id'])['status']=='capture_failed'
    monkeypatch.undo()
    second=command(attempt=2);(settings.captures/(second['event_id']+'_2.jpg')).write_bytes(jpeg())
    run(service,second)
    assert store.event(second['event_id'])['status']=='unknown'
    assert not service.submit(json.dumps(second))


def test_repeated_frame_and_multiple_faces(setup):
    settings,store,engine,service=setup
    first=command();(settings.captures/(first['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,first)
    # Simulate an earlier DB event so a later physical press can pass debounce.
    with store.lock,store.db:
        store.db.execute('UPDATE events SET epoch=epoch-30')
    second=command('capture_00000002','source_00000002')
    (settings.captures/(second['event_id']+'_1.jpg')).write_bytes(jpeg())
    engine.features=[[1.,0.],[1.,0.]]
    run(service,second)
    event=store.event(second['event_id'])
    assert event['status']=='ambiguous' and event['freshness']=='repeated'


def test_no_face_small_face_error(setup):
    settings,store,engine,service=setup
    engine.features=[None]
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    assert store.event(item['event_id'])['status']=='unknown'


def test_image_validation(setup):
    settings=setup[0]
    for data in [b'bad',b'',b'x'*(6*1024*1024+1)]:
        with pytest.raises((ValueError,OSError)):
            decode(data)
    assert decode(jpeg()).startswith(b'\xff\xd8')
    file=settings.captures/'capture_00000001_1.jpg';file.write_bytes(jpeg())
    os.utime(file,(time.time()-500,time.time()-500))
    with pytest.raises(ValueError):
        capture_read(settings.captures,'capture_00000001',1,time.time())
    file.unlink();file.symlink_to('/etc/passwd')
    with pytest.raises(OSError):
        capture_read(settings.captures,'capture_00000001',1,time.time())
    with pytest.raises(ValueError):
        capture_read(settings.captures,'../../etc/passwd',1,time.time())

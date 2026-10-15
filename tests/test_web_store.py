import io
import time
import pytest
from ringface.web import create_app
from conftest import jpeg
from test_service import command,run


@pytest.fixture
def client(setup):
    settings,store,engine,service=setup
    app=create_app(settings,store,engine,service)
    return app.test_client()


def auth(client):
    client.environ_base['REMOTE_ADDR']='172.30.32.2'
    r=client.get('/api/session');assert r.status_code==200
    return {'X-CSRF-Token':r.json['csrf']}


def test_auth_all_routes(client):
    for path in ['/','/api/session','/api/people','/api/history','/static/ui.js']:
        assert client.get(path).status_code==403
        assert client.get(path,headers={'X-Forwarded-For':'172.30.32.2'}).status_code==403
    headers=auth(client)
    assert client.post('/api/retention',json={'history_days':1,'image_days':0}).status_code==403
    assert client.post('/api/retention',headers=headers,json={'history_days':1,'image_days':0}).status_code==200
    assert client.get('/').headers['Cache-Control']=='no-store'
    assert 'default-src' in client.get('/').headers['Content-Security-Policy']


def test_enrollment_rename_replace_delete(client,setup):
    headers=auth(client);store=setup[1]
    photos=[(io.BytesIO(jpeg()),'../../danger.jpg') for _ in range(3)]
    r=client.post('/api/people',headers=headers,data={'name':"Alice'); DROP TABLE people;--",'trusted':'true','photos':photos})
    assert r.status_code==200,r.data
    pid=r.json['id'];assert r.json['warnings']
    assert len(store.people(vectors=True)[0]['vectors'])==3
    assert 'vectors' not in client.get('/api/people').json[0]
    assert list(setup[0].data.rglob('*.jpg'))==[]
    assert client.patch('/api/people/'+pid,headers=headers,json={'name':'Alice','trusted':False}).status_code==200
    assert store.people()[0]['trusted']==0
    result=client.post('/api/people',headers=headers,data={'name':'Alice','person_id':pid,'photos':[(io.BytesIO(jpeg()),'x.jpg') for _ in range(3)]})
    assert result.status_code==200 and len(store.people())==1
    assert client.delete('/api/people/'+pid,headers=headers).status_code==200
    assert store.people()==[] and store.db.execute('SELECT count(*) FROM templates').fetchone()[0]==0


def test_bad_enrollment_atomic(client,setup):
    headers=auth(client)
    assert client.post('/api/people',headers=headers,data={'name':'A'}).status_code==400
    setup[2].features=[]
    result=client.post('/api/people',headers=headers,data={'name':'A','photos':[(io.BytesIO(jpeg()),'x.jpg') for _ in range(3)]})
    assert result.status_code==400 and setup[1].people()==[]


def test_history_correction_does_not_train_retention(client,setup):
    headers=auth(client);settings,store,engine,service=setup
    store.set_retention(30,1)
    pid=store.person('Alice',True,[[1.,0.]])
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg());run(service,item)
    event=store.event(item['event_id']);eid=event['id']
    assert event['snapshot'] and client.get('/api/history/'+eid+'/image').status_code==200
    assert client.get('/api/history?person='+pid).json[0]['identity']=='Alice'
    assert client.get('/api/history?person=%27%20OR%201=1--').json==[]
    assert client.get('/api/history?start=bad').status_code==400
    assert client.patch('/api/history/'+eid,headers=headers,json={'identity':'Bob'}).status_code==200
    assert store.people()[0]['template_count']==1
    assert store.event(eid)['corrected_identity']=='Bob'
    assert client.post('/api/retention',headers=headers,json={'history_days':30,'image_days':0}).status_code==200
    assert client.get('/api/history/'+eid+'/image').status_code==404
    store.delete_person(pid)
    assert store.event(eid)['identity']=='Deleted person' and store.event(eid)['trusted']==0
    assert client.delete('/api/history/'+eid,headers=headers).status_code==200
    assert store.history()==[]


def test_retention_and_schema_version(setup):
    settings,store,engine,service=setup
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2
    assert store.db.execute('PRAGMA foreign_keys').fetchone()[0]==1
    with pytest.raises(ValueError):store.set_retention(0,10)
    with pytest.raises(ValueError):store.set_retention(30,100)
    orphan=settings.data/'images'/'orphan.jpg';orphan.write_bytes(jpeg())
    store.retention(30,0);assert not orphan.exists()
    from ringface.store import Store
    store.db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError,match='newer'):
        Store(settings.data)

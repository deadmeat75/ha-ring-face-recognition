import io
import json
from pathlib import Path
import sqlite3
import time
from unittest.mock import Mock
import pytest
from PIL import Image
from ringface.engine import Engine
from ringface.images import decode,capture_read
from ringface.settings import Settings
from ringface.store import MIGRATIONS,Store
from conftest import jpeg
from test_service import command,run


def test_upgrade_from_v1(tmp_path):
    db=sqlite3.connect(tmp_path/'visitors.sqlite3')
    db.executescript(MIGRATIONS[0]+'PRAGMA user_version=1;')
    db.execute("INSERT INTO people VALUES('alice','Alice',1)");db.commit();db.close()
    store=Store(tmp_path)
    assert store.db.execute('PRAGMA user_version').fetchone()[0]==2
    assert store.people()[0]['name']=='Alice'
    assert 'image_metadata' in {r[1] for r in store.db.execute('PRAGMA table_info(events)')}
    store.close()


def test_timeout_terminates_engine(setup,monkeypatch):
    from ringface import engine as module
    settings=setup[0]
    connection=Mock();connection.poll.return_value=False
    process=Mock();process.is_alive.return_value=True
    context=Mock();context.Pipe.return_value=(connection,Mock());context.Process.return_value=process
    monkeypatch.setattr(module.mp,'get_context',lambda _:context)
    engine=Engine(settings)
    with pytest.raises(TimeoutError,match='deadline'):
        engine.analyze(jpeg())
    assert process.terminate.called and process.kill.called and connection.close.called
    assert engine.process is None and engine.conn is None


def test_busy_engine_fails_bounded(setup):
    engine=Engine(setup[0]);engine.lock=Mock();engine.lock.acquire.return_value=False
    with pytest.raises(RuntimeError,match='busy'):
        engine.analyze(jpeg())
    engine.lock.release.assert_not_called()


def test_worker_error_is_recorded_and_recovers(setup):
    settings,store,engine,service=setup
    engine.analyze=Mock(side_effect=TimeoutError('deadline exceeded'))
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg())
    run(service,item)
    e=store.event(item['event_id'])
    assert e['status']=='error' and e['freshness']=='unverified' and service.health=='inference_error'


def test_metadata_is_diagnostic_only(setup):
    settings,store,engine,service=setup
    im=Image.new('RGB',(100,100));exif=im.getexif();exif[306]='1999:01:01 00:00:00'
    out=io.BytesIO();im.save(out,'JPEG',exif=exif)
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(out.getvalue())
    run(service,item)
    event=store.event(item['event_id'])
    assert json.loads(event['image_metadata'])['exif_datetime']=='1999:01:01 00:00:00'
    assert event['freshness']=='unverified'


def test_retention_removes_old_events_and_images(setup):
    settings,store,engine,service=setup
    store.set_retention(30,1)
    item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(jpeg());run(service,item)
    snapshot=store.event(item['event_id'])['snapshot']
    with store.lock,store.db:
        store.db.execute('UPDATE events SET epoch=epoch-86400*40')
    store.retention(30,1)
    assert not store.history() and not (settings.data/'images'/snapshot).exists()


def test_invalid_upload_rejected_without_templates(setup):
    from ringface.web import create_app
    settings,store,engine,service=setup
    client=create_app(settings,store,engine,service).test_client();client.environ_base['REMOTE_ADDR']='172.30.32.2'
    headers={'X-CSRF-Token':client.get('/api/session').json['csrf']}
    response=client.post('/api/people',headers=headers,data={'name':'Alice','photos':[(io.BytesIO(b'not an image'),'a.jpg') for _ in range(3)]})
    assert response.status_code==400 and not store.people()


def test_fifo_and_capture_directory_symlink_rejected(setup,tmp_path):
    import os
    settings=setup[0]
    fifo=settings.captures/'capture_00000001_1.jpg';os.mkfifo(fifo)
    with pytest.raises(ValueError):capture_read(settings.captures,'capture_00000001',1,time.time())
    other=tmp_path/'other';other.mkdir();link=tmp_path/'link';link.symlink_to(other)
    with pytest.raises(ValueError):capture_read(link,'capture_00000001',1,time.time())


def test_source_metadata_comparison_never_establishes_freshness():
    from datetime import datetime,timezone
    from ringface.images import compare_metadata
    epoch=datetime(2026,10,15,18,tzinfo=timezone.utc).timestamp()
    old=compare_metadata({'exif_original':'1999:01:01 00:00:00','exif_offset':'+00:00'},epoch)
    assert old['source_time_comparison']=='outside_capture_window'
    recent=compare_metadata({'exif_original':'2026:10:15 18:00:00','exif_offset':'+00:00'},epoch)
    assert recent['source_time_comparison']=='within_window_unverified'
    assert compare_metadata({'exif_datetime':'2026:10:15 18:00:00'},epoch)['source_time_comparison']=='timezone_missing'

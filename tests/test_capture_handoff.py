"""Regression coverage for shared HA Core -> app snapshot handoff, not live HA."""
from datetime import datetime,timezone
import errno
import json
import os
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace
import pytest
import yaml
from jinja2 import Environment,StrictUndefined
from conftest import jpeg
from test_service import command,run
from ringface.images import CaptureError,capture_read,prepare_capture_directory,wait_for_capture
from ringface.settings import Settings


def test_default_timeout_and_option_validation():
    assert Settings().validate().capture_timeout==10
    for bad in (0,61,True,1.2,'10'):
        with pytest.raises(ValueError,match='Capture timeout'):
            Settings(capture_timeout=bad).validate()
    assert Settings(capture_timeout=60).validate().capture_timeout==60


def test_directories_override_private_umask_only_for_exchange(tmp_path):
    directory=tmp_path/'share'/'ring_face'/'capture'
    private=tmp_path/'data';private.mkdir(mode=0o700)
    old=os.umask(0o077)
    try:
        prepare_capture_directory(directory)
        prepare_capture_directory(directory)  # Repeatable at every restart.
    finally:os.umask(old)
    assert stat.S_IMODE(directory.stat().st_mode)==0o1777
    assert stat.S_IMODE(directory.parent.stat().st_mode)==0o755
    assert stat.S_IMODE(private.stat().st_mode)==0o700
    link=tmp_path/'share'/'unsafe';link.symlink_to(directory.parent,target_is_directory=True)
    with pytest.raises(RuntimeError,match='Unsafe'):
        prepare_capture_directory(link/'capture')


def test_valid_snapshot_written_after_old_two_second_limit(setup):
    settings,store,engine,service=setup
    item=command();path=settings.captures/(item['event_id']+'_1.jpg')
    item['snapshot_path']=str(path)
    def writer():
        time.sleep(2.25)
        path.write_bytes(jpeg())
    writer_thread=threading.Thread(target=writer);writer_thread.start()
    try:
        run(service,item)
    finally:writer_thread.join()
    event=store.event(item['event_id'])
    assert event['status']=='unknown' and event['face_count']==1
    assert event['duration_ms']>=2000 and engine.calls==1
    assert not path.exists()
    assert event['freshness']=='unverified'


def test_configured_deadline_is_honored(setup,monkeypatch):
    import ringface.images as module
    settings,store,engine,service=setup
    settings.capture_timeout=17
    clock=[0.0]
    def sleep(delay):clock[0]+=delay
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0],time=time.time,sleep=sleep))
    monkeypatch.setattr(service.stop,'wait',lambda delay:sleep(delay) or False)
    run(service,command())
    assert clock[0]==17
    event=store.history()[0]
    assert event['status']=='capture_failed' and event['error'].startswith('missing: After 17s:')
    assert engine.calls==0


@pytest.mark.parametrize('kind', ['empty','invalid_image','stale','too_large','unsafe_file'])
def test_reject_bad_exchange_files_with_specific_reason(setup,kind):
    settings,_,_,_=setup
    path=settings.captures/'capture_00000001_1.jpg'
    if kind=='empty':path.write_bytes(b'')
    elif kind=='invalid_image':path.write_bytes(b'not an image')
    elif kind=='stale':
        path.write_bytes(jpeg());os.utime(path,(time.time()-500,time.time()-500))
    elif kind=='too_large':
        with path.open('wb') as f:f.truncate(6*1024*1024+1)
    elif kind=='unsafe_file':path.symlink_to('/etc/passwd')
    with pytest.raises(CaptureError) as raised:
        capture_read(settings.captures,'capture_00000001',1,time.time())
    assert raised.value.code==kind


def test_permission_error_diagnostic(setup,monkeypatch):
    import ringface.images as module
    def denied(*args,**kwargs):raise PermissionError(errno.EACCES,'denied')
    monkeypatch.setattr(module.os,'open',denied)
    with pytest.raises(CaptureError,match='permission_denied'):
        capture_read(setup[0].captures,'capture_00000001',1,time.time())


def test_partial_jpeg_can_finish_without_being_processed_early(setup,monkeypatch):
    import ringface.images as module
    settings=setup[0];path=settings.captures/'capture_00000001_1.jpg'
    raw=jpeg();path.write_bytes(raw[:-2]);writes=[]
    def complete(delay):
        writes.append(delay);path.write_bytes(raw)
    monkeypatch.setattr(module.time,'sleep',complete)
    image,metadata=wait_for_capture(settings.captures,'capture_00000001',1,time.time(),10)
    assert writes and image.startswith(b'\xff\xd8')


def test_mismatched_path_is_never_read(setup):
    settings,store,engine,service=setup
    item=command();item['snapshot_path']='/config/www/old.jpg'
    run(service,item)
    assert store.history()[0]['error'].startswith('path_mismatch:')
    assert engine.calls==0


def test_previous_unique_snapshot_is_not_reused(setup):
    settings=setup[0]
    (settings.captures/'previous_capture01_1.jpg').write_bytes(jpeg())
    with pytest.raises(CaptureError,match='missing:'):
        capture_read(settings.captures,'capture_00000001',1,time.time())


def test_app_requires_real_share_mount_at_production_path(setup,monkeypatch):
    settings,store,engine,service=setup
    settings.captures=Path('/share/ring_face/capture')
    monkeypatch.setattr('ringface.service.share_mount_present',lambda:False)
    with pytest.raises(RuntimeError,match='share_mount_missing'):
        service.start()


def render_automation(manual=False):
    root=Path(__file__).resolve().parents[1]
    automation=yaml.safe_load((root/'home_assistant/motion_automation.yaml').read_text())
    package=yaml.safe_load((root/'home_assistant/ring_face_package.yaml').read_text())
    assert automation==package['automation'][0]
    env=Environment(undefined=StrictUndefined)
    env.filters['to_json']=json.dumps
    values={'now':lambda:datetime.now(timezone.utc),'repeat':SimpleNamespace(index=2)}
    if not manual:
        values['trigger']=SimpleNamespace(to_state=SimpleNamespace(context=SimpleNamespace(id='ha_motion_context_012345')))
    for key,template in automation['actions'][0]['variables'].items():
        values[key]=env.from_string(template).render(**values)
    sequence=automation['actions'][1]['repeat']['sequence']
    for key,template in sequence[0]['variables'].items():
        values[key]=env.from_string(str(template)).render(**values)
    filename=env.from_string(sequence[1]['data']['filename']).render(**values)
    payload=json.loads(env.from_string(sequence[2]['data']['payload']).render(**values))
    assert filename==payload['snapshot_path']==f"/share/ring_face/capture/{payload['event_id']}_{payload['attempt']}.jpg"
    assert package['homeassistant']['allowlist_external_dirs']==['/share/ring_face/capture']
    config=yaml.safe_load((root/'ring_face/config.yaml').read_text())
    assert {'type':'share','read_only':False,'path':'/share'} in config['map']
    assert config['options']['capture_timeout']==10
    assert sequence[1]['action']=='camera.snapshot'
    assert sequence[1]['target']['entity_id']=='camera.doorbell_camera_live_view'
    assert sequence[2]['data']['topic']=='ring_face_recognition/capture'
    assert sequence[2]['data']['retain'] is False
    assert sequence[3]['timeout']=='00:02:10'
    return filename,payload


@pytest.mark.parametrize('manual',[False,True])
def test_rendered_ha_camera_path_matches_command_and_container_reader(tmp_path,manual):
    filename,payload=render_automation(manual)
    # Two filesystem views of the same /share mount. Core writes; app reads the
    # basename derived from exactly the same event/attempt, not /config/www.
    share=tmp_path/'share'
    core_path=share/Path(filename).relative_to('/share')
    prepare_capture_directory(core_path.parent)
    core_path.write_bytes(jpeg())
    raw,metadata=capture_read(core_path.parent,payload['event_id'],payload['attempt'],datetime.fromisoformat(payload['captured_at']).timestamp())
    assert raw.startswith(b'\xff\xd8')
    assert metadata['format']=='JPEG'


def test_mount_table_accepts_same_device_bind_mount_and_rejects_unmounted_or_readonly(tmp_path):
    from ringface.images import share_mount_present
    table=tmp_path/'mountinfo'
    table.write_text('138 129 0:27 /docker/volume /share rw,relatime - overlay overlay rw\n')
    assert share_mount_present(table)
    table.write_text('138 129 0:27 /docker/volume /share ro,relatime - overlay overlay rw\n')
    assert not share_mount_present(table)
    table.write_text('138 129 0:27 /docker/volume /share_backup rw,relatime - overlay overlay rw\n')
    assert not share_mount_present(table)

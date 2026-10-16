from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import time
import pytest
from conftest import jpeg
from ringface.images import CaptureError
from ringface.video import private_recording,select_recording_sample,video_frames,MAX_VIDEO_BYTES
from ringface.settings import Settings
from ringface.engine import Engine
from ringface.store import Store
from ringface.service import Service


def recording_command(recording_id='1234567890123456789'):
    now=datetime.now(timezone.utc)
    return dict(event_id='ring_recording_'+recording_id,source_event_id='ring_recording_'+recording_id,
                media_type='recording',recording_id=recording_id,attempt=1,
                pressed_at=now.isoformat(),captured_at=now.isoformat(),recording_at=(now-timedelta(seconds=120)).isoformat())


def make_clip(path,face=None):
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    blank=np.full((512,512,3),255,np.uint8)
    face=cv2.imread(str(face)) if face else blank
    face=cv2.resize(face,(512,512))
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),5,(512,512))
    assert writer.isOpened(),'This test requires the pinned OpenCV wheel bundled FFmpeg'
    try:
        for i in range(20):writer.write(blank if i<6 else face)
    finally:writer.release()


def sample(features,offset=1):
    return dict(features=features,image=jpeg(),warnings=[],offset=offset,face_area=100)


def test_conservative_frame_selection_skips_empty_but_not_conflicts():
    people=[{'id':'alice','vectors':[[1.,0.]]}]
    raw,result,offset=select_recording_sample([sample([],1),sample([[1.,0.]],3)],people,.55,.08)
    assert offset==3 and result['decision']['person_id']=='alice'
    _,result,_=select_recording_sample([sample([[1.,0.]],1),sample([[0.,1.]],3)],people,.55,.08)
    assert result['decision']['status']=='ambiguous' and result['decision']['person_id'] is None
    _,result,_=select_recording_sample([sample([[1.,0.],[0.,1.]],3),sample([[1.,0.]],5)],people,.55,.08)
    assert result['decision']['status']=='ambiguous' and result['decision']['face_count']==2
    _,result,_=select_recording_sample([sample([],1),sample([],3)],people,.55,.08)
    assert result['decision']['status']=='no_face'
    _,result,_=select_recording_sample([sample([None],1),sample([[1.,0.]],3)],people,.55,.08)
    assert result['decision']['status']=='ambiguous'


@pytest.mark.parametrize('change',[
 {'recording_id':'https://example.org/file.mp4'},
 {'recording_at':'2000-01-01T00:00:00+00:00'},
 {'recording_at':'2099-01-01T00:00:00+00:00'},
 {'event_id':'different_recording'},
 {'media_type':'web_url'},
])
def test_invalid_recording_commands_rejected(setup,change):
    command=recording_command();command.update(change)
    assert not setup[3].submit(json.dumps(command))


def test_shared_video_is_copied_privately_and_cleaned(setup):
    settings=setup[0];command=recording_command()
    path=settings.captures/(command['event_id']+'_1.mp4');make_clip(path)
    with private_recording(settings.captures,command['event_id'],1,time.time(),settings.data/'video_work') as (private,metadata):
        assert private.read_bytes()==path.read_bytes()
        assert private.stat().st_mode&0o077==0
        assert metadata['format']=='MP4'
        frames=list(video_frames(private))
        assert 1<=len(frames)<=5
        assert all(image.shape[:2]==(512,512) for _,image in frames)
    assert not private.exists()
    assert path.exists()


@pytest.mark.parametrize('kind',['empty','invalid','stale','symlink','oversize'])
def test_unsafe_recordings_rejected(setup,kind):
    settings=setup[0];command=recording_command()
    path=settings.captures/(command['event_id']+'_1.mp4')
    if kind=='empty':path.write_bytes(b'')
    elif kind=='invalid':path.write_bytes(jpeg())
    elif kind=='stale':
        make_clip(path);os.utime(path,(time.time()-500,time.time()-500))
    elif kind=='symlink':path.symlink_to('/etc/passwd')
    else:
        with path.open('wb') as out:out.truncate(MAX_VIDEO_BYTES+1)
    with pytest.raises(CaptureError):
        with private_recording(settings.captures,command['event_id'],1,time.time(),settings.data/'video_work',timeout=.01):
            pytest.fail('Unsafe recording accepted')
    assert not list((settings.data/'video_work').glob('*.mp4'))


@pytest.mark.models
def test_real_recording_empty_first_frame_then_person_recognized(tmp_path):
    models=os.environ.get('RING_TEST_MODELS');face=os.environ.get('RING_TEST_IMAGE')
    if not models or not face:pytest.skip('Real model assets not configured')
    settings=Settings(data=tmp_path/'data',captures=tmp_path/'share',models=Path(models),image_days=7,processing_timeout=30)
    settings.captures.mkdir()
    store=Store(settings.data);engine=Engine(settings);service=Service(settings,store,engine)
    command=recording_command();source=settings.captures/(command['event_id']+'_1.mp4')
    make_clip(source,face)
    command['recording_path']=str(source)
    try:
        face_features=engine.analyze(Path(face).read_bytes())['features']
        store.person('Public test face',False,face_features)
        assert service.submit(json.dumps(command))
        service.process(service.queue.get_nowait())
        event=store.event(command['event_id'])
        assert event['status']=='recognized',event
        assert event['identity']=='Public test face' and event['face_count']==1
        metadata=json.loads(event['image_metadata'])
        assert metadata['source']=='ring_completed_recording' and metadata['selected_seconds']>1
        assert 1<=len(metadata['sampled_seconds'])<=5
        assert 'features' not in event['image_metadata'] and 'http' not in event['image_metadata']
        assert event['freshness']=='unverified' and event['snapshot']
        assert not source.exists() and not list((settings.data/'video_work').glob('*.mp4'))
        assert not service.submit(json.dumps(command))
        assert len(store.history())==1
        print('Recording inference peak MiB',engine.peak_rss_kib/1024)
    finally:engine.close();store.close()


def test_recording_automation_uses_ready_video_id_and_keeps_url_out_of_mqtt():
    import yaml
    from types import SimpleNamespace
    from jinja2 import Environment,StrictUndefined
    root=Path(__file__).resolve().parents[1]
    flow=yaml.safe_load((root/'home_assistant/recording_automation.yaml').read_text())
    assert flow['triggers'][0]['entity_id']=='camera.doorbell_camera_live_view'
    assert flow['triggers'][0]['attribute']=='last_video_id'
    assert flow['mode']=='queued' and flow['max']==2
    env=Environment(undefined=StrictUndefined);env.filters['to_json']=json.dumps
    now=datetime.now(timezone.utc)
    rid='1234567890123456789'
    signed='https://example.invalid/ring-event.mp4?token=DO_NOT_PUBLISH'
    values={'trigger':SimpleNamespace(to_state=SimpleNamespace(attributes={'last_video_id':rid,'video_url':signed})),
            'now':lambda:now,'states':lambda entity:now.isoformat()}
    for action in flow['actions']:
        for key,template in action.get('variables',{}).items():
            values[key]=env.from_string(str(template)).render(**values)
    download=next(a for a in flow['actions'] if a.get('action')=='downloader.download_file')
    assert env.from_string(download['data']['url']).render(**values)==signed
    assert download['data']['subdir']=='ring_face/capture'
    assert download['data']['overwrite'] is True
    filename=env.from_string(download['data']['filename']).render(**values)
    mqtt_action=next(a for a in flow['actions'] if a.get('action')=='mqtt.publish')
    payload=env.from_string(mqtt_action['data']['payload']).render(**values)
    assert 'DO_NOT_PUBLISH' not in payload and 'https://' not in payload
    message=json.loads(payload)
    assert message['recording_path']=='/share/ring_face/capture/'+filename
    assert message['recording_id']==rid and message['event_id']=='ring_recording_'+rid
    assert message['media_type']=='recording' and message['attempt']==1
    assert not mqtt_action['data']['retain']
    assert not any(a.get('action')=='camera.snapshot' for a in flow['actions'])


def test_video_work_files_removed_after_decode_error(setup):
    settings,store,engine,service=setup
    command=recording_command()
    source=settings.captures/(command['event_id']+'_1.mp4')
    source.write_bytes(b'\x00\x00\x00\x10ftypisom\x00\x00\x00\x00')
    class RejectingEngine:
        def analyze_video(self,path):
            assert Path(path).is_file()
            raise CaptureError('invalid_recording','No playable frames')
    service.engine=RejectingEngine()
    assert service.submit(json.dumps(command))
    service.process(service.queue.get_nowait())
    assert store.event(command['event_id'])['status']=='capture_failed'
    assert not source.exists() and not list((settings.data/'video_work').glob('*.mp4'))

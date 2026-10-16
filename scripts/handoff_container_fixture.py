"""Two-container /share fixture. Exercises file handoff, not HA's camera API."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    role,event_id=sys.argv[1:3]
    captures=Path('/share/ring_face/capture')
    ready=captures.parent/'reader-ready'
    path=captures/f'{event_id}_1.jpg'
    if role=='prepare':
        from ringface.images import prepare_capture_directory
        os.umask(0o077)
        prepare_capture_directory(captures)
    elif role=='write':
        # Deliberately different UID from the app, as a filesystem permission test.
        assert os.geteuid()==65534
        deadline=time.monotonic()+20
        while not ready.exists():
            if time.monotonic()>deadline:raise RuntimeError('Reader never became ready')
            time.sleep(.1)
        time.sleep(3)
        path.write_bytes(Path('/tmp/sample.jpg').read_bytes())
        print(json.dumps({'writer_uid':os.geteuid(),'core_equivalent_path':str(path),'bytes':path.stat().st_size}))
    elif role=='read':
        from ringface.settings import Settings
        from ringface.engine import Engine
        from ringface.store import Store
        from ringface.service import Service
        os.umask(0o077)
        with tempfile.TemporaryDirectory() as tmp:
            settings=Settings(data=Path(tmp)/'data',image_days=1)
            store=Store(settings.data);engine=Engine(settings);service=Service(settings,store,engine)
            try:
                service.start()  # Also enforces the real /share mount and modes.
                now=datetime.now(timezone.utc).isoformat()
                payload={'event_id':event_id,'source_event_id':event_id,'pressed_at':now,
                         'captured_at':now,'attempt':1,'snapshot_path':str(path)}
                # Route a real Paho message object through the production MQTT
                # callback; no network broker is started or required by this fixture.
                from types import SimpleNamespace
                from paho.mqtt.client import MQTTMessage
                from ringface.mqtt import Broker
                message=MQTTMessage(topic=b"ring_face_recognition/capture")
                message.payload=json.dumps(payload).encode()
                message.retain=False
                Broker.on_message(SimpleNamespace(service=service),None,None,message)
                ready.write_text('ready')
                deadline=time.monotonic()+35
                while not store.event(event_id):
                    if time.monotonic()>deadline:raise RuntimeError('No persisted capture result')
                    time.sleep(.1)
                event=store.event(event_id)
                assert event['status']=='unknown',event
                assert event['face_count']==1 and event['duration_ms']>=3000
                assert event['freshness']=='unverified'
                assert event['snapshot'] and (settings.data/'images'/event['snapshot']).is_file()
                assert (settings.data.stat().st_mode&0o077)==0
                print(json.dumps({'app_uid':os.geteuid(),'app_path':str(path),'status':event['status'],
                                  'face_count':event['face_count'],'duration_ms':event['duration_ms'],
                                  'freshness':event['freshness'],'private_retained_image':True}))
            finally:
                service.close();engine.close();store.close();ready.unlink(missing_ok=True)
    else:raise ValueError('Unknown fixture role')


if __name__=='__main__':main()

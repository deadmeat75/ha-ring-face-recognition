"""Executed inside the built runtime image with the public sample at /tmp/sample.jpg."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
from ringface.engine import Engine
from ringface.images import decode
from ringface.settings import Settings
from ringface.store import Store
from ringface.service import Service
from ringface.web import create_app


def main():
    with tempfile.TemporaryDirectory() as tmp:
        settings=Settings(data=Path(tmp)/'data',captures=Path(tmp)/'capture')
        settings.captures.mkdir()
        store=Store(settings.data);engine=Engine(settings);service=Service(settings,store,engine)
        try:
            raw=Path('/tmp/sample.jpg').read_bytes()
            result=engine.analyze(decode(raw))
            assert len(result['features'])==1
            store.person('Public test fixture',False,result['features'])
            now=datetime.now(timezone.utc).isoformat()
            command={'event_id':'container_capture_01','source_event_id':'container_press_01','pressed_at':now,'captured_at':now,'attempt':1}
            (settings.captures/'container_capture_01_1.jpg').write_bytes(raw)
            assert service.submit(json.dumps(command))
            service.process(service.queue.get_nowait())
            event=store.event(command['event_id'])
            assert event['status']=='recognized' and event['freshness']=='unverified'
            client=create_app(settings,store,engine,service).test_client()
            assert client.get('/api/history').status_code==403
            client.environ_base['REMOTE_ADDR']='172.30.32.2'
            assert client.get('/api/history').json[0]['identity']=='Public test fixture'
            print(json.dumps({'container_inference_db_ingress':'PASS','engine_peak_mib':engine.peak_rss_kib/1024,
                              'cgroup_memory_peak_bytes':Path('/sys/fs/cgroup/memory.peak').read_text().strip(),
                              'cgroup_memory_limit_bytes':Path('/sys/fs/cgroup/memory.max').read_text().strip()}))
        finally:
            engine.close();store.close()


if __name__=='__main__':main()

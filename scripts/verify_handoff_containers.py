"""Verify two containers share the same capture file; installs no MQTT broker.
Usage: python scripts/verify_handoff_containers.py --sample /path/to/public.jpg
Requires a built ring-face:0.1.2 image. Does not contact Home Assistant or Ring.
"""
import argparse
from pathlib import Path
import subprocess
import uuid


def docker(*args,**kwargs):
    return subprocess.run(['docker',*args],check=True,text=True,**kwargs)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sample',type=Path,required=True)
    args=parser.parse_args()
    fixture=Path(__file__).with_name('handoff_container_fixture.py')
    volume='ring-face-test-'+uuid.uuid4().hex
    event_id='handoff_'+uuid.uuid4().hex
    ids=[]
    # docker cp preserves file read permissions, including for the non-root writer.
    fixture.chmod(0o644)
    docker('volume','create',volume,capture_output=True)
    try:
        def create(role,user='0:0'):
            cid=docker('create','--user',user,'--memory=384m','--memory-swap=384m','--cpus=1',
                       '-v',volume+':/share','-e','PYTHONPATH=/app','ring-face:0.1.2',
                       'python','/tmp/handoff.py',role,event_id,capture_output=True).stdout.strip()
            ids.append(cid)
            docker('cp',str(fixture),cid+':/tmp/handoff.py',capture_output=True)
            if role=='write':
                # A temporary copy keeps user-supplied sample permissions unchanged.
                import tempfile
                with tempfile.NamedTemporaryFile() as copy:
                    copy.write(args.sample.read_bytes());copy.flush();Path(copy.name).chmod(0o644)
                    docker('cp',copy.name,cid+':/tmp/sample.jpg',capture_output=True)
            return cid
        prepare=create('prepare');docker('start','-a',prepare,timeout=30)
        assert docker('inspect','--format','{{.State.ExitCode}}',prepare,capture_output=True).stdout.strip()=='0'
        reader=create('read');writer=create('write','65534:65534')
        docker('start',reader,writer,capture_output=True)
        statuses=[]
        for cid in (writer,reader):
            status=docker('wait',cid,capture_output=True,timeout=50).stdout.strip()
            docker('logs',cid)
            statuses.append(status)
            assert docker('inspect','--format','{{.State.OOMKilled}}',cid,capture_output=True).stdout.strip()=='false'
        assert statuses==['0','0'], 'Handoff container exit statuses: '+str(statuses)
        print('PASS: delayed file, separate containers, shared /share, different UIDs, real inference, private history; no broker installed')
    finally:
        for cid in ids:subprocess.run(['docker','rm','-f',cid],capture_output=True)
        subprocess.run(['docker','volume','rm',volume],capture_output=True)


if __name__=='__main__':main()

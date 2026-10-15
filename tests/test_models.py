import os
from pathlib import Path
import pytest
from PIL import Image
from ringface.engine import Engine,rank
from ringface.images import decode
from ringface.settings import Settings
from conftest import jpeg


@pytest.mark.models
def test_real_model_zero_one_multiple_and_same_identity(tmp_path):
    models=os.environ.get('RING_TEST_MODELS');sample=os.environ.get('RING_TEST_IMAGE')
    if not models or not sample:
        pytest.skip('Actual models/sample not available; set RING_TEST_MODELS and RING_TEST_IMAGE')
    engine=Engine(Settings(models=Path(models),processing_timeout=30))
    try:
        blank=engine.analyze(jpeg())
        assert blank['features']==[]
        raw=decode(Path(sample).read_bytes());one=engine.analyze(raw)
        assert len(one['features'])==1 and len(one['features'][0])==128
        again=engine.analyze(raw)
        assert rank(again['features'],[{'id':'sample','vectors':one['features']}],.55,.08)['status']=='recognized'
        im=Image.open(sample).convert('RGB');canvas=Image.new('RGB',(im.width*2,im.height));canvas.paste(im,(0,0));canvas.paste(im,(im.width,0))
        import io
        output=io.BytesIO();canvas.save(output,'JPEG')
        multiple=engine.analyze(decode(output.getvalue()))
        assert len(multiple['features'])==2
        assert rank(multiple['features'],[],.55,.08)['status']=='ambiguous'
        print('Actual model peak RSS MiB:',engine.peak_rss_kib/1024)
    finally:
        engine.close()


@pytest.mark.models
def test_actual_enrollment_to_private_visitor_history(tmp_path):
    models=os.environ.get('RING_TEST_MODELS');sample=os.environ.get('RING_TEST_IMAGE')
    if not models or not sample:
        pytest.skip('Actual model assets not configured')
    import io
    from PIL import ImageEnhance
    from ringface.store import Store
    from ringface.service import Service
    from ringface.web import create_app
    from test_service import command,run
    settings=Settings(data=tmp_path/'data',captures=tmp_path/'capture',models=Path(models))
    settings.captures.mkdir()
    store=Store(settings.data);engine=Engine(settings);service=Service(settings,store,engine)
    client=create_app(settings,store,engine,service).test_client();client.environ_base['REMOTE_ADDR']='172.30.32.2'
    headers={'X-CSRF-Token':client.get('/api/session').json['csrf']}
    try:
        im=Image.open(sample).convert('RGB');photos=[]
        for angle,brightness in [(-3,.9),(0,1.),(3,1.1)]:
            output=io.BytesIO();ImageEnhance.Brightness(im.rotate(angle)).enhance(brightness).save(output,'JPEG');output.seek(0);photos.append((output,'test.jpg'))
        response=client.post('/api/people',headers=headers,data={'name':'Public sample','trusted':'true','photos':photos})
        assert response.status_code==200,response.data
        item=command();(settings.captures/(item['event_id']+'_1.jpg')).write_bytes(Path(sample).read_bytes());run(service,item)
        event=client.get('/api/history').json[0]
        assert event['identity']=='Public sample' and event['status']=='recognized'
        assert event['freshness']=='unverified' and event['snapshot'] is None and event['trusted']==1
        assert not list(settings.data.rglob('*.jpg'))
    finally:
        engine.close();store.close()

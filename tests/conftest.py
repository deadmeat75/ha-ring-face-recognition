from pathlib import Path
import io
import pytest
from PIL import Image
from ringface.settings import Settings
from ringface.store import Store
from ringface.service import Service


def jpeg(size=(320,240), color='gray'):
    f=io.BytesIO();Image.new('RGB',size,color).save(f,'JPEG');return f.getvalue()


class FakeEngine:
    peak_rss_kib=0
    def __init__(self):
        self.features=[[1.,0.]]
        self.calls=0
    def analyze(self,raw):
        self.calls+=1
        return {'features':self.features,'warnings':[],'duration_ms':1}


@pytest.fixture
def setup(tmp_path):
    settings=Settings(data=tmp_path/'data',captures=tmp_path/'captures')
    settings.captures.mkdir()
    store=Store(settings.data)
    engine=FakeEngine()
    service=Service(settings,store,engine)
    yield settings,store,engine,service
    service.close();store.close()

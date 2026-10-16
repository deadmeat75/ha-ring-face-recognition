"""Artifact checks; complements, does not replace live HA validation."""
from pathlib import Path
import ast
import json
import yaml
from jinja2 import Environment
ROOT = Path(__file__).resolve().parents[1]
for p in ROOT.rglob('*.py'):
    if '.venv' not in p.parts:
        ast.parse(p.read_text(),filename=str(p))
for p in ROOT.rglob('*.yaml'):
    if '.venv' not in p.parts:
        yaml.safe_load(p.read_text())
config = yaml.safe_load((ROOT / 'ring_face/config.yaml').read_text())
assert config['arch'] == ['amd64'] and config['ingress'] and config['panel_admin']
assert not {'ports','host_network','privileged'} & config.keys()
assert config['schema']['mqtt_password'] == 'password'
assert set(config['options']) == set(config['schema'])
assert config['backup'] == 'cold'
package = yaml.safe_load((ROOT / 'home_assistant/ring_face_package.yaml').read_text())
assert {t['entity_id'] for t in package['automation'][0]['triggers']} == {'sensor.doorbell_camera_last_motion','binary_sensor.doorbell_camera_ding'}
assert package['automation'][0]['mode'] == 'single'
assert yaml.safe_load((ROOT / 'repository.yaml').read_text())['name']
env = Environment()
def templates(value):
    if isinstance(value,dict):
        for child in value.values(): templates(child)
    elif isinstance(value,list):
        for child in value: templates(child)
    elif isinstance(value,str) and '{{' in value:
        env.parse(value)
for p in (ROOT / 'home_assistant').glob('*.yaml'):
    templates(yaml.safe_load(p.read_text()))
json.loads((ROOT / 'ring_face/models.json').read_text())
print('Python syntax, YAML parsing, packaging invariants: PASS (not a live HA schema check)')

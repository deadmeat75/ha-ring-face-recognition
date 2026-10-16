"""Optional cloud-proxy build helper. Standard HAOS builds use the Dockerfile.
Preserves TLS, supplies the machine's existing trust bundle via a BuildKit
secret, and resolves proxy DNS for a Docker daemon in a separate namespace.
Never records proxy values in repository files or printed commands.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.parse import urlsplit

root=Path(__file__).resolve().parents[1]
args=['docker','build','--platform','linux/amd64','-t','ring-face:0.2.2']
if '--deps-only' in sys.argv:
    args+=['--target','runtime-deps']
seen=set()
for name in ['HTTP_PROXY','HTTPS_PROXY','NO_PROXY','http_proxy','https_proxy','no_proxy']:
    if name not in os.environ:
        continue
    args+=['--build-arg',name+'='+os.environ[name]]
    if name.lower()!='no_proxy':
        host=urlsplit(os.environ[name]).hostname
        if host and host not in seen:
            seen.add(host)
            args+=['--add-host',host+':'+socket.gethostbyname(host)]
ca=Path(os.environ.get('SSL_CERT_FILE','/etc/ssl/certs/ca-certificates.crt'))
if ca.is_file():
    args+=['--secret','id=build_ca,src='+str(ca)]
args+=['ring_face']
raise SystemExit(subprocess.call(args,cwd=root,env=dict(os.environ,DOCKER_CONFIG='/tmp/ring-docker')))

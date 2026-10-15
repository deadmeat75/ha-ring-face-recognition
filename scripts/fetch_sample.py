"""Optional public OpenCV test image. Never uploads private visitor/enrollment data."""
import hashlib
from pathlib import Path
import sys
import urllib.request
url='https://raw.githubusercontent.com/opencv/opencv/4.12.0/samples/data/lena.jpg'
data=urllib.request.urlopen(url,timeout=30).read()
expected='7de7ed51a1594fff247f4cae2301eceacf5313d6011e37b4a4c8733f7bb72c07'
if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Sample checksum mismatch')
Path(sys.argv[1]).write_bytes(data)
print('Verified public OpenCV sample')

# Model provenance and compatibility

Sources were inspected from OpenCV Zoo, pinned to commit
`47534e27c9851bb1128ccc0102f1145e27f23f98`. The SHA-256 hashes below are the
upstream Git LFS object IDs, not hashes invented after downloading an arbitrary
file. `fetch_models.py` verifies both byte length and SHA-256 before atomic
installation, revalidates existing files, and fails closed on any mismatch.

| Model | Bytes | SHA-256 |
| --- | ---: | --- |
| `face_detection_yunet_2023mar.onnx` | 232589 | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `face_recognition_sface_2021dec.onnx` | 38696353 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

Exact source metadata and download URLs:

- https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet
- https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface
- https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
- https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

YuNet is MIT licensed and SFace Apache 2.0; copies are in `ring_face/licenses/`
and included in the image. Model files are acquired at build time, not committed
here. Review their training-data provenance and suitability before biometric use.

This project pins OpenCV 4.12.0.88, NumPy 2.2.6 and Python 3.12. The 2023 YuNet
is deliberately used with OpenCV 4.x; the newer 2026 YuNet dynamic-shape export
is intended for OpenCV 5.x/ONNX Runtime and is not substituted. Linux amd64
manylinux wheels resolve and import; actual detection and 128-dimensional SFace
embedding extraction are integration-tested. Dependencies and transitive
requirements are hash-locked in `requirements.lock`; the Python base image is
also pinned by digest. Renew pins in a separate reviewed upgrade and rerun tests.

The optional public OpenCV `lena.jpg` fixture is downloaded from the OpenCV
4.12.0 tag and checksum checked by `scripts/fetch_sample.py`. It is used only
for a deterministic engineering smoke test (including generated transformations
and a two-face composition), not an accuracy benchmark, proof of consent for
visitor deployment, or calibration dataset. Private enrollment images never
leave the running app.

Current packaging reference inspected during implementation:
https://github.com/home-assistant/developers.home-assistant/tree/master/docs/apps
(`configuration.md`, `presentation.md`, `repository.md`). Current documentation
uses **apps**, retains app/add-on config conventions, requires ingress peer
`172.30.32.2`, supports `/share` mounts, and explicitly says the legacy
`build.yaml` is no longer read. Build metadata therefore lives in the Dockerfile.

## Completed-recording decoder

0.2.0 uses the FFmpeg backend already bundled in opencv-python-headless, with
CAP_PROP_N_THREADS=1 and hardware acceleration disabled. No ffmpeg CLI, Torch,
new inference server or network decoder is required in the app. Only private
local MP4 input is passed to the worker; network protocols and external MP4 data
references are disabled. At most five frames are decoded/analyzed under the
same native processing timeout. Engine features remain IPC-only and private.

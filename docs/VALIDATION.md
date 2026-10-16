# Validation record

Executed in this Linux amd64 cloud workspace, 2026-10-16 (UTC).
Retention regression tests rerun for app version 0.2.1; recording/container measurements
below were performed on 0.2.0. This is development
validation, not a claim of installation on the owner's HAOS laptop.

| Check | Outcome |
| --- | --- |
| Python syntax and runtime imports | PASS; Python 3.12.14 locally, 3.12.12 in image, OpenCV 4.12.0 |
| Dependency resolution / hashes | PASS; Linux amd64 wheels, exact direct/transitive runtime pins with SHA-256 verification |
| Model provenance and acquisition | PASS; upstream Git LFS size/hash matched both downloaded ONNX files |
| Actual model tests | PASS; no-face image, single face with 128-float embedding, repeat matching, two-face ambiguity |
| Real-photo enrollment → recognition → private history | PASS; varied synthetic transformations of a public sample, real YuNet/SFace, actual SQLite and Flask routes |
| Automated suite | 76 passed, 1 skipped (existing live MQTT broker unavailable in cloud) |
| MQTT discovery | PASS; five stable unique IDs, desired entity IDs, availability, expiration, JSON structure, Jinja rendering, reconnect/HA birth callbacks, no templates in payloads |
| SQLite / restart / migrations | PASS; persisted event deduplication, reopening DB, schema v1→v2 migration, rejecting future schema, deletion and retention |
| Security and recovery checks | PASS; ingress peer enforcement, forwarded-header rejection, CSRF, upload limits/type/quality validation, path/symlink/FIFO protection, bounded queue, engine timeout termination, invalid/repeated images, source metadata diagnostics |
| Full image build | PASS; final `linux/amd64` Python Debian image, model files and license notices included |
| Runtime container functional test | PASS; actual model → event → SQLite → authenticated history, direct access rejected, 1 CPU and 384 MiB limit, exit 0, no OOM kill |
| No-face diagnostics | PASS; all no-face images retained for configured image days, survive new events and one-day boundary, expire normally, hidden text history opt-in, latest-capture API independent of filters, zero retention respected |
| Fast result / motion recovery | PASS; already-received completion attributes satisfy wait immediately, attempt/event gates reject stale results, no-face retries update one event, reused contexts get new source IDs, motion/press share cooldown |
| Recording container handoff | PASS; separate writer UID 65534 and app UID 0, delayed shared MP4, real face detection and private history in 4009 ms including 3-second write delay; engine peak 175 MiB, cgroup peak 166 MiB, no OOM |
| Recording extraction | PASS; synthetic MP4 with empty first frame and later public face produces recognized result using real models; invalid/empty/stale/symlink/oversize recordings rejected and private work files cleaned |
| Recording identity consistency | PASS; empty samples skipped, multiple/uncomparable/inconsistent faces yield ambiguous; no embeddings/URL in persisted metadata |
| Recording automation contract | PASS; triggers a new ready Ring video ID, downloads to shared MP4, publishes no signed URL, ID/path match checked |
| Shared snapshot handoff | PASS; separately rendered HA camera/MQTT paths match, delayed writes beyond 2s succeed, default/configured timeout and specific rejections verified |
| Two-container shared volume | PASS; same `/share` volume, writer UID 65534, app UID 0, image delayed 3 seconds, actual face detection, private retained image, `unknown` record in ~3890 ms |
| Shared mount detection | PASS; Linux mount table accepts same-device bind mounts, rejects missing/read-only mappings; startup prepares shared permissions under private umask |
| Home Assistant YAML | PASS: YAML parsing, Jinja syntax and packaging invariants against documented current app conventions. Live Core/Supervisor schema acceptance is UNVERIFIED. |
| Lock/announcement/notification behavior | No implementation or HA action exists; inspected automation services and app interfaces |

## Memory measurements

A three-run public 512×512 face sample, one OpenCV thread, showed approximately
198 MiB combined sampled parent/child RSS, with warm inference ~37–43 ms.
A generated 4000×3000 (12 MP) version showed approximately 225 MiB combined RSS,
engine peak ~176 MiB, and warm inference ~43 ms. These are cloud-machine samples,
not rigorous upper bounds or accuracy/performance guarantees for the i5-4310U.

The runtime image smoke test runs with `--memory=384m --memory-swap=384m --cpus=1`
and reported cgroup peak around 187 MiB in its initial run (accounting differs
from summed process RSS). No OOM kill occurred. Do not infer that 384 MiB is a
safe production cap, or that the owner's ~1 GiB available memory is sufficient.
Flask/uploads, maximum photos, concurrent HA workloads, filesystem cache, builds
and backups can change peak use. Measure the app and Core together on the laptop.

Commands used:

```sh
sh scripts/prepare_cloud.sh
python scripts/verify_handoff_containers.py --sample /workspace/ring-lena.jpg
.venv/bin/python scripts/make_test_recording.py --face /workspace/ring-lena.jpg --output /workspace/ring-test-event.mp4
python scripts/verify_handoff_containers.py --recording --sample /workspace/ring-test-event.mp4
RING_TEST_MODELS=/workspace/ring-models RING_TEST_IMAGE=/workspace/ring-lena.jpg .venv/bin/python -m pytest -q
.venv/bin/python scripts/benchmark.py --models /workspace/ring-models --image /workspace/ring-lena.jpg
.venv/bin/python scripts/benchmark.py --models /workspace/ring-models --image /workspace/ring-large.jpg
python scripts/build_cloud.py
```

For the image smoke test, create a temporary container from `ring-face:0.2.1`
with `--memory=384m --memory-swap=384m --cpus=1 -e PYTHONPATH=/app` and command
`python /tmp/container_smoke.py`. Copy `scripts/container_smoke.py` to that path
and the downloaded public sample to `/tmp/sample.jpg` using `docker cp`, start
with `docker start -a`, inspect exit/OOM status, then remove the test container.
These Docker commands are development checks only, not HAOS installation steps.

Initial cloud failures were isolated and corrected: unwritable UV/Docker cache
paths moved to `/tmp`; container proxy DNS supplied explicitly; the existing CA
bundle mounted only for build commands. TLS/package/model verification stayed
enabled. Direct workspace access to the official model host returned 403, while
the corrected Docker build route fetched and verified both models successfully.
The models were copied out for local tests and reverified. The network draft
adds `media.githubusercontent.com` for reproducible direct model acquisition.

The initial detector score cutoff 0.90 missed both faces in a resized two-face
fixture (scores about 0.869). The implemented cutoff is 0.80; the real two-face
test now passes without changing the conservative identity threshold 0.55.

## Snapshot handoff 0.1.1 regression findings

The original 0.1.0 reader hardcoded a two-second wait and hid all reader errors.
0.1.1 uses a configurable 10-second default and specific diagnostics, shared
permissions, a required read/write `/share` mount and a single path variable in
both HA's camera service and MQTT command. It supports manual automation actions
and the confirmed `sensor.doorbell_camera_last_motion` trigger. See
[exact live update/verification instructions](SNAPSHOT_HANDOFF.md).

An initial strict `Path.is_mount()` startup check in development rejected a valid
same-device Docker shared volume. Inspection of `/proc/self/mountinfo` confirmed
the mount; the implementation now checks that Linux table for a read/write
`/share` mount. The cross-container test passed after this correction. No such
strict stat-based check was published to main.

The cross-container fixture uses the production MQTT message callback,
`Service`, models, SQLite and
private retained-image path. The writer is a filesystem stand-in for Core; it
**does not execute HA's actual `camera.snapshot` service** or connect to the
owner's broker. YAML/action/template contract tests complement this check; the
real Core service call still needs the live acceptance steps below.

## Required HAOS acceptance checklist (not performed here)

1. Back up HA and check available RAM, swap activity, existing app load, Core
   version (2026.4+) and Supervisor version. Leave start-on-boot disabled.
2. Push/review source or install as a local app through supported HA tooling.
   Confirm app repository validation, image build, protected-mode defaults,
   `/share` mapping and app startup in Supervisor.
3. Set existing broker credentials privately in app Configuration. Check actual
   broker authentication, discovery entities, availability, reconnect after a
   controlled app restart and existing MQTT integration behavior. No second
   broker is required. An optional existing-broker protocol test is provided in
   `tests/test_live_mqtt.py`; it starts no broker and uses only temporary topics.
   If using it, supply the named `RING_TEST_MQTT_*` process variables securely,
   without exposing passwords in shell history, source or chat. Test ACLs may
   need a temporary-topic allowance. This test was skipped here.
4. Follow docs/RING_RECORDINGS.md for the 0.2.1 update, configure Downloader
   with base directory `/share`, and install the completed-recording automation.
   Confirm a fresh saved recording downloads and yields a selected frame.
   For legacy JPEG tests use docs/SNAPSHOT_HANDOFF.md. Confirm the shared directory
   is actually visible to both Core and the app. Native YAML has not been loaded
   into a live HA Core configuration in this cloud machine.
5. Open ingress while signed in and confirm unauthenticated HA access fails.
   Enroll multiple consenting people; test rename, trusted label, template
   replacement, corrections, filtered history, private image access, deletion
   and retention. Check browser behavior on your phone as well as desktop.
6. Test no-face, multiple-person, unknown and similar-looking-person scenes;
   confirm no selected identity for ambiguity. Inspect unverified/repeated frame
   freshness. A fresh physical press cannot certify Ring source freshness.
7. Temporarily make Ring unavailable using supported controls; confirm bounded
   retries and `capture_failed`, then recovery on a later press. Check duplicate
   binary/event representations do not create duplicate records. Use one trigger.
8. Measure total app/Core RAM, swap activity and latency across normal peak load,
   enrollment, HA restart, and several presses before considering start-on-boot.
9. Check dashboard entity IDs and live-state expiration. Confirm durable private
   history survives app restart. Test encrypted cold backup/restore with harmless
   data during a maintenance window.
10. Verify silence and absence of any lock action in your complete HA automation
    environment; this repository cannot inspect unrelated existing automations.

This project has not been installed into the owner's HAOS
or tested against the owner's Ring account, real broker, ingress sessions,
physical laptop, or backup restoration. Those checks require that instance.

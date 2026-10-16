# Ring Face Recognition for Home Assistant OS

Requires Home Assistant Core **2026.4 or newer** and a current Supervisor.

An experimental **silent**, motion-triggered, local YuNet/SFace recognition app
for Generic x86-64 Home Assistant OS. Private enrollment and visitor history use
Home Assistant ingress and SQLite. Reuses your **existing Mosquitto broker and
MQTT integration**. No announcements, notifications, continuous video analysis,
cloud AI requests, or lock operations.

**Not an access-control system.** A match is a similarity result, not proof of
identity, liveness, or authorization. Ring can return a cached frame. Unique
filenames, file timestamps, EXIF and a recent motion event cannot prove source freshness.
Every observation is `unverified` or `repeated` (and may carry stale-metadata
warnings); no observation becomes a verified access event.

## Update an existing installation

**Latest: 0.1.2** automatically discards no-face snapshots and removes older
no-face snapshots during startup/maintenance. These diagnostic records are hidden
from normal history; select **Show no-face events** to inspect them. Unknown
visitors with a detected face are still retained, even before enrollment. Update
the app normally; no automation/configuration change is needed from 0.1.1.

**0.1.1 fixes snapshot handoff:** explicit shared mount and directory permissions,
a configurable `capture_timeout: 10`, matching camera/MQTT filenames, complete
image checks, and specific diagnostics. Follow the complete
[0.1.1 update and verification guide](docs/SNAPSHOT_HANDOFF.md). Update both the
app **and** your HA automation; keep your existing MQTT credentials and app data.

## Installation on your HAOS laptop

1. **Take an encrypted Home Assistant backup first.** With the previously
   reported ~1 GiB available RAM and swap already in use, leave start-on-boot
   disabled. See [resource guidance](docs/OPERATIONS.md#resources) before testing.
2. The project repository is
   `https://github.com/deadmeat75/ha-ring-face-recognition`, on branch `main`.
   Home Assistant's repository installer must be able to clone it without a
   GitHub login. If the repository is private, make it public when you are ready
   to share the source, or use the local-app installation route in step 3.
3. In Home Assistant: **Settings → Apps → App store → ⋮ → Repositories**
   (older versions call these Add-ons). Add
   `https://github.com/deadmeat75/ha-ring-face-recognition`, reload/check for updates,
   and install **Ring Face Recognition**. Supervisor builds the amd64 image locally.
   There is no image registry dependency and no host modification or Compose setup.
   Building can briefly consume more resources than running; stop if swap pressure
   or HA responsiveness worsens. Alternatively copy only `ring_face/` into the
   local apps directory `/addons/ring_face/` using your existing supported file
   access, then reload the app store. No manually managed Docker is needed on HAOS.
4. In the app's **Configuration**, enter your existing broker connection:

   ```yaml
   mqtt_host: core-mosquitto
   mqtt_port: 1883
   mqtt_username: YOUR_EXISTING_OR_DEDICATED_MQTT_USER
   mqtt_password: ENTER_SECURELY_IN_THE_APP_CONFIGURATION
   mqtt_tls: false
   timezone: America/Los_Angeles
   similarity_threshold: 0.55
   ambiguity_margin: 0.08
   opencv_threads: 1
   processing_timeout: 20
   capture_timeout: 10
   history_days: 30
   image_days: 0
   ```

   Do not paste real passwords into this repository, automations, or chat. The
   password uses HA's `password` configuration schema; Supervisor stores options
   privately in `/data/options.json`. Masking is not encryption at rest; protect
   HA administration and encrypt backups. Use your existing internal Mosquitto
   credentials or a dedicated non-admin MQTT user accepted by that broker. The app
   neither installs nor reconfigures Mosquitto. For a remote broker across an
   untrusted network, use `mqtt_tls: true`, its TLS port (often 8883), and a publicly
   trusted certificate. Certificate verification is mandatory.
5. **Start the app manually**. It creates `/share/ring_face/capture` and its
   private `/data` directories. Open **Web UI**, or enable **Show in sidebar** to
   open **Ring visitors**. The ingress gateway authenticates access; port 8099 is
   not exposed to your LAN. Enroll each consenting person with **3–8 photos**,
   exactly one clear face per photo, varied angles and lighting. Photos are
   discarded after normalized templates are extracted. Replace templates to
   retrain; deleting a person deletes templates. Trusted is informational only.
6. Copy [home_assistant/ring_face_package.yaml](home_assistant/ring_face_package.yaml)
   to `/config/packages/ring_face.yaml`. Merge this into your existing
   `homeassistant:` section of `/config/configuration.yaml` if packages are not
   already enabled:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   Do **not** create duplicate `homeassistant:` keys. Keep your existing package
   layout if different. The package allowlists `/share/ring_face/capture` for
   `camera.snapshot`; both Core and this app see the supported `/share` mount.
   It does not read Core's private `/config` filesystem or use public `/local`.
   Run HA's **Check configuration**, then restart Core to apply directory settings
   (an automation-only reload does not apply them). Do not enable the automation
   until the app is started and broker discovery is working.
7. The package now triggers on timestamp changes of
   **`sensor.doorbell_camera_last_motion`** and captures
   `camera.doorbell_camera_live_view`. This is the timestamp sensor confirmed on
   your installation. If using the binary sensor instead, replace the trigger
   with `binary_sensor.doorbell_camera_motion` (`off` → `on`). Walking up can
   therefore trigger recognition when Ring reports motion; no bell press is
   required. Enable motion detection in Ring and check its detection zones.
   There is a **60-second cooldown from the previous capture start**, plus
   `mode: single`, persistent IDs and the app's 10-second duplicate suppression.
   A new timestamp change after the cooldown is needed to retrigger. Motion
   sensitivity and Ring cloud latency still determine whether/when someone approaching is detected.
8. Existing installs must update the **HA automation**, not just the app. Replace
   the existing package file and reload automations, or copy the complete
   [motion_automation.yaml](home_assistant/motion_automation.yaml) into one
   automation's **Edit in YAML** screen and save. Never enable both a package
   automation and a UI copy, or retain a separate press automation. The existing
   package automation ID is preserved. If the snapshot allowlist from step 6 is
   not configured yet, apply it and restart Core first. App startup prepares
   `/share/ring_face` (0755) and its dedicated `capture` directory (sticky 1777)
   so Core can write across container user IDs. This shared exchange is temporary;
   biometric data and retained images stay private under `/data`.
   Walk into the motion zone, or use **Run actions** for a controlled snapshot
   pipeline test (0.1.1 supports manual runs with unique IDs). Verify the trace,
   app history and MQTT entities.
   Failed/missing/invalid snapshots retry up to three times. Successful captures
   stop after the first result. Wait at least 60 seconds and for motion to clear
   before a second test. For press-only operation instead, replace the trigger
   entity with `binary_sensor.doorbell_camera_ding`, or use the documented
   [event trigger alternative](home_assistant/event_trigger_alternative.yaml).
9. Create a new dashboard using [home_assistant/dashboard.yaml](home_assistant/dashboard.yaml)
   in its raw configuration editor, or merge its view into your dashboard. Native
   cards show current observations and health. Use the authenticated **Ring
   visitors** sidebar for durable, filterable history, private images, corrections,
   enrollment, deletion and retention. No custom frontend components are needed.

Before routine use, follow [the HAOS acceptance checklist](docs/VALIDATION.md).
The tests here cannot verify your Ring latency, broker credentials, ingress
sessions, Supervisor installation, or laptop memory pressure remotely.

## Entities and MQTT protocol

Discovery automatically creates these suggested IDs (HA may suffix or preserve
an existing entity ID; check MQTT device settings if they differ):

| Suggested entity | Meaning |
| --- | --- |
| `sensor.front_door_last_visitor` | Identity of latest observed event, or Unknown |
| `sensor.front_door_recognition_status` | recognized, unknown, ambiguous, no_face, capture_failed, error |
| `sensor.front_door_recognition_confidence` | Raw cosine similarity, **not a probability**; absent for no match score |
| `sensor.front_door_last_seen` | Event time in UTC |
| `sensor.front_door_recognition_health` | Worker readiness / capture or inference/storage error |

Runtime prefix is **`ring_face_recognition`**:

| Topic | Retained | Purpose |
| --- | --- | --- |
| `ring_face_recognition/capture` | Never | Snapshot command from the HA automation |
| `ring_face_recognition/state` | Never | Live observation state for discovery sensors |
| `ring_face_recognition/events` | Never | Event result / capture acknowledgement |
| `ring_face_recognition/health` | Never | 30-second heartbeat; includes engine-only peak RSS |
| `ring_face_recognition/availability` | Yes | `online` / MQTT last will `offline` |
| `homeassistant/sensor/ring_face_front_door/+/config` | Yes | Standard HA discovery prefix |

The standard discovery prefix remains `homeassistant`; your MQTT integration
already listens there. Stable unique IDs begin `ring_face_front_door_`. App and
HA reconnects resend discovery. Old retained state/events are cleared on connect;
retained replay commands are rejected, timestamps are bounded, completed IDs are
persistently deduplicated, and state sensors expire after 300 seconds. Health
expires after 90 seconds. A restored HA Recorder state is historical, not a fresh
visitor event. Automation acknowledgement races are harmless: retries reuse the
same ID, completed events cannot be processed again, and leftover capture files
are purged. No unlock topic or authorization endpoint exists. Templates never
leave the app in MQTT messages or HA attributes. MQTT messages do contain visitor
names, so restrict broker access and treat HA Recorder/backups as personal data.

## Matching, processing and storage

- CPU only: OpenCV **4.12.0.88**, YuNet `2023mar` and SFace `2021dec`; no Torch,
  GPU, Coral, or heavyweight inference service. Haswell-compatible amd64 wheel;
  actual i5-4310U timing remains a target-machine check.
- A single lazy subprocess holds both models. OpenCV and BLAS use one thread by
  default, inference has lowered scheduling priority, the detection preview is at
  most 640 pixels, and input is bounded to 6 MiB / 12 megapixels then normalized
  to at most 1280 pixels. One active job and two queued commands; enrollment and
  capture share the same engine lock. A native inference overrun terminates the
  subprocess; the next request recreates it. Snapshot file readiness has its own
  configurable 1–60-second deadline (default 10), independent of inference timeout. Enrollment is best performed while
  capture automation is disabled to avoid busy-engine errors.
- Detection score cutoff is 0.80, minimum identity face size 60 pixels on the
  normalized image. Zero faces → `no_face`; multiple detected faces → `ambiguous`
  with no chosen identity. Small sole face → `unknown`. Detection can miss faces;
  these outcomes describe detected faces, not a guarantee about the scene.
- Default match cosine threshold **0.55** and distinct-person margin **0.08** are
  configurable in app options. They are stricter than OpenCV's demonstration
  cosine cutoff 0.363, but are **not calibrated for your doorway**. Each person's
  score is their best template match. If the best two people are within the
  margin, identity stays ambiguous. Collect unknown and known examples under
  actual lighting; prefer false rejections to falsely assigning a person. Restart
  the app after changing thresholds. A higher score is not a probability.
- Enrollment rejects zero/multiple/small faces, checks cross-photo consistency
  (cosine ≥0.45), warns about blur and near duplicates, and stores only normalized
  128-float templates in private SQLite. Quality heuristics are not liveness or
  spoof protection. Names and filenames never become filesystem paths.
- SQLite uses numbered transactional migrations, foreign keys, parameterized
  values, a serialized writer lock, and persistent event IDs. Event records contain
  UTC/local time, identity, score, status, face count, optional private snapshot,
  informational trusted flag, duration, source/event IDs, attempt, frame hash,
  image metadata and freshness. Corrections preserve the original label and never
  train templates. The history UI returns the latest 200 rows matching person and
  UTC date filters; retention bounds the complete database.
- App data: `/data/visitors.sqlite3` and `/data/images/`. Defaults retain **30 days
  of events, no images**. UI retention settings override app defaults and apply
  immediately; startup and minute maintenance also purge expired data. Completed
  exchange images are deleted, duplicates/crash leftovers after ~3 minutes plus
  the maintenance interval. Enrollment photos never enter a public directory.

## Development and verification

Python 3.12 on Linux amd64:

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r ring_face/requirements.lock
.venv/bin/pip install -r requirements-dev.txt
python3 ring_face/fetch_models.py /tmp/ring-models
python3 scripts/fetch_sample.py /tmp/ring-lena.jpg
.venv/bin/python scripts/check.py
RING_TEST_MODELS=/tmp/ring-models RING_TEST_IMAGE=/tmp/ring-lena.jpg .venv/bin/pytest -q
.venv/bin/python scripts/benchmark.py --models /tmp/ring-models --image /tmp/ring-lena.jpg
docker build --platform linux/amd64 -t ring-face:0.1.2 ring_face
```

Model fetches require `media.githubusercontent.com`, packages use PyPI, the
base image uses Docker Hub, and the optional public test image uses
`raw.githubusercontent.com`. Runtime recognition has **no model/cloud download**
and never uploads images. See [models and sources](docs/MODELS.md). Corporate/cloud
proxy environments can use `python scripts/build_cloud.py`; it supplies existing
proxy DNS and a BuildKit-mounted trust bundle while keeping TLS and package hash
verification enabled. It does not install anything on HAOS.

[Validation results and limitations](docs/VALIDATION.md) ·
[Operations, backup, upgrade, rollback, uninstall](docs/OPERATIONS.md) ·
[Security and future access architecture](docs/SECURITY.md) ·
[Complete tree](docs/TREE.txt)

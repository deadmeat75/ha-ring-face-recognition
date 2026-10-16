# Configuration

See the repository [README](../README.md), [security design](../docs/SECURITY.md),
and [operations guide](../docs/OPERATIONS.md) before enabling the capture package.

Set your existing Mosquitto host, port, username and password in this app's
Configuration tab. Keep credentials out of automation YAML. The app does not
install a broker. Port 1883 is appropriate only for your existing internal
Supervisor broker network; use verified TLS (usually port 8883) across untrusted
networks. System certificate authorities are used; self-signed brokers need a
proper CA provisioning enhancement before use, not disabled verification.

Start manually; leave start-on-boot disabled until memory and event behavior
have been measured on your laptop. Open Web UI uses Home Assistant ingress;
there is deliberately no published HTTP port.

Threshold default 0.55 is a cosine similarity threshold, never a percentage or
probability. Ambiguity margin default 0.08 compares the best two distinct people.
The trusted flag is only an informational registry label. Nothing unlocks doors.

## Snapshot handoff (0.1.1)

Set `capture_timeout: 10` (range 1–60 seconds) in Configuration. This is separate
from `processing_timeout`, which bounds model initialization/inference. Update
your HA automation and snapshot directory allowlist as described in
[Snapshot update and verification](../docs/SNAPSHOT_HANDOFF.md). Private visitor
history and enrollment data survive an ordinary app update; do not uninstall.

## No-face cleanup (0.1.2)

Empty-porch/no_face snapshots are discarded automatically, including previously
retained ones at startup/maintenance. Their text records are hidden from normal
history; use Show no-face events and Filter / refresh for diagnostics. Unknown
visitors with a detected face remain visible and follow Image days retention.
Enrollment is not required for face detection. Update normally and reopen Web UI;
no automation changes are required from 0.1.1.

## Capture visibility and result race (0.1.3)

Use the new Latest capture panel to distinguish absent commands, capture errors
and hidden no-face results. Its status refresh does not trigger the camera.
With Image days enabled, one newest no-face image is retained for up to one day;
older no-face pictures are discarded. Update both the app and HA automation,
as detailed in [Capture recovery](../docs/CAPTURE_RECOVERY.md).

## Ring recordings (0.2.0)

Use the [completed-recording setup](../docs/RING_RECORDINGS.md) for Ring. Native
camera.snapshot can return a cached first/early recording frame; Ring WebRTC live
view is a different path. The new workflow downloads each completed event video
through your existing HA Ring account and Downloader into /share, then analyzes
up to five local frames. No new heavyweight stack or broker is installed.

# Security, privacy and freshness

## Trust boundary

Ingress is the only HTTP entry point. The Flask application checks the **actual
TCP peer** is `172.30.32.2` before every route, including private images and
static assets. It never trusts `X-Forwarded-For` or a user-supplied identity
header. No host port or host networking is configured. Home Assistant handles
session authentication; restrict ingress access to administrators, and do not
share an admin session. `panel_admin: true` restricts sidebar visibility; it is
not a substitute for Home Assistant's own ingress access checks. Everyone with
access to this app's ingress session must be considered a biometric administrator.
Do not proxy this app independently or add a direct published port.

Mutations require a random per-process CSRF token obtained through authenticated
ingress. The UI uses relative URLs for ingress prefixes, never renders names or
errors as HTML, and sets a restrictive same-origin CSP, no-store, no-sniff and
no-referrer headers. Request bodies, photos, decoded pixels, connections, worker
queue and registry size are bounded. Upload filenames are ignored. Only JPEG/PNG
are decoded; images are re-encoded to strip metadata before private storage.
Capture paths are generated from validated identifiers, opened relative to a
fixed directory, must be regular files, and cannot follow file/directory symlinks.
Other malicious privileged apps on the same Supervisor host remain outside this
app's isolation guarantees; `/share` is inherently shared.

`/data` holds biometric templates and optional visitor images. The service sets
umask 077; enrollment source photos are never persisted. SQLite `secure_delete`
is enabled, but deletion cannot promise physical erasure on SSDs or removal from
previous HA backups. Protect backups, disks, HA accounts and MQTT credentials.
The DB is **not encrypted at rest** by this app. Use HAOS disk protection and
encrypted HA backups appropriate to your threat model. Do not enroll people
without an appropriate basis and their informed agreement. Set short retention.

MQTT credentials are configured in the app password field and never logged.
Internal `core-mosquitto:1883` uses the existing Supervisor app network. TLS with
system CA and hostname verification is supported for remote brokers. No
certificate verification bypass exists. Use a dedicated MQTT user/ACL where your
existing broker supports it: read `ring_face_recognition/capture` and
`homeassistant/status`, write the app's state/events/health/availability and its
five discovery config topics. Core needs the corresponding publish/subscribe
rights. Do not change a working broker's authentication blindly. Any client that
can forge a capture command and write the shared folder can inject an observation;
MQTT data is informational, never an authorization channel.

## Freshness and replay

The dedicated exchange directory uses sticky mode 1777 to permit Core and this
app to write even under different container user IDs. Its parent is 0755; `/data`
remains private (umask 077). This does not expose an HTTP endpoint. Other apps
with the `/share` mount can access shared captures, so only transient exchange
images belong there. Do not extend these permissions to `/data`, enrollment
storage, retained images, or all of `/share`.

Capture command schema:

```json
{"event_id":"unique_capture_0001","source_event_id":"unique_press_0001","pressed_at":"2026-10-15T18:00:00+00:00","captured_at":"2026-10-15T18:00:01+00:00","attempt":1,"snapshot_path":"/share/ring_face/capture/unique_capture_0001_1.jpg"}
```

The optional `snapshot_path` must exactly match the fixed directory and derived
event/attempt basename; it is checked, never used as an arbitrary input path.
Older commands without that field remain compatible. The five-minute event age
allows bounded multi-attempt capture deadlines; each attempt still requires a
recent file and fresh capture timestamp, and successful IDs remain deduplicated.
The app accepts only timezoned commands within 300 seconds of the original motion/press event (maximum
five seconds future skew), capture timestamps after the press with five seconds
skew allowance, attempts 1–3, and an appropriately recent image mtime. It validates
decoding and records the original format, dimensions, available EXIF timestamps
and file mtime. Original metadata is diagnostic and not a trusted timestamp.
Normalized image hashes detect an exact repeated frame while history is retained;
JPEG recompression, resizing, deleted history or different metadata may prevent
repeat detection. Duplicate event/source IDs and a 10-second debounce persist
across restarts. A failed capture may be retried under the same ID with a higher
attempt; completed recognition cannot be retried as a new event.

**None of this proves that Ring's source image is fresh.** Recent file creation
proves only that a local file was written recently. No Ring source-frame timestamp
or cryptographically bound capture nonce is available in `camera.snapshot` here.
Freshness is never promoted to `verified`. A recognized result and a trusted
person label may coexist with `unverified` or `repeated` freshness; neither label
is authorization. Timestamps, scores and trusted labels remain informational.

State and events are never retained. MQTT retained replay commands are rejected;
QoS retransmissions are deduplicated. The service clears previously retained
state/events when reconnecting and expires discovery state, so a broker/HA restart
cannot manufacture a new press from retained visitor state. Historical state
inside HA Recorder or the private UI remains historical.

## Future access architecture (not implemented)

Any future door access design must use an independent authentication factor
(e.g. a cryptographic phone credential or PIN verified through a secure lock
integration), an explicit authorization policy, short-lived one-time challenges,
replay protection, authenticated event transport, independently established
source freshness, audit logs and a fail-closed lock controller. A policy decision
must bind the authenticated person, lock, purpose and expiry. Facial recognition
can be optional context only. Do not connect this app's sensor, trusted label,
score, or MQTT event directly to any unlocking action. There is no lock API,
service call, unlock endpoint, unlock topic or unlock automation in this project.

## Residual limitations

No liveness, presentation-attack, deepfake or photograph-spoof defense is
implemented. Detection can miss a second person, and match errors vary with
lighting, pose, age and training biases. Quality warnings are heuristics. These
limits are why the app is a silent history tool and its packaging stage is
experimental. Reporting `recognized` does not change these limits.

## Completed-recording path (0.2.0)

HA Downloader obtains the signed URL using the existing Ring integration; the
app receives only a validated ID and local MP4 path. URLs / Ring tokens never
enter the app, its MQTT payloads or DB. Protect HA traces, which may include
Downloader URLs. The camera ready-video ID and download URL are taken from one
triggering HA state; later queued jobs cannot silently substitute a different
URL. The separate recording timestamp sensor is diagnostic metadata, not an
authenticated frame timestamp or proof of exact motion-event correlation.

The app validates a regular non-symlink shared file, bounded size/mtime, unchanged
copy metadata, MP4 header, frame dimensions/duration, and a claimed recording age
of at most ten minutes. It reads via a private copy and limits one decoder thread
and five samples under a killable native deadline. Decoder network protocols and
external data references are disabled. Temporary shared/private MP4s are deleted;
only the selected private JPEG can follow image retention. Multiple/inconsistent
faces across samples remain ambiguous. All freshness stays unverified/repeated;
recorded-video matching cannot authorize any access-control action.

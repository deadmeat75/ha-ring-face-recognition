# Operations and troubleshooting

## Resources

Your machine is an i5-4310U, 4 logical CPUs, 8 GB RAM, no accelerator. Previously
reported ~1 GiB available RAM and ~2 GiB used swap are a reason to measure first,
not a proof of capacity. App `boot: manual` avoids adding startup pressure.

The cloud public-image benchmark reports only that machine's measurements; see
VALIDATION.md. It does not include Core, your other apps, every possible image,
HAOS backups/builds, or your laptop's thermal/CPU behavior. Large uploads can
briefly use more memory than the inference process alone. Enrollment is sequential
and one native inference process is reused; detected image sizes and queue length
are bounded. Do not increase OpenCV threads above one on this laptop without
measurements. Two is the supported maximum. Docker/HA Supervisor memory reporting
is more useful for total deployment memory than the engine-only health field.

Before testing, note available memory, swap activity and Core responsiveness from
HA's system information/resource monitors and existing diagnostic tooling. Start
only this app, enroll one person, make several presses including a multi-person
scene, and observe total app/Core memory and response times. Stop the app if memory
keeps rising, swap activity increases materially, the app is OOM-killed, or Core
becomes sluggish. Leave start-on-boot disabled until you have sufficient measured
headroom during your normal peak load. Do not add swap or modify the HAOS host as
an installation workaround. The app has no unsupported Supervisor memory-limit
setting; inference deadlines do not guarantee an operating-system memory limit.

## Snapshot handoff update

For `capture_failed` at about 2005 ms on 0.1.0, install **0.1.1** and follow
[the complete handoff update guide](SNAPSHOT_HANDOFF.md), including the HA
allowlist and replacement automation. The old two-second catch-all error does
not distinguish a missing mount, blocked Core write, path mismatch or bad image.
0.1.1 logs the exact expected `/share` path and a specific reason. Raising a
wait timeout cannot repair a failed `camera.snapshot` service call by itself.

## Diagnosis

| Symptom | Check / action |
| --- | --- |
| App fails before UI starts | Set both MQTT username and password; inspect structured startup logs, timezone and option ranges. |
| MQTT unavailable | Reuse your existing Mosquitto host/port/user; check broker log for this client; verify TLS port and certificate trust. Do not install a second broker. |
| No entities | Existing MQTT integration discovery must use standard `homeassistant` prefix. Reconnect/restart the app, inspect device entities for naming collisions. Only one app instance may use the fixed client ID. |
| Sensors become unavailable after a few minutes | Intentional expiration: live state is not retained. Durable history remains in ingress. Health should update every 30 seconds. |
| Capture failed | Read the specific error (`missing`, `permission_denied`, `path_mismatch`, `empty`, `invalid_image`, `stale`). Inspect HA automation trace, camera availability, directory allowlist and `/share/ring_face/capture` creation. Start the app before enabling the package. The old `/config/www/ring_test.jpg` is not this app's exchange path. |
| No event on physical press | Inspect the binary sensor transitions. Use the documented event-entity replacement if required, never both triggers. 0.1.1 also supports Run actions with a unique manual event ID; that tests the snapshot pipeline but not the physical motion trigger. |
| Capture retries but completed event exists | MQTT result can race the wait subscription. The app deduplicates further attempts. Leftover captures expire automatically. |
| `capture_failed` after Ring outage | Three attempts are exhausted, or command/file timestamps exceed the bounded window. A later physical press is a new event. Check machine clock synchronization through supported HA settings. |
| Recognized an old view | Source freshness is unverified. Exact repeated frames are marked repeated, but different encodings can escape hash detection. Check the Ring app for cloud latency; do not use this result for access. |
| Unknown / no face / ambiguous | Check illumination, face size and framing. A multi-face scene is intentionally ambiguous. Use varied, clear enrollment photos and conservative thresholds. A photograph or mask is not a safe identity factor. |
| Engine busy during enrollment | Disable capture automation while administering enrollment; one shared native engine is intentional. Retry later rather than increasing concurrency. |
| Inference timeout / engine exit | Subprocess is terminated and recreated next request. Check app memory, swap and CPU; reduce contention, retain one thread, and only then consider a longer timeout within 5–60 seconds. |
| Ingress 403 | Access through HA Open Web UI, not a direct port/proxy. Actual TCP peer must be `172.30.32.2`; forwarded IP headers do not bypass the check. |
| UI reload after restart | CSRF tokens rotate at restart; refresh ingress to obtain the new token. |
| SQLite/storage error | Stop capture automation, check data disk space and backups, restart the app once storage is healthy. Do not delete the DB to hide an error. |
| Build download/checksum failure | Verify official source availability, proxy trust and domain access. Never disable TLS or replace expected hashes to force a build. |

## Retention, deletion and backups

History defaults to 30 days, images to zero days. UI retention settings are
persistent and override option defaults; use the UI to change them after initial
setup. A change immediately purges expired images/events, and startup/minute
maintenance repeats this. Image files have no public URL. Correcting history does
not alter original matching evidence or templates. Deleting a person removes
biometric templates and redacts identities in their linked records. Delete
individual records to remove associated private images. Orphaned private images
are cleaned on maintenance; shared capture leftovers age out after three minutes.

Use Home Assistant's supported encrypted backup mechanism and select this app's
data. `backup: cold` stops the app while Supervisor snapshots SQLite and private
images consistently. In-flight jobs and RAM-only queue entries do not survive;
HA's bounded capture retry can resend a command, and saved events remain
deduplicated. Exchange captures live in `/share`; exclude that temporary directory
from long-lived backup policies where possible. Backups preserve templates/images
that were present when made; apply your privacy retention policy to backups too.

For a recovery test: disable capture automation, take a cold backup, create a
harmless test person, restore the backup through HA, reopen ingress and confirm
the expected people/history. Do not merge a restored database with a newer app's
schema. Restoring from backup is a user-controlled action on the real instance;
it has not been performed in the cloud workspace.

## Upgrade and rollback

1. Disable the capture automation. Take an encrypted cold backup including app
   version and data. Record existing thresholds and UI retention settings.
2. Review release notes and model/license changes. Update from the app store.
   Migrations advance `PRAGMA user_version` transactionally. Templates are model
   version specific: model changes require an explicit migration/re-enrollment
   release, never silently mix incompatible vectors.
3. Start manually, inspect health, people and history, and perform one physical
   press before re-enabling the automation and any start-on-boot preference.
4. If rollback is needed, stop the app and restore the **matching pre-upgrade app
   and data backup** using HA's supported restore workflow. Older code refuses
   a newer DB schema. Do not edit `user_version`, overwrite a live SQLite file,
   or reset a Git checkout as a database rollback.

## Uninstallation and complete data deletion

1. Disable/remove the Ring Face automation and dashboard cards. Remove only this
   package's allowlist entry if no other feature needs it; keep unrelated settings.
2. In ingress, delete people/templates and visitor records as appropriate, or
   uninstall the app with its data using Supervisor. Check your HA version's data
   removal confirmation. Never delete Core's own database.
3. Remove `/share/ring_face/capture` with supported HA file access after stopping
   the app; it contains temporary exchange images only.
4. Remove the Ring Face device/entities from the existing MQTT integration. Clear
   the five retained `homeassistant/sensor/ring_face_front_door/<key>/config`
   topics plus `ring_face_recognition/availability` and any mistakenly retained
   capture/state/events/health topics by publishing empty retained payloads via
   HA's MQTT tools. Do not remove Mosquitto or your MQTT integration.
5. Revoke a dedicated MQTT user's access only if no other feature uses it.
   Delete corresponding encrypted backups/exports according to your retention
   policy; HA Recorder may still contain past visitor names until its normal
   purge or a deliberate supported Recorder purge. SSD-level erasure is not
   guaranteed by deleting app files or SQLite records.

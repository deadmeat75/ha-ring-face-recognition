# Fix and verify snapshot exchange — version 0.1.1

## What the old error establishes

`capture_failed: Missing, stale, or invalid snapshot after bounded wait` at
~2005 ms is the old **hardcoded two-second file wait**, not a model failure or a
proof that Ring cannot take snapshots. The old reader swallowed filesystem and
validation errors behind that same message. The original declared `/share`
paths matched, but the exchange directories inherited the app's private 077
umask, and a failed HA camera action could still send an MQTT command with no
file because capture actions allow retries via `continue_on_error`.

The cloud workspace cannot inspect your running Core container or automation
trace; a single live root cause cannot be asserted from that message alone.
0.1.1 fixes the handoff contract and makes remaining failures actionable.

## Updated handoff contract

- Supervisor maps `type: share`, `read_only: false`, `path: /share` in
  `ring_face/config.yaml`. The running app refuses to proceed if the production
  `/share` path is not actually mounted.
- App startup creates `/share/ring_face` as 0755 and its dedicated `capture`
  directory as sticky 1777. It exercises a write/read/delete self-check and logs
  `capture_directory_ready`. This supports cross-container user IDs. Only these
  temporary exchange directories receive shared permissions; **not `/data`**
  and not the `/share` root. Other apps with shared mount access can read these
  transient files; enrollment and retained images remain private.
- HA Core allowlists `/share/ring_face/capture`. Its `camera.snapshot` action
  writes `/share/ring_face/capture/<unique-event-id>_<attempt>.jpg`.
- Each attempt computes **one** `snapshot_path` variable, uses it for the camera
  filename and MQTT payload, and the app checks it against its expected path.
  No `/config/www`, `/local`, cross-container private `/config` access or fixed
  reusable snapshot name is involved.
- `capture_timeout` defaults to **10 seconds**, configurable from 1–60 in app
  Configuration. It bounds file readiness after MQTT reception, separately from
  `processing_timeout`. Missing, empty, incomplete and stale files are retried
  within that window. Unsafe paths, oversize files and permission errors fail
  immediately with a specific reason. Shutdown interrupts a pending wait.
- The app requires a regular non-symlink file, bounded size, stable file metadata,
  complete valid JPEG/PNG decoding, an appropriate mtime relative to the attempt,
  and a file age no greater than 120 seconds. It never falls back to an older file.
- Up to three attempts retain one event ID with unique attempt filenames. The HA
  acknowledgement timeout is 130 seconds so it covers the supported capture
  (up to 60s) plus inference (up to 60s) deadlines. Commands older than five
  minutes remain rejected; the longer bounded retry window does not verify
  Ring source freshness. Failed capture retries replace the failed record;
  successful records stay deduplicated.
- Logs include `capture_wait` with path/attempt/timeout and `processing_failed`
  with `missing`, `empty`, `invalid_image`, `stale`, `permission_denied`,
  `unsafe_file`, `too_large`, or `path_mismatch`. History shows the same specific
  error. Successful exchange files are deleted; failed cleanup is logged rather
  than suppressing the persisted event and MQTT result.

## Exact update instructions for the existing HAOS installation

1. Disable your Ring Face capture automation temporarily. Make an encrypted HA
   backup including this app's data. **Do not uninstall or delete the app's data**;
   your existing history, biometric templates, retention and credentials stay put.
2. In **Settings → Apps → App store → ⋮**, choose **Check for updates** (wording
   may vary with Supervisor). Open Ring Face Recognition and update to **0.1.1**.
   The app's version is bumped so Supervisor can discover the new build. If the
   repository is cached, reload/check the app store before checking the app again.
   Confirm the repository contains the 0.1.1 source before updating.
3. In the app Configuration, retain all existing broker/recognition options and
   set `capture_timeout: 10`. If your Supervisor adds the default automatically,
   simply confirm it. Save and start/restart the app. Confirm the app log contains
   `capture_directory_ready`, `/share/ring_face/capture`, and timeout `10`.
   If `share_mount_missing` appears, confirm you installed the new app config
   and restarted/recreated the app via Supervisor; do not create a substitute
   `/share` inside a container or alter the HAOS host.
4. Configure the HA allowlist. If you use packages, replace your existing
   `/config/packages/ring_face.yaml` with the **complete updated**
   [ring_face_package.yaml](../home_assistant/ring_face_package.yaml). Keep
   `homeassistant: packages: !include_dir_named packages` merged into your one
   existing `homeassistant:` block. Enable only that package automation.
5. If you use a UI-managed automation instead, replace its entire **Edit in YAML**
   contents with [motion_automation.yaml](../home_assistant/motion_automation.yaml).
   Do not also enable a package copy. Merge this into the existing
   `/config/configuration.yaml` `homeassistant:` block, preserving other entries:

   ```yaml
   homeassistant:
     allowlist_external_dirs:
       - /share/ring_face/capture
   ```

   Keep any existing allowlist entries and packages setting. **Do not** introduce
   duplicate `homeassistant:` keys. Start the app first so the directory exists.
6. Run HA **Check configuration**. If the allowlist was added/changed, restart
   **Home Assistant Core** through its supported UI. An automation reload alone
   does not apply a changed allowlist. If the allowlist already matches, saving
   the UI automation or reloading package automations is sufficient for that part.
7. Reopen app Web UI; it should show **snapshot wait: 10s**. Keep your existing
   Mosquitto broker/integration and credentials. No new broker or HA token is used.

## Verify the live workflow on your installation

1. In Developer Tools → Actions, first test the Core write independently:

   ```yaml
   action: camera.snapshot
   target:
     entity_id: camera.doorbell_camera_live_view
   data:
     filename: "/share/ring_face/capture/ha_diagnostic_{{ now().strftime('%Y%m%dT%H%M%S%f') }}_1.jpg"
   ```

   A service error here establishes a **Core/camera/allowlist/write** problem,
   before MQTT or recognition. Inspect the exact error. A success writes only a
   diagnostic exchange file, not a visitor record. Use your supported HA shared
   file access to inspect its image if needed; do not change host permissions
   manually. The app purges old shared captures after a few minutes.
2. Run **Actions** on the updated Ring Face automation. 0.1.1 supplies unique
   manual event IDs when no trigger context exists. This exercises camera write,
   MQTT command, app container read, validation, recognition and private history
   without waiting for motion. Inspect the trace's snapshot action even though
   `continue_on_error` allows retries. In its variables, compare `snapshot_path`
   to the `capture_wait` path in app logs; they must be identical.
3. The app should create `unknown`, `recognized`, `no_face`, or `ambiguous` history
   instead of `capture_failed`. A successful image alone does not guarantee a
   visible face. For viewable history pictures set **Image days >0** in the app
   UI; this controls private retention, not shared exchange readiness.
4. Enable the automation, wait for its cooldown to expire, then walk into Ring's
   motion zone. This package uses your confirmed timestamp sensor
   `sensor.doorbell_camera_last_motion`, with startup/unavailable exclusions and
   a 60-second cooldown. A new timestamp change should produce a trace and record.
5. If failure remains, read the specific reason and path:
   - `missing`: check the HA camera action trace, allowlist and exact filename.
     More timeout will not repair a denied or failed write.
   - `permission_denied`: verify the new startup directory preparation succeeded.
   - `path_mismatch`: replace the old/custom automation with the complete new file.
   - `empty` / `invalid_image`: Ring returned no image or an incomplete/invalid one.
   - `stale`: file timestamps are outside the attempt window; check supported HA
     time synchronization and ensure unique event/attempt names.
6. Check your existing visitor history and people remain present after update.
   A normal update uses the same app slug, data mount, SQLite schema and MQTT
   topics/unique IDs. There are no notifications, audible alerts or lock actions.

## Verification performed in the cloud

Regression tests render both complete HA YAML forms, assert camera filename,
MQTT path and app basename agree, validate allowlist/share mapping, test manual
and motion contexts, delayed writes beyond two seconds, configurable deadlines,
private umask/shared permissions, partial JPEG completion, stale/empty/invalid
files, symlinks, path mismatch and explicit filesystem errors. Existing model,
SQLite, enrollment and MQTT-discovery tests are also rerun.

`scripts/verify_handoff_containers.py --sample <public.jpg>` tests the same
`/share` Docker volume across separate containers, with a writer at UID 65534
and the app at UID 0, delaying the image for three seconds. It routes a Paho message through the production MQTT callback, uses actual
models, and verifies private history retention. It installs no broker and does not
pretend to call the live HA `camera.snapshot` API. The live steps above still
require your HAOS/Ring instance.

Latest executed results: **52 passed, 1 skipped** (live existing-broker test),
full Linux amd64 image build passed, and the separate-container handoff passed
with a three-second delayed write, one detected face, private retained image,
and an `unknown` event after about 3890 ms. Both test containers were capped at
one CPU / 384 MiB with no OOM kill. These are cloud checks, not live HAOS proof.

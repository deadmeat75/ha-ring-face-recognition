# Ring completed-recording capture — 0.2.0

## Confirmed source problem

The owner confirmed that a live Ring phone view showed a person while the HA
snapshot showed an empty porch, and that the saved event recording contains the
person. Inspection of released Home Assistant Core 2026.10.0 Ring code explains
this: `async_camera_image` extracts a still from `_video_url`, stores it in
`_images`, and only clears images when the recording ID changes. The same camera's
WebRTC live view is implemented separately. Its `live_view` name does not make
`camera.snapshot` a live-frame grab. Sampling the beginning of a recording can
also precede the person's arrival even when that recording contains them later.

Sources inspected:
- https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/ring/camera.py
- https://www.home-assistant.io/integrations/ring/
- https://www.home-assistant.io/integrations/downloader/
- https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/downloader/services.py

The live instance's Core version and service behavior cannot be inspected from
this cloud workspace. The observed behavior matches the released implementation;
this guide deliberately uses its supported completed-recording route instead of
pretending a unique JPEG filename forces a live Ring frame.

## Exact setup for this installation

1. Disable the existing **Ring Face – silent capture on motion** automation.
   Back up app data, then update the app normally to **0.2.0** and start it.
   Do not uninstall, replace Mosquitto, remove the Ring integration, or delete DB data.
2. Keep **Image days = 7** (or another positive value) in the app UI for pictures.
   Existing history, enrollment and broker settings are preserved; database schema
   stays at v2. Keep one OpenCV thread. No additional Ring credentials go in the app.
3. Keep the confirmed timestamp sensor enabled:
   **`sensor.front_porch_front_door_last_recording`**.
   It supplies the recording creation time for age checks / history. It may remain
   unknown until Ring supplies recording history; wait for a recent saved clip.
4. In HA **Settings → Devices & services → Add integration**, search **Downloader**
   and configure its download directory as **`/share`** (absolute path).
   The directory exists on HAOS. The app prepares `/share/ring_face/capture`;
   Downloader's `subdir: ring_face/capture` therefore targets that same shared
   location. Current HA uses a UI config flow: do not add the old `downloader:`
   YAML example from older documentation to configuration.yaml.
   If you already use Downloader with a different base directory, do not silently
   redirect other automations: first check its existing configuration and adapt
   those jobs or arrange a deliberate shared-directory setup. The published
   recording automation assumes its base is exactly `/share`.
5. Replace the existing capture automation in **Edit in YAML** with the complete
   [recording_automation.yaml](../home_assistant/recording_automation.yaml).
   Keep only that workflow enabled. It uses your existing
   `camera.doorbell_camera_live_view` entity's `last_video_id` **attribute change**
   as the ready-video trigger, not its snapshot service or the motion sensor.
   That ID is assigned by Ring's HA camera only once the recording is ready.
   The exact URL and ID are taken together from the triggering state, avoiding a
   switch to a different recording while an older queued job is downloading.
6. Walk into view / ring the bell, then allow Ring to **finish and upload the
   event recording**. HA polls recording history; processing can be delayed by
   the recording length, upload and polling. Do not expect a live or instant
   recognition result. Make sure motion recording is enabled in Ring and that
   the new saved clip actually contains you.
7. Reopen Web UI → Latest capture. It should say **App 0.2.0**, **MQTT connected**,
   and **Source: completed Ring recording**, with sampled/selected seconds.
   Open the retained private JPEG. It is selected from inside the clip, not the
   cached first still. If the source still says HA camera snapshot, an old
   automation is still publishing JPEG commands; disable/replace it.
8. For a controlled test, **Run actions** processes the current ready recording
   when it is no more than ten minutes old. A given Ring recording ID is processed
   once; running the same clip again does not create a new visitor record. Make
   a new recorded event for subsequent tests. Native recording URLs are signed
   and expire; use a new completed recording if the download fails.

No new snapshot allowlist entry or Core restart is needed for this route when
adding Downloader through its UI. Keep the existing `/share` app read/write map;
Core Downloader and the app must see the same `/share/ring_face/capture` directory.
The older JPEG diagnostic allowlist may remain for existing snapshot tests.

## What is processed and retained

- A new non-null `last_video_id` triggers one queued HA workflow (maximum 2).
  A clip may be a motion, press, or saved Ring live-view recording, depending on
  Ring's event history. Repeated polling with the same ID does not trigger work.
- Downloader writes a unique `ring_recording_<id>_1.mp4` and returns after the
  download completes. Only then is a non-retained MQTT command published.
- The signed URL stays in HA's action variables and Downloader. **It is not sent
  over MQTT, saved in this app's database, or logged by this app.** HA's own trace /
  integration logs may contain it; protect admin access and diagnostics exports.
- The app rejects unexpected paths, symlinks/FIFOs, empty files, files >64 MiB,
  inappropriate file mtimes and claimed recording times older than ten minutes.
  It copies the file to private `/data/video_work` using 64 KiB buffers and checks
  it did not change while copying. The copy is mode 0600 in a 0700 directory.
- The existing OpenCV FFmpeg backend opens that private local MP4 with one decode
  thread, network protocols disabled and external data references disabled.
  Clip limits are 180 seconds and 12 MP per frame. Unsupported / corrupt clips
  fail explicitly. HA Downloader writes the entire source clip before these app
  limits apply; keep Ring event duration reasonable to limit temporary disk use.
- At most five requested positions (1s, 3s, 6s, halfway and 80%, clipped/deduplicated
  for short recordings) are sampled. Frames are bounded to 1280 pixels, detection
  preview to 640. This is sparse sampling and can miss a very brief appearance.
  Seek timing depends on the container/codec; positions are approximate.
- Empty samples do not hide a face found later. Multiple faces or inconsistent
  identities across samples yield **ambiguous** with no chosen identity. Enrollment
  is not necessary to detect a face; unregistered detected faces remain Unknown.
- Decode and inference use the same single native worker and existing
  `processing_timeout` (default 20s); a timeout terminates the process. Do not
  increase concurrency on the memory-constrained laptop. If an actual native
  deadline occurs, measure load before considering a modest timeout increase.
- The downloaded shared MP4 and private work copy are deleted after processing.
  Crash-orphaned private copies are removed at app startup; stale shared MP4s
  expire during maintenance. No permanent video archive is created. Only the
  selected JPEG follows existing private image retention settings.

Ring ID, creation time, download mtime, selected offset and frame hash are recorded
as diagnostic metadata. These are **not cryptographically authenticated source
freshness**. Timing/ID correlation does not prove who was present or confer
access authorization. Freshness remains `unverified` or `repeated`. No unlocking,
announcements, routine notifications or third-party AI upload exists.

## Expected failures and live checks

- No new ready-video ID: inspect Ring's completed clip and HA Ring integration;
  no new recording means nothing for this workflow to decode.
- Recording timestamp unknown/older than ten minutes: the HA condition stops the
  job rather than mislabeling an older clip as current. Wait for a new clip and
  confirm the exact enabled timestamp sensor ID above.
- Downloader action missing / wrong base path: install/configure its existing
  supported UI integration and check the automation trace. The app cannot read
  Core's private `/config/downloads` directory.
- Signed URL unavailable/expired: inspect the HA Downloader action result and make
  a new event. Do not publish URLs or credentials into MQTT/chat as a workaround.
- recording_too_large / recording_limits: shorten Ring recording duration or
  investigate the codec; limits are intentional protections for this laptop.
- No face in sampled frames: inspect the saved clip and selected JPEG. Five sparse
  samples are not continuous tracking; poor framing, occlusion and lighting can
  still prevent detection.

The cloud tests use synthetic MP4s with a public face fixture and separate shared
containers. They cannot prove your live Downloader configuration, Ring ready-ID
updates, signed download, polling delay or Haswell latency. The steps above are
required instance validation; they have not been performed remotely.

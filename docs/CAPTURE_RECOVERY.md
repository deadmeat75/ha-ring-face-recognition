# Capture recovery — 0.1.3

The workspace cannot inspect the owner's live HA automation, MQTT connection or
Ring account. This release fixes reproducible code/workflow faults, supplies
clear live diagnostics, and provides the remaining instance checks explicitly.

## Faults addressed

1. The old automation published its command and then created an MQTT result
   listener. A fast (e.g. ~100 ms) result could precede that listener. With
   `mode: single`, a missed response could occupy the workflow for minutes and
   reject new motion. The replacement checks `event_id`, `attempt` and `status`
   attributes on the existing MQTT last-visitor sensor; it sees a result even if
   it arrived before the wait. Metadata is non-biometric and events remain
   non-retained. Distinct IDs prevent stale results satisfying a new capture.
2. Source IDs formerly relied on HA context IDs. Reuse of a context could make
   later state changes appear duplicate indefinitely. The replacement derives
   source IDs from each trigger state's last_changed timestamp.
3. 0.1.2 hid no-face records and deleted their images. A working capture pipeline
   could therefore appear idle. The top Latest capture panel now shows the newest
   outcome independently of filters, plus MQTT connection and command receipt /
   rejection status. It refreshes every 10 seconds in a visible browser tab;
   it never polls or triggers the camera. Original deleted images cannot return.
4. Empty/early frames stopped the old workflow immediately. A two-second approach
   delay and at most three captures now allow a later frame to contain the
   visitor. Only no_face/capture_failed outcomes retry; detected faces terminate
   the capture sequence. No continuous processing is introduced. Ring may still
   return cached/delayed frames; all source freshness remains unverified.

## Install

1. Back up app data. Update the existing app to **0.1.3** and restart it; do not
   uninstall, change its slug, replace your broker, or delete its database.
2. Set Image days to **7** (or another positive value) in the app's Retention
   section if you need viewable pictures. Zero remains an explicit no-image
   setting. The newest no-face diagnostic is kept for at most one day; older
   no-face pictures are removed, leaving normal history uncluttered. Other
   detected-face images follow normal retention. Text diagnostics still follow
   history retention. Valid capture images can also be inspected after inference
   errors, so capture and recognition failures are distinguishable.
3. Replace ONE existing HA automation with the full YAML below. Disable any old
   separate motion/press capture automation or package duplicate. If you use the
   package form, replace the package instead of also creating a UI copy.
4. Confirm `sensor.front_door_last_visitor` exists in your MQTT integration. App
   startup sends updated discovery to add event_id/attempt/status attributes.
   If you renamed that entity, substitute its actual ID in both wait templates.
   The app must be updated before this automation can use the new attributes.
5. Keep `/share/ring_face/capture` in Core's `homeassistant.allowlist_external_dirs`.
   No allowlist change / Core restart is required if the 0.1.1 handoff already works.
6. Reopen Web UI. Check the Latest capture panel says **App 0.1.3** and **MQTT:
   connected**. Stand facing the camera and use **Run actions** on the automation.
   Allow a few seconds for the two-second delay and camera operation. The panel
   should show a new capture and permit opening its picture if image retention
   is enabled. `no_face` means capture occurred but detection found no face.
7. Test walking up and a later bell press at least 60 seconds apart, allowing
   Ring's motion timestamp to update. The two triggers share one cooldown, so
   simultaneous motion/press activity cannot create duplicate processing.

## If the instance still fails

- **MQTT disconnected:** check this app's broker credentials and your existing
  broker's logs, without creating another broker or sharing secrets in chat.
- **No new command time after Run actions:** inspect the HA automation trace.
  It may not be enabled/loaded, the camera action may be stalled, or the publish
  action may not be reached. This is different from a hidden no-face event.
- **Command rejected:** the panel exposes why (expiry, duplicate/debounce, queue
  full/invalid input). Wait 10 seconds between manual tests; automatic triggers
  already have a 60-second cooldown. Do not loosen replay checks to hide failures.
- **capture_failed:** inspect the recorded specific error and identical camera /
  MQTT snapshot_path as documented in SNAPSHOT_HANDOFF.md.
- **no_face / repeated / empty-porch image:** inspect the retained diagnostic.
  Ring can supply an older cloud frame; a new local filename cannot solve source
  latency. Detection can also miss poorly lit, small or obscured faces. Enrollment
  does not improve face detection, and false matches must not be manufactured.
- **App gets records but automation still waits:** inspect the exact last-visitor
  entity ID and its event_id/attempt/status attributes. This release's template
  checks values already stored there, not receipt of a one-time MQTT message.

## Full UI automation (Edit in YAML)


```yaml
# Replace ONE existing automation. Keep only this capture automation enabled.
# Requires app 0.1.3 discovery attributes on sensor.front_door_last_visitor.
id: ring_face_capture_press
alias: Ring Face - silent capture on motion
mode: single
max_exceeded: silent
triggers:
  - trigger: state
    entity_id: sensor.doorbell_camera_last_motion
    not_from: ["unknown", "unavailable"]
    not_to: ["unknown", "unavailable"]
  - trigger: state
    entity_id: binary_sensor.doorbell_camera_ding
    from: "off"
    to: "on"
# Do not admit another capture until 60 seconds after the previous start.
# The existing automation ID is preserved so this replaces the press version.
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none and trigger.to_state is not none and
         trigger.from_state.state != trigger.to_state.state }}
  - condition: template
    value_template: >-
      {{ this.attributes.get('last_triggered') is none or
         as_timestamp(now()) - as_timestamp(this.attributes.get('last_triggered')) >= 60 }}
actions:
  - variables:
      source_id: >-
        {{ trigger.to_state.last_changed.strftime('%Y%m%dT%H%M%S%f') if trigger is defined and
           trigger.to_state is defined and trigger.to_state is not none
           else now().strftime('manual_%Y%m%dT%H%M%S%f') }}
      capture_id: "{{ now().strftime('%Y%m%dT%H%M%S%f') }}_{{ source_id }}"
      pressed_at: "{{ now().isoformat() }}"
  - delay: "00:00:02"
  - repeat:
      count: 3
      sequence:
        - variables:
            attempt: "{{ repeat.index }}"
            captured_at: "{{ now().isoformat() }}"
            snapshot_path: "/share/ring_face/capture/{{ capture_id }}_{{ repeat.index }}.jpg"
        - action: camera.snapshot
          continue_on_error: true
          target:
            entity_id: camera.doorbell_camera_live_view
          data:
            filename: "{{ snapshot_path }}"
        - action: mqtt.publish
          data:
            topic: ring_face_recognition/capture
            qos: 1
            retain: false
            payload: >-
              {{ {'event_id': capture_id, 'source_event_id': source_id,
                  'pressed_at': pressed_at, 'captured_at': captured_at,
                  'attempt': attempt | int, 'snapshot_path': snapshot_path} | to_json }}
        # State attributes persist even when the result arrived before this
        # wait started. A new MQTT listener could miss a fast result.
        - wait_template: >-
            {{ state_attr('sensor.front_door_last_visitor', 'event_id') == capture_id and
               (state_attr('sensor.front_door_last_visitor', 'attempt') | int(0)) >= (attempt | int) }}
          timeout: "00:02:10"
          continue_on_timeout: true
        - if:
            - condition: template
              value_template: >-
                {{ wait.completed and
                   state_attr('sensor.front_door_last_visitor', 'status') not in ['capture_failed', 'no_face'] }}
          then:
            - stop: Visitor event processed
        - delay: "00:00:03"
```

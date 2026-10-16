# 0.1.2

- Discard snapshots for no_face results; purge older no_face snapshots on startup/maintenance.
- Hide no_face diagnostic records from normal visitor history, with an explicit Show no-face events checkbox.
- Apply filtering before the history query limit so empty-porch events do not crowd out visitors.
- Keep unknown detected faces, recognition errors, people and enrollment templates unchanged.

# 0.1.1

- Require the actual Supervisor /share mount and declare its explicit read/write path.
- Prepare the exchange directories with shared permissions despite the private data umask.
- Add capture_timeout (default 10 seconds, range 1–60), interruptible on shutdown.
- Report missing/empty/invalid/stale/unsafe/permission/path mismatch errors distinctly.
- Reject truncated JPEGs and files changing during a read; keep source freshness unverified.
- Use a single snapshot_path for HA camera.snapshot and the MQTT handoff; retain old command compatibility.
- Preserve motion timestamp triggering, support manual Run actions, and extend acknowledgement wait
  to cover configured capture + inference deadlines. Bound retry command age to five minutes.
- Preserve visitor database, templates, private retention settings, MQTT credentials and silence.

# 0.1.0

Initial experimental app: ingress enrollment and private visitor history,
YuNet/SFace CPU worker, SQLite migrations, MQTT discovery, bounded capture
retries, explicit unverified freshness, and retention controls.
No authorization or lock actions.

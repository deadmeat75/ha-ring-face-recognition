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

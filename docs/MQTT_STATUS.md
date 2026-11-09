# MQTT status

Optional and off by default. Vapor Board can connect to an MQTT broker on the shop's network and show in the status bar whether the connection is up and how many messages it has seen.

In `shop.json`:

```json
{"mqtt_enabled": true, "mqtt_host": "192.168.1.20", "mqtt_port": 1883, "mqtt_topic": "msh/#"}
```

- **Receive-only:** the code can connect, subscribe and ping. It has no way to publish.
- **Contents are ignored:** messages are counted and discarded. Nothing reaches the boards, the messages page or the radio.
- **No password or TLS:** shop settings never hold credentials, so the broker must allow anonymous reads. Use a broker on your own network, not a public one.
- If the connection drops, it tries again every 30 seconds.

Not yet tested against a real broker.

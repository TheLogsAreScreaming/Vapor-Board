# MeshCore radios

Set `"radio_type": "meshcore"` in `shop.json` to connect to a MeshCore radio running companion firmware, over USB or its network port (usually 5000).

**This is listen-only.** The Overview page shows the connection and a count of messages received. Customer replies, boards and messages work only on Meshtastic, and `transmissions_enabled` has no effect on MeshCore.

Vapor Board sends the radio three local requests: start, device information, and next waiting message. None of them go on the air, and the code has no way to send a message or advert. Message text and senders are dropped when received and aren't stored. Reading a message does take it out of the radio's queue, so another app connected later won't receive it.

Not yet tested on a real radio.

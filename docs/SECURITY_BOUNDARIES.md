# Security boundary audit checklist

These tests assert existing guardrails: customer access requires both approval and age verification, customers cannot create boards, receive-only TCP cannot send, and default radio state is unverified and TX disabled.

**Not yet secure for public customer access:** Principal is a plain data class; callers can construct fake staff or approved identities. No trusted login/session layer or independent age-verification provider is implemented. Never expose AuthorizedBBS directly to untrusted network clients. Treat all current desktop BBS browsing as trusted local operator functionality only.

## Update (staff sign-in, customers, radio replies)

- The desktop now requires a staff sign-in (docs/STAFF_SIGN_IN.md). Customer records and approvals are kept by signed-in staff only (docs/CUSTOMERS.md).
- `ReceiveOnlyTcpClient.send` still always refuses. The radio link (`MeshtasticTcpClient`) sends only API control messages (want_config, heartbeat) unless `transmissions_enabled` is true, and then only direct text replies to approved customers (docs/RADIO_REPLIES.md).
- A radio node ID is not proof of identity: anyone who copies a customer's node ID could read the customer-visible boards and that customer's staff replies. Keep sensitive information off customer-visible boards and out of replies.

## Update check
Off by default. With `check_for_updates` true, or when someone chooses File ▸ Check for Updates, Vapor Board asks GitHub for the public release list. No shop data is sent, and nothing is downloaded or installed.

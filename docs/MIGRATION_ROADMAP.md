# Vapor Board implementation roadmap

## Phase 1: Foundation
- Audit THE SITDOWN BBS source files, dependencies, licenses, notices, and attribution before copying code.
- Port core BBS message/board engine and existing tests with neutral terminology.
- Remove Jersey-specific UI and hard-coded network names from the shop-facing experience.
- Preserve Intel Mac launch/build support and radio TCP handling.
- Never copy live credentials, customer data, or local configuration.

## Phase 2: Single-shop product
- One shop per installation, configured shop name, contact details, opening hours, and visual identity.
- Staff/admin authentication and role-scoped posting permissions.
- Moderated general announcements, questions, replies, pinned posts, expiration, and scheduled publication.
- Consent-based notification preferences; no unsolicited radio/MQTT broadcasting.
- Searchable local archive, audit logs, and safe backup/export.

## Phase 3: Connectivity
- Optional Meshtastic TCP connectivity; keep radio operation independent of internet.
- Optional receive-only MQTT status and diagnostics, default off.
- No automatic MQTT-to-radio or cross-network bridge.
- Any future outgoing transport requires explicit per-network operator approval, rate limits, deduplication, and field tests.
- MeshCore support requires an independent protocol adapter and testing, not an assumption of compatibility.

## Phase 4: Compliance and launch
- General store notices and customer service first.
- Age-restricted product promotions are out of initial scope until applicable federal/state/local legal review.
- Add age-appropriate access controls, privacy and retention policies, moderation, and accessibility.
- Run unit/integration tests, demo-mode checks, Intel Mac packaging tests, and physical radio tests.
- Publish release candidates only after acceptance testing.

## Initial acceptance criteria
1. Shop operator can configure one shop without editing source.
2. Authorized staff can post a general notice and moderate replies.
3. Customers can view permitted notices without staff privileges.
4. No automatic MQTT publish or radio transmission from shop announcements.
5. Existing radio BBS commands remain testable without internet.
6. Demo mode cannot connect to a live radio or broker.
7. Packaging and tests run on Intel Mac.

## Acceptance status (1.0.0 RC 1)
1. Configure one shop without editing source: **done** (shop.json, documented in the README).
2. Authorized staff post notices and moderate: **done** (staff sign-in; edit/delete/pin/schedule; customer messages arrive in the staff inbox).
3. Customers view permitted notices without staff privileges: **done** (kiosk; radio replies for approved customers; Visible/Staff only boards).
4. No automatic MQTT publish or radio transmission from announcements: **done** (no MQTT; radio only replies to direct requests, and only when turned on).
5. Radio BBS commands testable without internet: **done** (simulated radio tests; codec checked against official bindings).
6. Demo mode can't connect to a live radio or broker: **done** (`--demo`).
7. Packaging and tests run on Intel Mac: **done in CI** (macos-15-intel). Real-Mac click-through and physical radio tests are still open.

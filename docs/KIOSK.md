# Customer kiosk

**Start kiosk** (Overview page) turns the window into a read-only notice screen for customers on the shop counter.

- Shows only boards marked *Visible* on the Customers page, pinned posts first, with large text. Touch a board to read it.
- With nobody touching it, the kiosk moves to the next board every `kiosk_rotate_seconds` (shop.json, default 30; 0 turns rotation off).
- Starting the kiosk signs staff out. **Staff sign-in** (top right) opens the sign-in screen; *Back to kiosk* returns without signing in. Signing in leaves kiosk mode.
- Fills the screen by default (`kiosk_fullscreen`, default true).
- Nothing can be written, searched or sent from the kiosk, and it never uses the radio.
- Kiosk start and stop are in the activity log.

For an unattended shop display, run Vapor Board under a standard (non-admin) macOS user so customers can't reach other apps' settings.

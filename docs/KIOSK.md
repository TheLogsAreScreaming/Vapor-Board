# Customer kiosk

**Start kiosk** (Overview page) turns the window into a read-only notice screen for customers on the shop counter.

- Shows only boards marked *Visible* on the Customers page, pinned posts first, with large text. Touch a board to read it.
- With nobody touching it, the kiosk moves to the next board every `kiosk_rotate_seconds` (shop.json, default 30; 0 turns rotation off).
- Starting the kiosk signs staff out. **Staff sign-in** (top right) opens the sign-in screen; *Back to kiosk* returns without signing in. Signing in leaves kiosk mode.
- Fills the screen by default (`kiosk_fullscreen`, default true).
- **Branding** (shop.json): the header uses your `accent_color`. `kiosk_logo` is a PNG or GIF (a full path, or a file name inside `~/.vapor-board`) scaled to fit; if it can't be read the shop's initial is shown. `kiosk_tagline` replaces the line under the shop name (up to 120 characters). `kiosk_text_size` sets the notice size: `standard`, `large` (default) or `larger`.
- `shop_hours` and `shop_contact` (shop.json, up to 160 characters each) appear along the bottom of the kiosk.
- Nothing can be written, searched or sent from the kiosk, and it never uses the radio.
- Kiosk start and stop are in the activity log.

For an unattended shop display, run Vapor Board under a standard (non-admin) macOS user so customers can't reach other apps' settings.

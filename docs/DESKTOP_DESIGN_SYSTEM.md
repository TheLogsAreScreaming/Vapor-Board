# Desktop design system

All visual decisions live in `vapor_board/ui_theme.py`; wording lives in `vapor_board/ui_format.py`. Screens in `desktop.py` use only these.

- **Tokens:** light and dark palettes with the same semantic names (background, card, field, border, text, muted, subtle, success, warning, danger, info). The shop accent is adjusted per palette so white text on accent buttons and accent-coloured text both reach WCAG AA 4.5:1 (tested for many accents).
- **Spacing:** `XS 4, SM 8, MD 12, LG 16, XL 24, XXL 32`.
- **Type:** body, small, caption, label, button, headline, title, stat; scaled by `text_size` (`standard`, `large`, `larger`) in shop.json.
- **Appearance:** `appearance` in shop.json: `system` (follows macOS), `light`, `dark`.
- **Components:** `Card` (title, subtitle, header actions), `ListView` (roomy rows, keyboard navigation, auto-hiding scrollbar), `text_area`, `Pill` status badge, `Toast` non-blocking notices, `empty_state`, `field`.
- **Feedback:** success/info notices fade; warnings and errors stay until dismissed (Esc or ✕). Only destructive actions use a confirmation dialog (default button: No).
- **Motion:** the only animation is a gentle pulse while connecting, skipped when macOS Reduce Motion is on.
- **Keyboard:** ⌘1–6 pages, ⌘N new post/message, ⌘R refresh, ⌘L lock, ⌘↩ publish/send, Esc cancel edit, Return/Space press focused buttons, Delete removes the selected post (with confirmation).

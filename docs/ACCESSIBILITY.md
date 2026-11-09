# Accessibility

## What's covered

- **Keyboard:** every enabled control on a page can be reached with Tab, and CI checks this. Turn on *Keyboard navigation* in macOS System Settings ▸ Keyboard so Tab reaches buttons too. Page, new, refresh, search and lock shortcuts are shown in the status bar. Lists work with the arrow keys, and Escape closes a notice.
- **Text size:** Standard, Large and Larger in Settings. CI checks every page fits at large text.
- **Contrast:** text meant to be read is at least 4.5:1 in light and dark themes, for any shop accent colour, and CI checks this. Only disabled controls use a fainter colour.
- **Not colour alone:** statuses use words, and unread items also show a dot and bold text.
- **Motion:** the connecting animation stops when macOS Reduce Motion is on.

## VoiceOver

**VoiceOver support is limited and hasn't been tested.** The app is built with Tk, which draws most controls itself and tells macOS little about them, so VoiceOver may announce only part of the window. Testing can show how far it gets, but fixing it properly would mean moving to a different interface toolkit.

Until that's tested, don't describe the app as screen-reader accessible. A customer who can't use the kiosk should get help from staff.

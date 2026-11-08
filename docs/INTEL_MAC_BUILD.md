# Intel Mac build prototype

The workflow builds an unsigned, unnotarized Tkinter desktop preview into a macOS x86_64 .app and DMG. It is **not** a production release or proof of radio support. GitHub-hosted Intel macOS runner availability and PyInstaller build compatibility must be confirmed in Actions. The current desktop preview does not connect to a radio or expose a live BBS.

Run manually on an Intel Mac: `sh packaging/build_macos.sh`. Check GitHub Actions logs and inspect the uploaded artifact before distribution. macOS Gatekeeper may block unsigned bundles; do not disable system security protections to install them. Signing, notarization, app icon, hardened runtime and hardware testing are separate follow-ups.

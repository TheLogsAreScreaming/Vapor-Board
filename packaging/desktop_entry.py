"""PyInstaller entry point for package-relative desktop imports."""
import sys
from vapor_board.desktop import main


def self_test():
    """Headless check used by the build: modules load and the radio codec works. No window opens."""
    from vapor_board import __version__, meshwire, radio_replies, accounts, customers, export, demo  # noqa: F401
    decoded = meshwire.decode_from_radio(b"\x1a\x06\x08" + meshwire._varint(0xDEADBEEF))
    assert decoded == {"variant": "my_info", "node_num": 0xDEADBEEF}, decoded
    print(f"Vapor Board {__version__} self-test OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        self_test()
    else:
        main()

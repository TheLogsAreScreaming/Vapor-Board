import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class PackagingTests(unittest.TestCase):
    def test_entry_imports_package_main(self):
        source = (ROOT / "packaging" / "desktop_entry.py").read_text()
        tree = ast.parse(source)
        self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.module == "vapor_board.desktop" for node in ast.walk(tree)))
    def test_build_covers_both_mac_architectures(self):
        source = (ROOT / "packaging" / "build_macos.sh").read_text()
        for expected in ('x86_64', 'arm64', 'packaging/desktop_entry.py', 'Vapor-Board-$LABEL.dmg', 'codesign --force --deep --sign -'):
            self.assertIn(expected, source)

if __name__ == "__main__": unittest.main()

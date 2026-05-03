"""Entry point: launches the BatSim main window."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication


def main() -> int:
    # Discover plugins (built-in + user + data) before constructing UI
    import batsim.plugins.builtin  # noqa: F401  (registers core models/blocks)
    from batsim.plugins import discover
    counts = discover()
    print(f"[BatSim] plugins loaded: python={counts['python']} "
          f"cells={counts['cells']} bms={counts['bms']}")

    from batsim.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("BatSim")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

"""Entry point: launches the BatSim main window."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication


def main() -> int:
    # Discover plugins (built-in + user + data) before constructing UI
    import batsim_core.plugins.builtin  # noqa: F401  (registers core models/blocks)
    from batsim_core.plugins import discover
    counts = discover()
    print(f"[BatSim] plugins loaded: python={counts['python']} "
          f"cells={counts['cells']} bms={counts['bms']}")

    from batsim_core.ui.main_window import MainWindow
    from batsim_core.ui.fonts import setup_application_font
    from batsim_core.ui.style import apply_app_style
    app = QApplication(sys.argv)
    app.setApplicationName("BatSim")
    setup_application_font(app)
    apply_app_style(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())


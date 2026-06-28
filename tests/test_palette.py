import sys

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


def test_palette_basic_is_engineering_level_not_minimal():
    from batsim_core.ui.palette import PaletteWidget

    app = QApplication.instance() or QApplication(sys.argv)
    pal = PaletteWidget()
    try:
        basic = pal._lists["basic"]
        kinds = []
        for i in range(basic.count()):
            kind = basic.item(i).data(Qt.ItemDataRole.UserRole)
            if kind:
                kinds.append(kind)
        assert "R" in kinds
        assert "MOSFET" in kinds
        assert "BATPACK" in kinds
        assert "PCS" in kinds
        assert "JUNCTION" not in kinds
        assert len(kinds) >= 15
    finally:
        pal.close()


def test_palette_search_filters_components():
    from batsim_core.ui.palette import PaletteWidget

    app = QApplication.instance() or QApplication(sys.argv)
    pal = PaletteWidget()
    try:
        pal._filter.setText("pcs")
        basic = pal._lists["basic"]
        kinds = [basic.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(basic.count())]
        assert "PCS" in kinds
        assert "R" not in kinds
    finally:
        pal.close()


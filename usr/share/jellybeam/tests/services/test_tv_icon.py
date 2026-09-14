"""The customized build swaps the squashed wide icon for a square one."""

import pytest

from services import customization
from services.customization import ASSETS_DIR
from utils.constants import CUSTOMIZATION_ICON, JELLYFIN_ICON_FILE
from utils.exceptions import CustomizationInjectionError


def test_the_shipped_icon_exists_and_is_square():
    """It is a file in the package, not generated; make sure it ships."""
    icon = ASSETS_DIR / CUSTOMIZATION_ICON
    assert icon.is_file()
    dados = icon.read_bytes()
    assert dados[:8] == b"\x89PNG\r\n\x1a\n"
    largura = int.from_bytes(dados[16:20], "big")
    altura = int.from_bytes(dados[20:24], "big")
    assert largura == altura == 512


def test_replaces_the_package_icon_in_place(tmp_path):
    (tmp_path / JELLYFIN_ICON_FILE).write_bytes(b"wide wordmark")
    destino = customization.replace_icon(tmp_path)
    assert destino == tmp_path / JELLYFIN_ICON_FILE
    assert destino.read_bytes() == (ASSETS_DIR / CUSTOMIZATION_ICON).read_bytes()


def test_refuses_a_directory_that_is_not_a_package(tmp_path):
    """No icon.png means this is not the unpacked .wgt; do not create one."""
    with pytest.raises(CustomizationInjectionError):
        customization.replace_icon(tmp_path)
    assert not (tmp_path / JELLYFIN_ICON_FILE).exists()

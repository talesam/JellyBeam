"""The customized package carries our version and our symbol everywhere."""

import struct
import zlib

import pytest

from services import customization
from services.customization import ASSETS_DIR
from utils.constants import BRANDING_DIR, CUSTOMIZATION_APP_VERSION

CONFIG = ('<?xml version="1.0" encoding="UTF-8"?>\n'
          '<widget xmlns:tizen="http://tizen.org/ns/widgets" xmlns="http://www.w3.org/ns/widgets" '
          'id="http://jellyfin.org/Jellyfin" version="0.1.0" viewmodes="fullscreen">\n'
          '    <tizen:application id="AprZAARz4r.Jellyfin" package="AprZAARz4r" required_version="2.3"/>\n'
          '</widget>\n')


def _png(w, h):
    """A minimal valid PNG of the given size (1 grey pixel row repeated)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class TestVersion:
    def test_constant_is_a_release_number_and_not_upstreams(self):
        assert CUSTOMIZATION_APP_VERSION.count(".") == 2
        assert CUSTOMIZATION_APP_VERSION != "0.1.0"

    def test_writes_the_version_into_the_widget_tag(self, tmp_path):
        (tmp_path / "config.xml").write_text(CONFIG, encoding="utf-8")
        assert customization.set_package_version(tmp_path, "1.2.3") == "1.2.3"
        fonte = (tmp_path / "config.xml").read_text(encoding="utf-8")
        assert 'version="1.2.3"' in fonte and 'version="0.1.0"' not in fonte
        # required_version on the application element is not a widget version.
        assert 'required_version="2.3"' in fonte

    def test_default_is_the_constant(self, tmp_path):
        (tmp_path / "config.xml").write_text(CONFIG, encoding="utf-8")
        customization.set_package_version(tmp_path)
        assert f'version="{CUSTOMIZATION_APP_VERSION}"' in (tmp_path / "config.xml").read_text()

    def test_rejects_a_malformed_version(self, tmp_path):
        (tmp_path / "config.xml").write_text(CONFIG, encoding="utf-8")
        with pytest.raises(customization.CustomizationInjectionError):
            customization.set_package_version(tmp_path, "0.9")


class TestBranding:
    def test_shipped_symbols_cover_every_size_jellyfin_web_uses(self):
        tamanhos = set()
        for p in (ASSETS_DIR / BRANDING_DIR).glob("symbol-*.png"):
            tamanhos.add(customization._png_size(p.read_bytes()))
        # 536 icon-transparent, 512 touchicon, 440 notification, 180/144/114/72 touch icons
        assert {(536, 536), (512, 512), (440, 440), (180, 180), (144, 144), (114, 114), (72, 72)} <= tamanhos

    def test_replaces_by_size_and_banners_by_the_square_symbol(self, tmp_path):
        www = tmp_path / "www"
        (www / "favicons").mkdir(parents=True)
        (www / "banner-light.abc.png").write_bytes(_png(1302, 378))
        (www / "banner-dark.abc.png").write_bytes(_png(1302, 378))
        (www / "icon-transparent.abc.png").write_bytes(_png(536, 536))
        (www / "notificationicon.abc.png").write_bytes(_png(440, 440))
        (www / "touchicon144.abc.png").write_bytes(_png(144, 144))
        (www / "favicons" / "touchicon72.png").write_bytes(_png(72, 72))
        (www / "favicons" / "touchicon999.png").write_bytes(_png(999, 999))  # no symbol: left alone
        (www / "unrelated.png").write_bytes(_png(536, 536))

        trocados = customization.replace_branding(tmp_path)

        assert set(trocados) == {
            "www/banner-light.abc.png", "www/banner-dark.abc.png", "www/icon-transparent.abc.png",
            "www/notificationicon.abc.png", "www/touchicon144.abc.png", "www/favicons/touchicon72.png",
        }
        simbolo_536 = (ASSETS_DIR / BRANDING_DIR / "symbol-536.png").read_bytes()
        assert (www / "icon-transparent.abc.png").read_bytes() == simbolo_536
        # Wide banner -> the largest square symbol; the CSS contain-fits it.
        assert (www / "banner-light.abc.png").read_bytes() == simbolo_536
        assert customization._png_size((www / "favicons" / "touchicon999.png").read_bytes()) == (999, 999)
        assert (www / "unrelated.png").read_bytes() == _png(536, 536)

    def test_is_idempotent(self, tmp_path):
        www = tmp_path / "www"
        www.mkdir()
        (www / "icon-transparent.abc.png").write_bytes(_png(536, 536))
        customization.replace_branding(tmp_path)
        primeira = (www / "icon-transparent.abc.png").read_bytes()
        customization.replace_branding(tmp_path)
        assert (www / "icon-transparent.abc.png").read_bytes() == primeira

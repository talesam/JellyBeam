"""TV-only scripts shipped inside the package.

tv-fhd-versions.js: Jellyfin lists versions highest-resolution first and the
details page plays the selected one without fallback; on a Full HD Samsung set
that default is the one the native player refuses. The script preselects the
widest version that fits 1080p.
"""

import json
import shutil
import subprocess

import pytest

from services import customization
from services.customization import ASSETS_DIR, TV_SCRIPTS

INDEX = "<html><head></head><body><div id=app></div></body></html>"


def _pkg(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "index.html").write_text(INDEX, encoding="utf-8")
    return tmp_path


class TestInstall:
    def test_copies_the_script_and_references_it_once(self, tmp_path):
        pkg = _pkg(tmp_path)
        assert customization.install_tv_scripts(pkg) == list(TV_SCRIPTS)
        for nome in TV_SCRIPTS:
            assert (pkg / "www" / nome).read_bytes() == (ASSETS_DIR / nome).read_bytes()
        index = (pkg / "www" / "index.html").read_text(encoding="utf-8")
        assert index.count('<script src="tv-fhd-versions.js" defer></script>') == 1
        assert index.index("JellyBeam:tv") < index.index("</body>")

    def test_is_idempotent(self, tmp_path):
        pkg = _pkg(tmp_path)
        customization.install_tv_scripts(pkg)
        primeira = (pkg / "www" / "index.html").read_text(encoding="utf-8")
        customization.install_tv_scripts(pkg)
        assert (pkg / "www" / "index.html").read_text(encoding="utf-8") == primeira

    def test_leaves_the_server_resource_block_alone(self, tmp_path):
        pkg = _pkg(tmp_path)
        customization.inject(pkg / "www", "https://example.org")
        customization.install_tv_scripts(pkg)
        index = (pkg / "www" / "index.html").read_text(encoding="utf-8")
        assert "JellyBeam:start" in index and "JellyBeam:tv" in index
        assert customization.is_injected(pkg / "www")

    def test_missing_index_is_reported(self, tmp_path):
        (tmp_path / "www").mkdir()
        with pytest.raises(customization.CustomizationInjectionError):
            customization.install_tv_scripts(tmp_path)


class TestPickVersion:
    """The chooser, run as real JavaScript."""

    @staticmethod
    def _pick(sources):
        if not shutil.which("node"):
            pytest.skip("node not available")
        fonte = (ASSETS_DIR / "tv-fhd-versions.js").read_text(encoding="utf-8")
        script = (
            "var window = {}; var document = undefined;\n" + fonte +
            "\nprocess.stdout.write(JSON.stringify(window.JellyBeamVersions.pickVersion("
            + json.dumps(sources) + ")));"
        )
        saida = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        assert saida.returncode == 0, saida.stderr
        return json.loads(saida.stdout)

    @staticmethod
    def _source(id_, w, h):
        return {"Id": id_, "MediaStreams": [{"Type": "Audio"}, {"Type": "Video", "Width": w, "Height": h}]}

    def test_prefers_the_widest_version_that_fits(self):
        fontes = [self._source("uhd", 3840, 2080), self._source("fhd", 1920, 1080), self._source("hd", 1280, 720)]
        assert self._pick(fontes) == "fhd"

    def test_tall_1080p_scope_is_fine_but_2160_is_not(self):
        fontes = [self._source("uhd", 3840, 1606), self._source("scope", 1920, 800)]
        assert self._pick(fontes) == "scope"

    def test_nothing_fits_returns_null(self):
        assert self._pick([self._source("uhd", 3840, 2160)]) is None

    def test_sources_without_video_are_ignored(self):
        fontes = [{"Id": "audio", "MediaStreams": [{"Type": "Audio"}]}, self._source("fhd", 1920, 1080)]
        assert self._pick(fontes) == "fhd"

    def test_script_parses(self):
        if not shutil.which("node"):
            pytest.skip("node not available")
        r = subprocess.run(["node", "--check", str(ASSETS_DIR / "tv-fhd-versions.js")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

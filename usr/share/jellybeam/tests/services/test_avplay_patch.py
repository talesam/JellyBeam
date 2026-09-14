"""The AVPlay player stretches video unless told otherwise; the patch tells it.

The fixture below is the shape of jellyfin-tizen's avplayVideoPlayer.js around
the anchors the patch relies on, not the whole file.
"""

from services import customization
from services.customization import AVPLAY_FILE, CONFIG_FILE, POWER_PRIVILEGE

FIXTURE = """function _AvplayVideoPlayer(modules) {
    this.name = "AVPlay Video Player";

    this.canPlayMediaType = function (mediaType) {
        return (mediaType || '').toLowerCase() === 'video';
    };

    this.stop = function (destroyPlayer) {
        if (elem) {
            console.debug('stop 1', webapis.avplay.getState());
            webapis.avplay.pause();
            console.debug('stop 2', webapis.avplay.getState());
        }
    }

    this.pause = function () {
        webapis.avplay.pause();
        this.Events.trigger(this, 'pause');
    }

    this.unpause = function () {
        webapis.avplay.play();
        this.Events.trigger(this, 'unpause');
    }

    this.setCurrentSrc = function (elem, options) {
        var self = this;
        return new Promise(function (resolve, reject) {
            webapis.avplay.open(options.url);
            webapis.avplay.setDisplayRect(elem.offsetLeft, elem.offsetTop, elem.offsetWidth, elem.offsetHeight);

            webapis.avplay.prepareAsync(resolve, reject);
        });
    }
}
"""

CONFIG = """<?xml version="1.0" encoding="UTF-8"?>
<widget xmlns:tizen="http://tizen.org/ns/widgets" xmlns="http://www.w3.org/ns/widgets" id="http://jellyfin.org/Jellyfin">
    <tizen:privilege name="http://tizen.org/privilege/download"/>
    <tizen:privilege name="http://tizen.org/privilege/tv.inputdevice"/>
</widget>
"""


def _pkg(tmp_path, source=FIXTURE):
    (tmp_path / AVPLAY_FILE).write_text(source, encoding="utf-8")
    return tmp_path


class TestAvplayPatch:
    def test_adds_the_feature_and_applies_it_before_prepare(self, tmp_path):
        assert customization.patch_avplay(_pkg(tmp_path)) is True
        fonte = (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")

        # jellyfin-web asks for these to show the aspect-ratio menu.
        for metodo in ("this.supports", "this.getSupportedAspectRatios",
                       "this.getAspectRatio", "this.setAspectRatio"):
            assert metodo in fonte

        # The default keeps the video's own shape, and it is applied in IDLE:
        # after the display rect is set, before prepareAsync. LETTER_BOX, not
        # AUTO_ASPECT_RATIO: the latter stretched on a real set.
        assert "PLAYER_DISPLAY_MODE_LETTER_BOX" in fonte
        assert "AUTO_ASPECT_RATIO" not in fonte
        assert "'letterbox';" in fonte  # the fallback when nothing is saved
        rect = fonte.index("setDisplayRect(")
        apply = fonte.index("self._applyDisplayMethod();")
        prepare = fonte.index("prepareAsync(")
        assert rect < apply < prepare

    def test_turns_4k_on_between_open_and_prepare(self, tmp_path):
        customization.patch_avplay(_pkg(tmp_path))
        fonte = (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")
        abrir = fonte.index("webapis.avplay.open(")
        modo4k = fonte.index("'SET_MODE_4K', 'TRUE'")
        prepare = fonte.index("prepareAsync(")
        assert abrir < modo4k < prepare

    def test_holds_the_screen_only_while_playing(self, tmp_path):
        customization.patch_avplay(_pkg(tmp_path))
        fonte = (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")
        # Requested when playback is set up and on unpause; released on
        # pause and on stop.
        assert fonte.count("self._keepScreenOn(true);") == 1
        assert fonte.count("this._keepScreenOn(true);") == 1
        assert fonte.count("this._keepScreenOn(false);") == 2
        assert "tizen.power.request('SCREEN', 'SCREEN_NORMAL')" in fonte
        assert "tizen.power.release('SCREEN')" in fonte

    def test_is_idempotent(self, tmp_path):
        customization.patch_avplay(_pkg(tmp_path))
        primeira = (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")
        assert customization.patch_avplay(tmp_path) is True
        assert (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8") == primeira

    def test_standard_build_has_nothing_to_patch(self, tmp_path):
        """The HTML5 player keeps the aspect ratio by itself; no file, no patch."""
        assert customization.patch_avplay(tmp_path) is False

    def test_upstream_rewrite_is_skipped_not_fatal(self, tmp_path):
        _pkg(tmp_path, "function _AvplayVideoPlayer() { /* rewritten */ }\n")
        assert customization.patch_avplay(tmp_path) is False
        assert "JellyBeam" not in (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")

    def test_a_moved_hook_costs_only_that_hook(self, tmp_path):
        """pause() rewritten upstream: the rest of the patch still lands."""
        sem_pause = FIXTURE.replace("this.Events.trigger(this, 'pause');", "/* gone */")
        assert customization.patch_avplay(_pkg(tmp_path, sem_pause)) is True
        fonte = (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")
        assert "'SET_MODE_4K'" in fonte
        assert fonte.count("this._keepScreenOn(false);") == 1  # stop only


class TestConfigPrivileges:
    def test_adds_the_power_privilege_before_the_end(self, tmp_path):
        (tmp_path / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
        assert customization.patch_config_privileges(tmp_path) is True
        fonte = (tmp_path / CONFIG_FILE).read_text(encoding="utf-8")
        assert fonte.count(f'name="{POWER_PRIVILEGE}"') == 1
        assert fonte.index(POWER_PRIVILEGE) < fonte.index("</widget>")

    def test_does_not_duplicate_an_existing_one(self, tmp_path):
        (tmp_path / CONFIG_FILE).write_text(CONFIG, encoding="utf-8")
        customization.patch_config_privileges(tmp_path)
        assert customization.patch_config_privileges(tmp_path) is False
        fonte = (tmp_path / CONFIG_FILE).read_text(encoding="utf-8")
        assert fonte.count(f'name="{POWER_PRIVILEGE}"') == 1

"""The AVPlay player stretches video and draws no subtitles; the patch fixes both.

The fixture below is the shape of jellyfin-tizen's avplayVideoPlayer.js around
the anchors the patch relies on, not the whole file.
"""

from services import customization
from services.customization import AVPLAY_FILE

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
            var listener = {
                onsubtitlechange: function (duration, text, data3, data4) {
                    console.debug("subtitleText: " + text);
                }
            };
            webapis.avplay.open(options.url);
            webapis.avplay.setDisplayRect(elem.offsetLeft, elem.offsetTop, elem.offsetWidth, elem.offsetHeight);

            webapis.avplay.prepareAsync(resolve, reject);
        });
    }

    this.setSubtitleStreamIndex = function (streamIndex) {
        if (track) {
            webapis.avplay.setSelectTrack('TEXT', streamIndex);
        } else {
            webapis.avplay.setSilentSubtitle(true);
        }
    }
}
"""


def _pkg(tmp_path, source=FIXTURE):
    (tmp_path / AVPLAY_FILE).write_text(source, encoding="utf-8")
    return tmp_path


def _patched(tmp_path, source=FIXTURE) -> str:
    assert customization.patch_avplay(_pkg(tmp_path, source)) is True
    return (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")


class TestAspectRatio:
    def test_adds_the_feature_and_applies_it_before_prepare(self, tmp_path):
        fonte = _patched(tmp_path)
        # jellyfin-web asks for these to show the aspect-ratio menu.
        for metodo in ("this.supports", "this.getSupportedAspectRatios",
                       "this.getAspectRatio", "this.setAspectRatio"):
            assert metodo in fonte
        # LETTER_BOX by default, applied in IDLE: after the display rect is
        # set, before prepareAsync. Not AUTO_ASPECT_RATIO -- that stretched.
        assert "PLAYER_DISPLAY_MODE_LETTER_BOX" in fonte
        assert "AUTO_ASPECT_RATIO" not in fonte
        assert "'letterbox';" in fonte
        assert fonte.index("setDisplayRect(") < fonte.index("self._applyDisplayMethod();") < fonte.index("prepareAsync(")


class TestUhdAndScreen:
    def test_turns_4k_on_only_for_uhd_panels_before_prepare(self, tmp_path):
        fonte = _patched(tmp_path)
        assert fonte.index("webapis.avplay.open(") < fonte.index("'SET_MODE_4K', 'TRUE'") < fonte.index("prepareAsync(")
        # On a 1080p set it stopped playback outright, so it is gated.
        assert "isUdPanelSupported()" in fonte

    def test_holds_the_screen_saver_off_only_while_playing(self, tmp_path):
        fonte = _patched(tmp_path)
        # tizen.power does not exist on the TV; AppCommon does.
        assert "webapis.appcommon.setScreenSaver" in fonte
        assert "tizen.power.request" not in fonte
        assert fonte.count("self._keepScreenOn(true);") == 1   # playback set up
        assert fonte.count("this._keepScreenOn(true);") == 1   # unpause
        assert fonte.count("this._keepScreenOn(false);") == 2  # pause, stop


class TestSubtitles:
    def test_draws_each_cue_avplay_delivers(self, tmp_path):
        fonte = _patched(tmp_path)
        # The cue handler now draws instead of only logging.
        assert 'console.debug("subtitleText: " + text);\n                    self._showSubtitle(text, duration);' in fonte
        assert "this._showSubtitle = function (text, duration)" in fonte
        assert "jellybeam-subtitles" in fonte

    def test_reads_the_jellyfin_appearance_settings(self, tmp_path):
        fonte = _patched(tmp_path)
        assert "subtitleappearance" in fonte
        for campo in ("textSize", "dropShadow", "font", "textColor", "textBackground", "verticalPosition"):
            assert campo in fonte

    def test_only_harmless_markup_survives(self, tmp_path):
        """Cues carry <i> and <br>; anything else is stripped before innerHTML."""
        fonte = _patched(tmp_path)
        assert r"(i|b|u|br)" in fonte

    def test_hidden_when_switched_off_stopped_or_source_changes(self, tmp_path):
        fonte = _patched(tmp_path)
        assert "webapis.avplay.setSilentSubtitle(true);\n            this._hideSubtitle();" in fonte
        assert fonte.count("_hideSubtitle();") >= 3  # off, stop, new source


class TestRobustness:
    def test_is_idempotent(self, tmp_path):
        primeira = _patched(tmp_path)
        assert customization.patch_avplay(tmp_path) is True
        assert (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8") == primeira

    def test_standard_build_has_nothing_to_patch(self, tmp_path):
        """The HTML5 player keeps the aspect ratio and draws subtitles itself."""
        assert customization.patch_avplay(tmp_path) is False

    def test_upstream_rewrite_is_skipped_not_fatal(self, tmp_path):
        _pkg(tmp_path, "function _AvplayVideoPlayer() { /* rewritten */ }\n")
        assert customization.patch_avplay(tmp_path) is False
        assert "JellyBeam" not in (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")

    def test_a_moved_hook_costs_only_that_hook(self, tmp_path):
        """pause() rewritten upstream: the rest of the patch still lands."""
        sem_pause = FIXTURE.replace("this.Events.trigger(this, 'pause');", "/* gone */")
        fonte = _patched(tmp_path, sem_pause)
        assert "'SET_MODE_4K'" in fonte
        assert "self._showSubtitle(text, duration);" in fonte
        assert fonte.count("this._keepScreenOn(false);") == 1  # stop only

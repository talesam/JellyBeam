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

    this.getDeviceProfile = function (item, options) {
        return Promise.resolve({
            MaxStreamingBitrate: 120000000,
            CodecProfiles: [{ Type: 'Video', Codec: 'h264', Conditions: [] }],
            TranscodingProfiles: [
                { Container: 'mkv', Type: 'Video', Protocol: '' },
                { Container: 'ts', Type: 'Video', Protocol: 'hls' },
                { Container: 'mp4', Type: 'Video', Protocol: 'http' },
                { Container: 'aac', Type: 'Audio', Protocol: 'http' }
            ]
        });
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
        var self = this;
        if (track) {
            if (track.DeliveryMethod === 'External') {
                var downloadRequest = new tizen.DownloadRequest(window.ApiClient.getUrl(track.DeliveryUrl), 'wgt-private-tmp');
                tizen.download.start(downloadRequest, {});
            } else if (track.DeliveryMethod === 'Embed') {
                webapis.avplay.setSelectTrack('TEXT', streamIndex);
            }
        } else {
            webapis.avplay.setSilentSubtitle(true);
        }
    }

    this.setSubtitleOffset = function (offset) {
        var offsetValue = parseFloat(offset) * 1000;
    }
}
"""

SAMPLE_VTT = """WEBVTT

NOTE a comment block

1
00:00:01.000 --> 00:00:02.500
<i>Star City.</i> Luna 16,
you are crossing 100 km.

00:01:00.000 --> 00:01:01.000 align:start
Second cue

01:02:03,400 --> 01:02:04,000
Comma timestamps, SRT style
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
        assert "webapis.avplay.setSilentSubtitle(true);\n            this._clearVtt();" in fonte
        assert fonte.count("_clearVtt();") >= 3  # off, stop, new source

    def test_external_subtitles_bypass_tizen_download(self, tmp_path):
        """tizen.download stalled on the real set; the page fetches the .vtt itself."""
        fonte = _patched(tmp_path)
        externo = fonte.index("if (track.DeliveryMethod === 'External') {")
        nosso = fonte.index("self._loadExternalSubtitle(window.ApiClient.getUrl(track.DeliveryUrl));")
        download = fonte.index("new tizen.DownloadRequest(")
        assert externo < nosso < download  # ours runs first and returns
        assert "this._parseVtt = function" in fonte
        assert "webapis.avplay.getCurrentTime()" in fonte

    def test_offset_control_shifts_the_clock(self, tmp_path):
        fonte = _patched(tmp_path)
        assert "var offsetValue = parseFloat(offset) * 1000;\n        this._vttOffset = offsetValue || 0;" in fonte

    def test_vtt_parser_handles_real_cues(self, tmp_path):
        """Run the actual JS parser in node against a WebVTT sample."""
        import json
        import shutil
        import subprocess

        if not shutil.which("node"):
            import pytest
            pytest.skip("node not available")
        fonte = _patched(tmp_path)
        script = (
            "var webapis={}, tizen={}, window={}; var document={getElementById:function(){return null}};"
            "var console={debug:function(){},warn:function(){}};"
            "function localStorage(){}\n"
            + fonte +
            "\nvar p = new _AvplayVideoPlayer({});"
            "process.stdout.write(JSON.stringify(p._parseVtt(" + json.dumps(SAMPLE_VTT) + ")));"
        )
        saida = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        assert saida.returncode == 0, saida.stderr
        cues = json.loads(saida.stdout)
        assert [c["start"] for c in cues] == [1000, 60000, 3723400]
        assert cues[0]["end"] == 2500
        assert cues[0]["text"] == "<i>Star City.</i> Luna 16,\nyou are crossing 100 km."
        assert cues[2]["text"] == "Comma timestamps, SRT style"


class TestDeviceProfile:
    """What the player announces decides what the server streams."""

    def _run(self, tmp_path, uhd: bool):
        import json
        import shutil
        import subprocess

        if not shutil.which("node"):
            import pytest
            pytest.skip("node not available")
        fonte = _patched(tmp_path)
        script = (
            "var webapis={productinfo:{isUdPanelSupported:function(){return " + ("true" if uhd else "false") + "}}};"
            "var tizen={}, window={}; var document={getElementById:function(){return null}};"
            "var console={debug:function(){},warn:function(){}}; function localStorage(){}\n"
            + fonte +
            "\nvar p = new _AvplayVideoPlayer({});"
            # The stock method returns a Promise; the wrapper must keep that.
            "setTimeout(function(){ var r = p.getDeviceProfile({}, {});"
            " if (typeof r.then !== 'function') { process.stderr.write('not a promise'); process.exit(2); }"
            " r.then(function(d){ process.stdout.write(JSON.stringify(d)); }); }, 5);"
        )
        saida = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
        assert saida.returncode == 0, saida.stderr
        return json.loads(saida.stdout)

    def test_video_transcodes_only_over_hls(self, tmp_path):
        """Progressive transcodes failed to open on the set; HLS plays."""
        perfil = self._run(tmp_path, uhd=False)
        video = [t for t in perfil["TranscodingProfiles"] if t["Type"] == "Video"]
        assert [t["Protocol"] for t in video] == ["hls"]
        # Audio profiles are left alone.
        assert any(t["Type"] == "Audio" for t in perfil["TranscodingProfiles"])

    def test_1080p_panel_declares_its_size_so_4k_is_transcoded(self, tmp_path):
        perfil = self._run(tmp_path, uhd=False)
        conds = [c for cp in perfil["CodecProfiles"] for c in cp.get("Conditions", [])]
        assert {"Property": "Width", "Value": "1920"}.items() <= [c for c in conds if c["Property"] == "Width"][0].items()
        assert any(c["Property"] == "Height" and c["Value"] == "1080" for c in conds)

    def test_uhd_panel_keeps_full_resolution(self, tmp_path):
        perfil = self._run(tmp_path, uhd=True)
        conds = [c for cp in perfil["CodecProfiles"] for c in cp.get("Conditions", [])]
        assert not any(c["Property"] in ("Width", "Height") for c in conds)


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

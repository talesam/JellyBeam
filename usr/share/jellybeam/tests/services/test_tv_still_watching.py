"""tv-still-watching.js: no "Are you still watching?" left covering the picture.

Reproduced on an LSP3: OK on "Start now" in the Up Next card asks the
question while the episode plays on; when the episode ends the question is
asked again, on top. "Continue" on the top one starts the next episode with
the first question still covering it -- sound, no picture.

0.9.2 paused the episode with a synthetic Pause key; jellyfin reads that key
from KeyboardEvent.code, which engines before Chromium 48 do not have, and a
set was reported with buttons still on screen after "Continue". Now the
player is paused directly, and an answer given to the top question is given
to any left underneath.
"""

import json
import shutil
import subprocess

import pytest

from services import customization
from services.customization import ASSETS_DIR, AVPLAY_FILE, TV_SCRIPTS

SCRIPT = ASSETS_DIR / "tv-still-watching.js"


def _node(js: str, prelude: str = "var window = {}; var document = undefined;\n"):
    if not shutil.which("node"):
        pytest.skip("node not available")
    fonte = SCRIPT.read_text(encoding="utf-8")
    saida = subprocess.run(
        ["node", "-e", prelude + fonte + "\n" + js],
        capture_output=True, text=True, timeout=30,
    )
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout)


class TestIsPrompt:
    @pytest.mark.parametrize("ids,video,esperado", [
        (["cancel", "ok"], True, True),
        (["ok", "cancel"], True, True),
        (["cancel", "ok"], False, False),       # the same confirm elsewhere
        (["ok"], True, False),                  # an alert
        (["a", "b", "c"], True, False),         # an action sheet
        (["cancel", "ok", "x"], True, False),
    ])
    def test_only_a_confirm_over_the_video(self, ids, video, esperado):
        js = f"process.stdout.write(JSON.stringify(window.JellyBeamStillWatching.isPrompt({json.dumps(ids)}, {json.dumps(video)})))"
        assert _node(js) is esperado


class TestHowToPause:
    @pytest.mark.parametrize("estado,esperado", [
        ({"videoPlaying": True, "avplay": True, "avplayState": "PLAYING"}, "video"),
        ({"videoPlaying": False, "avplay": True, "avplayState": "PLAYING"}, "avplay"),
        ({"videoPlaying": False, "avplay": True, "avplayState": "PAUSED"}, "none"),
        ({"videoPlaying": False, "avplay": True, "avplayState": "NONE"}, "none"),
        # Never the key when a player is reachable: on Chromium < 48 it does nothing.
        ({"videoPlaying": False, "avplay": False, "avplayState": ""}, "key"),
    ])
    def test_the_player_is_paused_directly(self, estado, esperado):
        js = f"process.stdout.write(JSON.stringify(window.JellyBeamStillWatching.howToPause({json.dumps(estado)})))"
        assert _node(js) == esperado


# Just enough DOM to run the script: body, the video page, dialogs appended
# the way dialogHelper does it (closing removes them at once, as on a TV),
# an AVPlay player and a record of everything done to it.
FAKE_DOM = r"""
var window = {};
var keyListener = null;
window.addEventListener = function (type, fn) { if (type === 'keydown') { keyListener = fn; } };
var log = [];
var timers = [];
function setTimeout(fn) { timers.push(fn); }
function flush() { while (timers.length) { timers.shift()(); } }
var observers = [];
function MutationObserver(fn) { this.fn = fn; observers.push(this); }
MutationObserver.prototype.observe = function () {};
function KeyboardEvent(type, init) { this.type = type; this.code = init.code; }
var page = { classList: { hidden: false, contains: function () { return this.hidden; } } };
var dialogs = [];
var clickListener = null;
function cls(list) { return { list: list, contains: function (c) { return this.list.indexOf(c) >= 0; } }; }
function Dialog(ids, name) {
    var d = this;
    this.name = name;
    this.classList = cls(['dialog', 'opened']);
    this.style = {};
    var backdrop = { style: {}, classList: cls(['dialogBackdrop']) };
    this.parentNode = { previousElementSibling: backdrop, parentNode: document };
    this.backdrop = backdrop;
    this.buttons = ids.map(function (id) {
        return { parentNode: d, classList: cls(['btnOption']), getAttribute: function () { return id; },
                 focus: function () { document.activeElement = this; },
                 click: function () { clickListener({ target: this }); log.push(d.name + ':' + id); close(d); } };
    });
}
Dialog.prototype.querySelectorAll = function () { return this.buttons; };
Dialog.prototype.contains = function (n) { return this.buttons.indexOf(n) >= 0; };
Dialog.prototype.querySelector = function (sel) {
    return this.buttons.filter(function (b) { return sel.indexOf('"' + b.getAttribute() + '"') >= 0; })[0] || null;
};
var slider = { name: 'slider' };
var document = {
    activeElement: null,
    body: { contains: function (d) { return dialogs.indexOf(d) >= 0; },
            dispatchEvent: function (e) { log.push(e.type + ':' + e.code); } },
    querySelectorAll: function (sel) { return sel === '#videoOsdPage' ? [page] : dialogs.slice(); },
    querySelector: function () { return null; },
    addEventListener: function (type, fn) { if (type === 'click') { clickListener = fn; } }
};
var avState = 'PLAYING';
window.webapis = { avplay: { getState: function () { return avState; } } };
window.JellyBeamAvplay = { pause: function () { avState = 'PAUSED'; log.push('avplay.pause'); } };
function notify() { observers.forEach(function (o) { o.fn(); }); }
function open(ids, name) { var d = new Dialog(ids, name); dialogs.push(d); notify(); return d; }
function close(d) { dialogs.splice(dialogs.indexOf(d), 1); d.classList.list = []; notify(); }
function userClicks(d, id) { d.querySelector('"' + id + '"').click(); }
function out(v) { process.stdout.write(JSON.stringify(v)); }
function press(keyCode) {
    var ev = { keyCode: keyCode, stopped: false, prevented: false,
        stopPropagation: function () { this.stopped = true; }, preventDefault: function () { this.prevented = true; } };
    keyListener(ev);
    var a = document.activeElement;
    var where = a === slider ? 'slider' : (a && a.parentNode ? a.parentNode.name + ':' + a.getAttribute() : 'none');
    return [where, ev.stopped];
}
"""


class TestPause:
    def test_avplay_is_paused_directly_and_only_once(self):
        assert _node("open(['cancel', 'ok'], 'A'); open(['cancel', 'ok'], 'B'); out(log)",
                     prelude=FAKE_DOM) == ["avplay.pause"]

    def test_the_key_is_only_a_last_resort(self):
        assert _node("window.JellyBeamAvplay = undefined; open(['cancel', 'ok'], 'A'); out(log)",
                     prelude=FAKE_DOM) == ["keydown:Pause"]

    def test_the_prompt_is_shaded_not_opaque(self):
        assert _node("var d = open(['cancel', 'ok'], 'A'); out([d.style.background, d.backdrop.style.background])",
                     prelude=FAKE_DOM) == ["rgba(0, 0, 0, 0.45)", "transparent"]

    def test_menus_and_other_pages_are_left_alone(self):
        assert _node(
            "var a = open(['a', 'b', 'c'], 'menu'); page.classList.hidden = true; var b = open(['cancel', 'ok'], 'X');"
            "out([log, a.style, b.style])",
            prelude=FAKE_DOM,
        ) == [[], {}, {}]


class TestStackedPrompts:
    def test_continue_on_the_top_one_continues_the_one_underneath(self):
        # The reported set: two questions, "Continue" on the top one.
        assert _node(
            "var a = open(['cancel', 'ok'], 'A'); var b = open(['cancel', 'ok'], 'B');"
            "userClicks(b, 'ok'); flush(); out([log, dialogs.length])",
            prelude=FAKE_DOM,
        ) == [["avplay.pause", "B:ok", "A:ok"], 0]

    def test_stop_is_mirrored_too(self):
        assert _node(
            "var a = open(['cancel', 'ok'], 'A'); var b = open(['cancel', 'ok'], 'B');"
            "userClicks(b, 'cancel'); flush(); out([log, dialogs.length])",
            prelude=FAKE_DOM,
        ) == [["avplay.pause", "B:cancel", "A:cancel"], 0]

    def test_three_deep_all_answered_top_down(self):
        assert _node(
            "var a = open(['cancel', 'ok'], 'A'); var b = open(['cancel', 'ok'], 'B'); var c = open(['cancel', 'ok'], 'C');"
            "userClicks(c, 'ok'); flush(); out([log, dialogs.length])",
            prelude=FAKE_DOM,
        ) == [["avplay.pause", "C:ok", "B:ok", "A:ok"], 0]

    def test_a_single_prompt_is_not_touched_after_the_answer(self):
        assert _node(
            "var a = open(['cancel', 'ok'], 'A'); userClicks(a, 'ok'); flush();"
            "var b = open(['cancel', 'ok'], 'B'); flush(); out([log, dialogs.length])",
            prelude=FAKE_DOM,
        ) == [["avplay.pause", "A:ok"], 1]


class TestKeyAction:
    @pytest.mark.parametrize("key,dentro,esperado", [
        ("ArrowRight", True, "next"), ("ArrowDown", True, "next"),
        ("ArrowLeft", True, "prev"), ("ArrowUp", True, "prev"),
        ("Enter", True, "pass"),            # the button's own click
        ("ArrowRight", False, "enter"),     # focus already behind the prompt
        ("Enter", False, "enter"),          # OK on the seek bar would play
        ("Back", True, "pass"), ("MediaPlayPause", False, "pass"),
    ])
    def test_rules(self, key, dentro, esperado):
        js = f"process.stdout.write(JSON.stringify(window.JellyBeamStillWatching.keyAction({json.dumps(key)}, {json.dumps(dentro)})))"
        assert _node(js) == esperado


class TestKeysStayOnThePrompt:
    def test_the_reported_sequence_two_prompts_right_then_ok(self):
        # Seen on the LSP3: two prompts up, Right sent focus to the seek bar.
        assert _node(
            "var a = open(['cancel', 'ok'], 'A'); var b = open(['cancel', 'ok'], 'B');"
            "b.buttons[0].focus(); var r = press(39); var e = press(13);"
            "userClicks(b, 'ok'); flush(); out([r, e, dialogs.length, log])",
            prelude=FAKE_DOM,
        ) == [["B:ok", True], ["B:ok", False], 0, ["avplay.pause", "B:ok", "A:ok"]]

    def test_focus_behind_the_prompt_is_brought_back_not_played(self):
        assert _node(
            "var a = open(['cancel', 'ok'], 'A'); document.activeElement = slider;"
            "out([press(13), press(39)])",
            prelude=FAKE_DOM,
        ) == [["A:cancel", True], ["A:ok", True]]

    def test_edges_and_no_prompt(self):
        assert _node(
            "var r1 = press(39); var a = open(['cancel', 'ok'], 'A'); a.buttons[0].focus();"
            "var r2 = press(37); var r3 = press(39); var r4 = press(39);"
            "userClicks(a, 'ok'); document.activeElement = slider; var r5 = press(39);"
            "out([r1, r2, r3, r4, r5])",
            prelude=FAKE_DOM,
        ) == [["none", False], ["A:cancel", True], ["A:ok", True], ["A:ok", True], ["slider", False]]


class TestAvplayExposed:
    def test_the_patched_player_publishes_itself(self, tmp_path):
        fonte = (
            "function _AvplayVideoPlayer() {\n"
            "    this.canPlayMediaType = function (mediaType) {\n"
            "        return true;\n    };\n"
            "    this.setCurrentSrc = function () {\n"
            "            webapis.avplay.setDisplayRect(elem.offsetLeft, elem.offsetTop, elem.offsetWidth, elem.offsetHeight);\n"
            "    };\n}\n"
        )
        (tmp_path / AVPLAY_FILE).write_text(fonte, encoding="utf-8")
        assert customization.patch_avplay(tmp_path)
        assert "window.JellyBeamAvplay = this;" in (tmp_path / AVPLAY_FILE).read_text(encoding="utf-8")


def test_shipped_to_the_tv():
    assert "tv-still-watching.js" in TV_SCRIPTS


def test_script_parses():
    if not shutil.which("node"):
        pytest.skip("node not available")
    r = subprocess.run(["node", "--check", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

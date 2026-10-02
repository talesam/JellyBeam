"""tv-still-watching.js: pause the episode while "Are you still watching?" is up.

Reproduced on an LSP3: OK on "Start now" in the Up Next card asks the
question while the episode plays on; when the episode ends the question is
asked again, on top. "Continue" on the top one starts the next episode with
the first question still covering it -- sound, no picture. Paused, the
episode never ends, so the second question never comes.
"""

import json
import shutil
import subprocess

import pytest

from services.customization import ASSETS_DIR, TV_SCRIPTS

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


# Just enough DOM for the observer: body, the video page, dialogs appended
# the way dialogHelper does it, and a record of the keys dispatched.
FAKE_DOM = r"""
var window = {};
var observers = [];
function MutationObserver(fn) { this.fn = fn; observers.push(this); }
MutationObserver.prototype.observe = function () {};
function KeyboardEvent(type, init) { this.type = type; this.key = init.key; this.code = init.code; }
var sent = [];
var dialogs = [];
var page = { classList: { hidden: false, contains: function () { return this.hidden; } } };
function Dialog(ids) {
    this.buttons = ids.map(function (id) { return { getAttribute: function () { return id; } }; });
    this.style = {};
    var backdrop = { style: {}, classList: { contains: function (c) { return c === 'dialogBackdrop'; } } };
    this.parentNode = { previousElementSibling: backdrop };
    this.backdrop = backdrop;
}
Dialog.prototype.querySelectorAll = function () { return this.buttons; };
var document = {
    body: { dispatchEvent: function (e) { sent.push(e.type + ':' + e.code); } },
    querySelectorAll: function (sel) { return sel === '#videoOsdPage' ? [page] : dialogs; },
    addEventListener: function () {}
};
function open(ids) { dialogs.push(new Dialog(ids)); observers.forEach(function (o) { o.fn(); }); }
function close() { dialogs.shift(); observers.forEach(function (o) { o.fn(); }); }
"""


class TestObserver:
    def test_the_prompt_over_the_video_pauses_once(self):
        assert _node(
            "open(['cancel', 'ok']); observers[0].fn(); observers[0].fn();"
            "process.stdout.write(JSON.stringify(sent))",
            prelude=FAKE_DOM,
        ) == ["keydown:Pause"]

    def test_each_new_prompt_pauses(self):
        assert _node(
            "open(['cancel', 'ok']); close(); open(['cancel', 'ok']);"
            "process.stdout.write(JSON.stringify(sent))",
            prelude=FAKE_DOM,
        ) == ["keydown:Pause", "keydown:Pause"]

    def test_the_prompt_is_shaded_not_opaque(self):
        assert _node(
            "open(['cancel', 'ok']); var d = dialogs[0];"
            "process.stdout.write(JSON.stringify([d.style.background, d.backdrop.style.background]))",
            prelude=FAKE_DOM,
        ) == ["rgba(0, 0, 0, 0.45)", "transparent"]

    def test_menus_and_other_pages_are_left_alone(self):
        assert _node(
            "open(['a', 'b', 'c']); page.classList.hidden = true; open(['cancel', 'ok']);"
            "process.stdout.write(JSON.stringify([sent, dialogs.map(function (d) { return d.style; })]))",
            prelude=FAKE_DOM,
        ) == [[], [{}, {}]]


def test_shipped_to_the_tv():
    assert "tv-still-watching.js" in TV_SCRIPTS


def test_script_parses():
    if not shutil.which("node"):
        pytest.skip("node not available")
    r = subprocess.run(["node", "--check", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

"""tv-search-throttle.js: the typing gate and the result cap, run as real JS.

Measured on an LSP3: typing "top" fired 21 requests (7 per key, no debounce)
and the last answer landed 4 s after the last key. A first version gated the
requests and aborted superseded ones; React Query retried the aborts and the
on-screen keyboard became unusable. The gate now sits on the input event, so
React sees one change per pause in typing and nothing is ever cancelled.
"""

import json
import shutil
import subprocess

import pytest

from services.customization import ASSETS_DIR

SCRIPT = ASSETS_DIR / "tv-search-throttle.js"


def _node(js: str):
    if not shutil.which("node"):
        pytest.skip("node not available")
    fonte = SCRIPT.read_text(encoding="utf-8")
    prelude = "var window = {}; var document = undefined; var XMLHttpRequest = undefined;\n"
    saida = subprocess.run(
        ["node", "-e", prelude + fonte + "\nvar S = window.JellyBeamSearch;\n" + js],
        capture_output=True, text=True, timeout=30,
    )
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout)


class TestUrlHelpers:
    def test_only_search_urls_are_touched(self):
        assert _node("process.stdout.write(JSON.stringify(["
                     "S.isSearch('https://x/Items?searchTerm=top&limit=800'),"
                     "S.isSearch('https://x/Items?parentId=1&limit=800'),"
                     "S.isSearch('https://x/Persons?SearchTerm=a')]))") == [True, False, True]

    def test_cap_only_lowers_never_raises(self):
        assert _node("process.stdout.write(JSON.stringify(["
                     "S.capLimit('https://x/Items?searchTerm=t&limit=800&f=1'),"
                     "S.capLimit('https://x/Items?searchTerm=t&limit=20'),"
                     "S.capLimit('https://x/Items?searchTerm=t')]))") == [
            "https://x/Items?searchTerm=t&limit=60&f=1",
            "https://x/Items?searchTerm=t&limit=20",
            "https://x/Items?searchTerm=t",
        ]


class TestDebounce:
    """A manual scheduler stands in for setTimeout so the order is exact."""

    SETUP = """
var timers = {}; var next = 1; var log = [];
var later = S.createDebounce(500,
    function (fn, ms) { var h = next++; timers[h] = fn; return h; },
    function (h) { delete timers[h]; log.push('cancel ' + h); });
function fire() { Object.keys(timers).forEach(function (h) { var fn = timers[h]; delete timers[h]; fn(); }); }
"""

    def test_only_the_last_callback_runs(self):
        log = _node(self.SETUP + """
later(function () { log.push('t'); }); later(function () { log.push('to'); }); later(function () { log.push('top'); });
fire(); process.stdout.write(JSON.stringify(log));""")
        assert [x for x in log if not x.startswith("cancel")] == ["top"]
        assert len([x for x in log if x.startswith("cancel")]) == 2

    def test_separate_pauses_each_run(self):
        log = _node(self.SETUP + """
later(function () { log.push('top'); }); fire();
later(function () { log.push('top gun'); }); fire();
process.stdout.write(JSON.stringify(log));""")
        assert log == ["top", "top gun"]

    def test_nothing_is_ever_aborted_at_the_network(self):
        """The earlier design's mistake, pinned: no abort anywhere in the file."""
        fonte = SCRIPT.read_text(encoding="utf-8")
        assert ".abort(" not in fonte
        assert "AbortError" not in fonte


def test_script_parses():
    if not shutil.which("node"):
        pytest.skip("node not available")
    r = subprocess.run(["node", "--check", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

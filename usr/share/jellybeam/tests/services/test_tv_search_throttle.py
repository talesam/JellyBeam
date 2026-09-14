"""tv-search-throttle.js: the search gate and the result cap, run as real JS.

Measured on an LSP3: typing "top" fired 21 requests (7 per key, no debounce)
and the last answer landed 4 s after the last key. Two designs failed on the
set before this one: aborting superseded requests (React Query retried them
and the keyboard thrashed) and holding the input event back from React (a
controlled field loses letters on re-render). This gate never touches input
and never aborts: a superseded request is simply not sent.
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

    def test_path_and_term(self):
        assert _node("process.stdout.write(JSON.stringify(["
                     "S.pathOf('https://x/Items?searchTerm=top%20gun&a=1'), S.termOf('https://x/Items?searchTerm=top%20gun&a=1')]))") == [
            "https://x/Items", "top%20gun"]


class TestGate:
    """A manual scheduler stands in for setTimeout so the order is exact."""

    GATE = """
var queue = [];
var gate = S.createGate(500, function (fn, ms) { queue.push(fn); });
var log = [];
function req(path, term) { gate.request(path, term, function () { log.push('send ' + path + ' ' + term); }); }
"""

    def test_intermediate_terms_are_never_sent_final_one_is(self):
        log = _node(self.GATE + """
req('/Items', 't'); req('/Persons', 't');
req('/Items', 'to'); req('/Persons', 'to');
req('/Items', 'top'); req('/Persons', 'top');
while (queue.length) { queue.shift()(); }
process.stdout.write(JSON.stringify(log));""")
        assert log == ["send /Items top", "send /Persons top"]

    def test_a_single_term_goes_through(self):
        log = _node(self.GATE + "req('/Items', 'gun'); while (queue.length) { queue.shift()(); } process.stdout.write(JSON.stringify(log));")
        assert log == ["send /Items gun"]

    def test_endpoints_are_independent(self):
        log = _node(self.GATE + """
req('/Items', 'a'); req('/Persons', 'a'); req('/Items', 'ab');
while (queue.length) { queue.shift()(); }
process.stdout.write(JSON.stringify(log));""")
        assert log == ["send /Persons a", "send /Items ab"]

    def test_same_term_repeated_is_sent(self):
        log = _node(self.GATE + "req('/Items', 'x'); req('/Items', 'x'); while (queue.length) { queue.shift()(); } process.stdout.write(JSON.stringify(log));")
        assert log == ["send /Items x", "send /Items x"]


class TestLessonsPinned:
    def test_never_aborts_and_never_touches_the_input(self):
        fonte = SCRIPT.read_text(encoding="utf-8")
        assert ".abort(" not in fonte and "AbortError" not in fonte
        assert "stopImmediatePropagation" not in fonte and "addEventListener('input'" not in fonte


def test_script_parses():
    if not shutil.which("node"):
        pytest.skip("node not available")
    r = subprocess.run(["node", "--check", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

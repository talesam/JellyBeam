/* JellyBeam -- make search usable on a television.
 *
 * jellyfin-web's search page has no debounce: every keystroke starts seven
 * queries (people, artists, studios, video, programs, live TV, items) and
 * the items one asks for 800 results with full fields. A PC absorbs that; on
 * a Tizen set each response costs about half a second of network and JSON
 * parsing, so typing "top" queued eighteen requests and the last answer
 * arrived four seconds after the last key (measured on an LSP3).
 *
 * Two changes, applied where the requests leave the page:
 *   - a gate: a search request waits until typing has paused for WAIT ms;
 *     if a newer term for the same endpoint shows up meanwhile, the older
 *     request is cancelled before it ever reaches the network;
 *   - a cap: limit=N above MAX_LIMIT becomes MAX_LIMIT on search requests.
 * Covers XMLHttpRequest (the SDK) and fetch (the legacy ApiClient).
 */
(function () {
    'use strict';

    var WAIT = 500;
    var MAX_LIMIT = 60;

    function isSearch(url) {
        return /[?&]searchTerm=/i.test(String(url));
    }

    function capLimit(url, max) {
        max = max || MAX_LIMIT;
        return String(url).replace(/([?&])limit=(\d+)/i, function (m, sep, n) {
            return parseInt(n, 10) > max ? sep + 'limit=' + max : m;
        });
    }

    function pathOf(url) {
        var s = String(url);
        var i = s.indexOf('?');
        return i < 0 ? s : s.slice(0, i);
    }

    function termOf(url) {
        var m = /[?&]searchTerm=([^&]*)/i.exec(String(url));
        return m ? m[1] : '';
    }

    /* The gate. `schedule(fn, ms)` is injectable so tests can drive time.
     * request() returns nothing; it calls send() or cancel() later. */
    function createGate(wait, schedule) {
        var latest = {};
        return {
            request: function (path, term, send, cancel) {
                latest[path] = term;
                schedule(function () {
                    if (latest[path] === term) { send(); } else { cancel(); }
                }, wait);
            }
        };
    }

    if (typeof window !== 'undefined') {
        window.JellyBeamSearch = { isSearch: isSearch, capLimit: capLimit, createGate: createGate, termOf: termOf, pathOf: pathOf };
    }
    if (typeof XMLHttpRequest === 'undefined' || typeof document === 'undefined') { return; }

    var gate = createGate(WAIT, function (fn, ms) { setTimeout(fn, ms); });

    // --- XMLHttpRequest (axios / @jellyfin/sdk) ---
    var proto = XMLHttpRequest.prototype;
    var open = proto.open;
    var send = proto.send;
    proto.open = function (method, url) {
        this._jbSearch = isSearch(url);
        if (this._jbSearch) {
            url = capLimit(url);
            this._jbPath = pathOf(url);
            this._jbTerm = termOf(url);
        }
        var args = Array.prototype.slice.call(arguments);
        args[1] = url;
        return open.apply(this, args);
    };
    proto.send = function (body) {
        if (!this._jbSearch) { return send.call(this, body); }
        var xhr = this;
        gate.request(xhr._jbPath, xhr._jbTerm,
            function () { send.call(xhr, body); },
            function () { xhr.abort(); });
    };

    // --- fetch (legacy ApiClient) ---
    if (typeof window.fetch === 'function') {
        var fetch0 = window.fetch;
        window.fetch = function (input, init) {
            var url = (input && input.url) || input;
            if (!isSearch(url)) { return fetch0.apply(this, arguments); }
            var capped = capLimit(url);
            var self = this;
            return new Promise(function (resolve, reject) {
                gate.request(pathOf(capped), termOf(capped),
                    function () { fetch0.call(self, capped, init).then(resolve, reject); },
                    function () { reject(new DOMException('superseded by a newer search', 'AbortError')); });
            });
        };
    }
})();

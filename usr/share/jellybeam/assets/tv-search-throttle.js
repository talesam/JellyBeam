/* JellyBeam -- make search usable on a television.
 *
 * jellyfin-web's search page has no debounce: every keystroke starts seven
 * queries (people, artists, studios, video, programs, live TV, items), the
 * items one asking for 800 results with full fields. A PC absorbs that; on a
 * Tizen set each response costs about half a second of network and JSON
 * parsing, so typing "top" queued 21 requests and the last answer arrived
 * four seconds after the last key (measured on an LSP3).
 *
 * The fix acts where requests leave the page and touches nothing the user
 * types -- two earlier designs taught why:
 *   - aborting superseded requests made React Query retry them, and the
 *     retries thrashed the on-screen keyboard;
 *   - holding the input event back from React lost letters: React restores
 *     a controlled field to the value it knows on every re-render.
 * So: a search request waits WAIT ms; if a newer term for the same endpoint
 * has appeared by then, the older request is simply never sent -- no error,
 * no abort, nothing to retry. The caller's own cancellation (React Query's
 * AbortSignal) still works as before. limit=N above MAX_LIMIT is capped.
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
     * send() runs only if no newer term for that path arrived meanwhile;
     * otherwise nothing happens at all. */
    function createGate(wait, schedule) {
        var latest = {};
        return {
            request: function (path, term, send) {
                latest[path] = term;
                schedule(function () {
                    if (latest[path] === term) { send(); }
                }, wait);
            }
        };
    }

    if (typeof window !== 'undefined') {
        window.JellyBeamSearch = { isSearch: isSearch, capLimit: capLimit, createGate: createGate, termOf: termOf, pathOf: pathOf };
    }
    if (typeof document === 'undefined') { return; }

    var gate = createGate(WAIT, function (fn, ms) { setTimeout(fn, ms); });

    // --- XMLHttpRequest (axios / @jellyfin/sdk) ---
    if (typeof XMLHttpRequest !== 'undefined') {
        var proto = XMLHttpRequest.prototype;
        var open = proto.open;
        var send = proto.send;
        proto.open = function (method, url) {
            this._jbSearch = isSearch(url);
            var args = Array.prototype.slice.call(arguments);
            if (this._jbSearch) {
                args[1] = capLimit(url);
                this._jbPath = pathOf(url);
                this._jbTerm = termOf(url);
            }
            return open.apply(this, args);
        };
        proto.send = function (body) {
            if (!this._jbSearch) { return send.call(this, body); }
            var xhr = this;
            gate.request(xhr._jbPath, xhr._jbTerm, function () {
                // The caller may have cancelled it in the meantime.
                if (xhr.readyState === 1) { send.call(xhr, body); }
            });
        };
    }

    // --- fetch (legacy ApiClient) ---
    if (typeof window.fetch === 'function') {
        var fetch0 = window.fetch;
        window.fetch = function (input, init) {
            var url = (input && input.url) || input;
            if (typeof url !== 'string' || !isSearch(url)) { return fetch0.apply(this, arguments); }
            var capped = capLimit(url);
            var self = this;
            return new Promise(function (resolve, reject) {
                gate.request(pathOf(capped), termOf(capped), function () {
                    fetch0.call(self, capped, init).then(resolve, reject);
                });
            });
        };
    }
})();

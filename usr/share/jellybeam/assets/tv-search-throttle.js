/* JellyBeam -- make search usable on a television.
 *
 * jellyfin-web's search page has no debounce: every keystroke updates React
 * state, re-renders the page and starts seven queries (people, artists,
 * studios, video, programs, live TV, items), the items one asking for 800
 * results with full fields. A PC absorbs that; on a Tizen set the renders
 * and the responses pile up and the on-screen keyboard itself starts to lag.
 *
 * Two changes:
 *   - typing gate: the browser updates the text field instantly as usual,
 *     but React only hears about it once typing has paused for WAIT ms --
 *     one render, one round of queries. Nothing is cancelled or retried; an
 *     earlier version aborted in-flight requests and React Query's retries
 *     made the keyboard unusable.
 *   - cap: limit=N above MAX_LIMIT becomes MAX_LIMIT on search requests.
 */
(function () {
    'use strict';

    var WAIT = 500;
    var MAX_LIMIT = 60;
    var INPUT_ID = 'searchTextInput';

    function isSearch(url) {
        return /[?&]searchTerm=/i.test(String(url));
    }

    function capLimit(url, max) {
        max = max || MAX_LIMIT;
        return String(url).replace(/([?&])limit=(\d+)/i, function (m, sep, n) {
            return parseInt(n, 10) > max ? sep + 'limit=' + max : m;
        });
    }

    /* Trailing-edge debounce with an injectable scheduler (tests drive it).
     * Only the callback handed to the last call within `wait` runs. */
    function createDebounce(wait, schedule, cancel) {
        var handle = null;
        return function (fn) {
            if (handle !== null) { cancel(handle); }
            handle = schedule(function () { handle = null; fn(); }, wait);
        };
    }

    if (typeof window !== 'undefined') {
        window.JellyBeamSearch = { isSearch: isSearch, capLimit: capLimit, createDebounce: createDebounce };
    }
    if (typeof document === 'undefined') { return; }

    // --- typing gate ---
    // React listens at its root container; a capturing listener on document
    // runs first and can keep the event from ever reaching it. The field's
    // own value is already updated by then, so the user sees every letter.
    var later = createDebounce(WAIT,
        function (fn, ms) { return setTimeout(fn, ms); },
        function (h) { clearTimeout(h); });
    document.addEventListener('input', function (e) {
        var t = e.target;
        if (!t || t.id !== INPUT_ID || e.jellybeamReplay) { return; }
        e.stopImmediatePropagation();
        later(function () {
            var replay = new Event('input', { bubbles: true });
            replay.jellybeamReplay = true;
            t.dispatchEvent(replay);
        });
    }, true);

    // --- result cap ---
    if (typeof XMLHttpRequest !== 'undefined') {
        var open = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function (method, url) {
            var args = Array.prototype.slice.call(arguments);
            if (isSearch(url)) { args[1] = capLimit(url); }
            return open.apply(this, args);
        };
    }
    if (typeof window.fetch === 'function') {
        var fetch0 = window.fetch;
        window.fetch = function (input, init) {
            var url = (input && input.url) || input;
            if (typeof url === 'string' && isSearch(url)) {
                return fetch0.call(this, capLimit(url), init);
            }
            return fetch0.apply(this, arguments);
        };
    }
})();

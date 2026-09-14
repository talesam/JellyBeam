/* JellyBeam -- on a non-UHD panel, preselect the version that fits 1080p.
 *
 * Jellyfin lists an item's versions by resolution, highest first, and the
 * details page plays whatever the "Version" menu shows without falling back.
 * On a Full HD Samsung set the native player refuses anything above 1080p
 * (measured: 1080p SDR/HDR prepare, 4K SDR/HDR fail), so the default choice
 * is exactly the one that cannot play. This picks the widest version that
 * still fits the panel as soon as the menu appears. UHD panels are left alone.
 */
(function () {
    'use strict';

    var MAX_WIDTH = 1920;
    var MAX_HEIGHT = 1080;

    function fhdPanel() {
        try { return !webapis.productinfo.isUdPanelSupported(); } catch (e) { return false; }
    }

    function videoOf(source) {
        var streams = source.MediaStreams || [];
        for (var i = 0; i < streams.length; i++) {
            if (streams[i].Type === 'Video') { return streams[i]; }
        }
        return null;
    }

    /* The id of the widest version within the panel's limits, or null when
     * every version is too large (nothing to gain by switching). */
    function pickVersion(sources, maxWidth, maxHeight) {
        var best = null;
        var bestWidth = -1;
        for (var i = 0; i < sources.length; i++) {
            var video = videoOf(sources[i]);
            if (!video) { continue; }
            var w = video.Width || 0;
            var h = video.Height || 0;
            if (w <= (maxWidth || MAX_WIDTH) && h <= (maxHeight || MAX_HEIGHT) && w > bestWidth) {
                best = sources[i].Id;
                bestWidth = w;
            }
        }
        return best;
    }

    // Exposed for tests; the DOM work below is TV-only.
    if (typeof window !== 'undefined') {
        window.JellyBeamVersions = { pickVersion: pickVersion };
    }
    if (typeof document === 'undefined' || !fhdPanel()) { return; }

    function itemIdFromHash() {
        var m = /[#&?]id=([0-9a-f-]{32,36})/i.exec(window.location.hash);
        return m ? m[1].replace(/-/g, '') : null;
    }

    function apply(select) {
        // Once per page: the same menu is reused while the user is on it.
        if (select.getAttribute('data-jellybeam-page') === window.location.hash) { return; }
        var id = itemIdFromHash();
        if (!id || !window.ApiClient) { return; }
        select.setAttribute('data-jellybeam-page', window.location.hash);

        window.ApiClient.getItem(window.ApiClient.getCurrentUserId(), id).then(function (item) {
            var best = pickVersion(item.MediaSources || []);
            if (!best || select.value === best) { return; }
            var present = false;
            for (var i = 0; i < select.options.length; i++) {
                if (select.options[i].value === best) { present = true; break; }
            }
            if (!present) { return; }
            select.value = best;
            // The page listens for this to reload audio/subtitle menus and to
            // pass the version along when Play is pressed.
            select.dispatchEvent(new Event('change', { bubbles: true }));
            console.debug('[JellyBeam] FHD panel: version ' + best.slice(0, 8) + ' preselected');
        }).catch(function (e) {
            console.debug('[JellyBeam] version preselect skipped', e);
        });
    }

    function scan() {
        var select = document.querySelector('select.selectSource');
        if (select && select.options.length > 1) { apply(select); }
    }

    new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener('hashchange', function () { setTimeout(scan, 0); });
})();

/* JellyBeam -- pause the episode while "Are you still watching?" is up.
 *
 * jellyfin-web 10.11 asks before starting the next episode, and the episode
 * behind the question keeps playing. Reproduced on a set (LSP3): the "Up
 * next" card focuses "Start now" about 40 s before the end; OK there asks
 * the question while the episode plays on, and when the episode ends the
 * end-of-playback path asks it a second time, on top. "Continue" on the top
 * one starts the next episode -- sound, no picture: the first question is
 * still covering the screen. "Stop" on that leftover one stops everything.
 *
 * Paused, the episode cannot end, so there is never a second question. The
 * pause goes through jellyfin's own Pause key handling, so the player, the
 * OSD and the server all see an ordinary pause. "Continue" plays the next
 * episode as before; "Stop" stops. The prompt is also shaded instead of
 * opaque, so the paused picture stays in view behind the buttons.
 */
(function () {
    'use strict';

    /* The prompt is jellyfin's confirm(): exactly a cancel and an ok button.
     * Only over the video page -- the same dialog elsewhere is not ours. */
    function isPrompt(ids, onVideoPage) {
        if (!onVideoPage || ids.length !== 2) { return false; }
        return ids.indexOf('cancel') >= 0 && ids.indexOf('ok') >= 0;
    }

    if (typeof window !== 'undefined') {
        window.JellyBeamStillWatching = { isPrompt: isPrompt };
    }
    if (typeof document === 'undefined') { return; }

    function onVideoPage() {
        var pages = document.querySelectorAll('#videoOsdPage');
        for (var i = 0; i < pages.length; i++) {
            if (!pages[i].classList.contains('hide')) { return true; }
        }
        return false;
    }

    function buttonIds(dialog) {
        var botoes = dialog.querySelectorAll('.btnOption');
        var ids = [];
        for (var i = 0; i < botoes.length; i++) { ids.push(botoes[i].getAttribute('data-id')); }
        return ids;
    }

    function pause() {
        // keyboardnavigation maps the Pause key to playbackManager.pause().
        document.body.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Pause', code: 'Pause', bubbles: true, cancelable: true
        }));
    }

    /* On a TV the prompt is a full-screen opaque dialog. Shaded instead, so
     * the (paused) picture stays in view behind the two buttons. */
    function seeThrough(dialog) {
        dialog.style.background = 'rgba(0, 0, 0, 0.45)';
        var container = dialog.parentNode;
        var backdrop = container && container.previousElementSibling;
        if (backdrop && backdrop.classList.contains('dialogBackdrop')) {
            backdrop.style.background = 'transparent';
        }
    }

    var seen = typeof WeakSet === 'function' ? new WeakSet() : null;

    function check() {
        var abertos = document.querySelectorAll('.dialogContainer .dialog.opened');
        for (var i = 0; i < abertos.length; i++) {
            var d = abertos[i];
            if (seen ? seen.has(d) : d._jbSeen) { continue; }
            if (seen) { seen.add(d); } else { d._jbSeen = true; }
            if (isPrompt(buttonIds(d), onVideoPage())) {
                pause();
                seeThrough(d);
            }
        }
    }

    function start() {
        // dialogHelper appends the container to <body> and marks the dialog
        // "opened" in the same task, so by the time the observer runs (a
        // microtask later) it is already there. Direct children only: the
        // OSD rewrites its own subtree several times a second.
        new MutationObserver(check).observe(document.body, { childList: true });
    }

    if (document.body) { start(); } else { document.addEventListener('DOMContentLoaded', start); }
})();

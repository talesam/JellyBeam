/* JellyBeam -- keep "Are you still watching?" from leaving buttons behind.
 *
 * jellyfin-web 10.11 asks before starting the next episode, and the episode
 * behind the question keeps playing. Reproduced on a set (LSP3): the "Up
 * next" card focuses "Start now" about 40 s before the end; OK there asks
 * the question while the episode plays on, and when the episode ends the
 * end-of-playback path asks it a second time, on top. "Continue" on the top
 * one starts the next episode -- sound, no picture: the first question is
 * still covering the screen. "Stop" on that leftover one stops everything.
 *
 * Three guards:
 *   - the episode is paused while the question is up, so it cannot end and
 *     ask again. The player is paused directly: 0.9.2 sent a synthetic
 *     Pause key, which jellyfin reads from KeyboardEvent.code -- absent
 *     before Chromium 48 (Tizen 3), where the pause silently did nothing and
 *     a set still ended up with buttons on screen after "Continue";
 *   - if two questions are up anyway (OK pressed twice on "Start now" while
 *     the first one is still on its way), the answer given to the top one is
 *     given to the rest, so none is left covering the picture;
 *   - the remote stays on the question's buttons: the video page handles keys
 *     without looking for a dialog, and with two questions up Right sent
 *     focus to the seek bar behind them (fixed upstream in jellyfin-web PR
 *     8559, not yet in the build the TV gets).
 * The question is also shaded instead of opaque, so the paused picture stays
 * in view behind the buttons.
 */
(function () {
    'use strict';

    /* The prompt is jellyfin's confirm(): exactly a cancel and an ok button.
     * Only over the video page -- the same dialog elsewhere is not ours. */
    function isPrompt(ids, onVideoPage) {
        if (!onVideoPage || ids.length !== 2) { return false; }
        return ids.indexOf('cancel') >= 0 && ids.indexOf('ok') >= 0;
    }

    /* Which way to pause: the HTML5 <video> if that is what plays, else the
     * AVPlay player JellyBeam exposes (only when it is actually playing --
     * its pause() on a closed player throws), else jellyfin's Pause key. */
    function howToPause(s) {
        if (s.videoPlaying) { return 'video'; }
        if (s.avplay) { return s.avplayState === 'PLAYING' ? 'avplay' : 'none'; }
        return 'key';
    }

    var KEYS = { 13: 'Enter', 37: 'ArrowLeft', 38: 'ArrowUp', 39: 'ArrowRight', 40: 'ArrowDown' };

    /* A key while a prompt is the top dialog:
     *   pass  -- not ours (OK on one of its buttons clicks it natively)
     *   enter -- focus is outside the prompt: bring it back, swallow the key
     *   prev / next -- move between its buttons, swallow the key
     * The video page's own handler must never see these: with the OSD
     * hidden it sends Left/Right to the seek bar behind the prompt (seen on
     * a set: focus left the buttons and the episode skipped 33 s), Up/Down
     * show the OSD and focus its play button, and OK on the seek bar plays
     * the episode behind the prompt. */
    function keyAction(key, inPrompt) {
        var arrow = key === 'ArrowLeft' || key === 'ArrowRight' || key === 'ArrowUp' || key === 'ArrowDown';
        if (!arrow && key !== 'Enter') { return 'pass'; }
        if (!inPrompt) { return 'enter'; }
        if (key === 'Enter') { return 'pass'; }
        return key === 'ArrowLeft' || key === 'ArrowUp' ? 'prev' : 'next';
    }

    if (typeof window !== 'undefined') {
        window.JellyBeamStillWatching = { isPrompt: isPrompt, howToPause: howToPause, keyAction: keyAction };
    }
    if (typeof document === 'undefined') { return; }

    // The answer reaches the leftovers after the top one has closed and its
    // history entry has been popped; dialogHelper is not built for two
    // closing in the same tick.
    var MIRROR_DELAY = 400;

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
        var video = document.querySelector('video');
        var avplay = window.JellyBeamAvplay;
        var state = '';
        try { state = window.webapis.avplay.getState(); } catch (e) {}
        var how = howToPause({
            videoPlaying: !!(video && !video.paused),
            avplay: !!(avplay && typeof avplay.pause === 'function'),
            avplayState: state
        });
        try {
            if (how === 'video') {
                video.pause();
            } else if (how === 'avplay') {
                avplay.pause();
            } else if (how === 'key') {
                // keyboardnavigation maps the Pause key to playbackManager.pause().
                document.body.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'Pause', code: 'Pause', bubbles: true, cancelable: true
                }));
            }
        } catch (e) {
            console.warn('[JellyBeam] pause under the prompt failed', e);
        }
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

    var prompts = [];

    function isOpen(dialog) {
        return document.body.contains(dialog) && dialog.classList.contains('opened');
    }

    function answerLeftovers(answer) {
        setTimeout(function () {
            var restantes = prompts.filter(isOpen);
            prompts = restantes;
            if (!restantes.length) { return; }
            // One at a time, top first. The click goes through the capture
            // listener below like a user's would, which schedules the next.
            var alvo = restantes[restantes.length - 1];
            var botao = alvo.querySelector('.btnOption[data-id="' + answer + '"]');
            if (botao) { botao.click(); }
        }, MIRROR_DELAY);
    }

    function promptOf(node) {
        while (node && node !== document) {
            if (prompts.indexOf(node) >= 0) { return node; }
            node = node.parentNode;
        }
        return null;
    }

    // Capture phase: the button's own handler closes the dialog.
    document.addEventListener('click', function (e) {
        var botao = e.target;
        while (botao && !(botao.classList && botao.classList.contains('btnOption'))) {
            botao = botao.parentNode;
        }
        if (!botao || !promptOf(botao)) { return; }
        var outros = prompts.filter(function (d) { return d !== promptOf(botao) && isOpen(d); });
        if (outros.length) { answerLeftovers(botao.getAttribute('data-id')); }
    }, true);

    // Capture phase on window: ahead of every other listener, including the
    // seek bar's own Enter handler when focus has already landed there.
    window.addEventListener('keydown', function (e) {
        if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) { return; }
        var abertos = prompts.filter(isOpen);
        if (!abertos.length) { return; }
        var topo = abertos[abertos.length - 1];
        var ativo = document.activeElement;
        var acao = keyAction(KEYS[e.keyCode] || e.key || '', !!ativo && topo.contains(ativo));
        if (acao === 'pass') { return; }
        e.preventDefault();
        e.stopPropagation();
        var botoes = Array.prototype.slice.call(topo.querySelectorAll('.btnOption'));
        if (!botoes.length) { return; }
        var i = botoes.indexOf(ativo);
        var alvo = acao === 'enter' ? botoes[0]
            : botoes[Math.max(0, Math.min(botoes.length - 1, i + (acao === 'prev' ? -1 : 1)))];
        if (alvo && alvo !== ativo) { alvo.focus(); }
    }, true);

    var seen = typeof WeakSet === 'function' ? new WeakSet() : null;

    function check() {
        var abertos = document.querySelectorAll('.dialogContainer .dialog.opened');
        for (var i = 0; i < abertos.length; i++) {
            var d = abertos[i];
            if (seen ? seen.has(d) : d._jbSeen) { continue; }
            if (seen) { seen.add(d); } else { d._jbSeen = true; }
            if (isPrompt(buttonIds(d), onVideoPage())) {
                prompts.push(d);
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

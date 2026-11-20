// Jarvis film captions - runs in every page and frame (players are often inside an iframe).
// Reports the main video's position: once a second while playing, and at once on play/pause/seek.
(function () {
  if (window.__jarvisFilmCaptions) return;
  window.__jarvisFilmCaptions = true;

  function mainVideo() {
    let best = null;
    for (const video of document.querySelectorAll("video")) {
      if (video.readyState === 0) continue;
      const area = video.clientWidth * video.clientHeight;
      if (!best || (!video.paused && best.paused) ||
          (video.paused === best.paused && area > best.clientWidth * best.clientHeight)) best = video;
    }
    return best;
  }

  let last = 0;
  function report(force) {
    const video = mainVideo();
    if (!video) return;
    const now = Date.now();
    if (!force && (video.paused || now - last < 1000)) return;
    last = now;
    const src = video.currentSrc || "";
    try {
      chrome.runtime.sendMessage({
        type: "jarvis-video",
        page: location.href,
        time: video.currentTime,
        paused: video.paused,
        rate: video.playbackRate,
        duration: isFinite(video.duration) ? video.duration : 0,
        src: /^https?:/i.test(src) ? src : "",
      });
    } catch (e) { /* the extension was reloaded: this page needs a refresh */ }
  }

  // Media events do not bubble, but the capture phase on the document sees them.
  for (const name of ["play", "playing", "pause", "seeked", "ratechange", "loadedmetadata"]) {
    document.addEventListener(name, () => report(true), true);
  }
  setInterval(() => report(false), 1000);
})();

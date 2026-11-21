// Jarvis film captions - runs in every page and frame (players are often inside an iframe).
// Follows ONE player (the one that last played) through its own events instead of scanning the page:
// a report at once on play/pause/seek/buffering/end (grouped within 150 ms), and a heartbeat while a
// video is loaded — every second while it plays, every 3 s while it is paused.
(function () {
  if (window.__jarvisFilmCaptions) return;
  window.__jarvisFilmCaptions = true;

  let current = null;     // the followed <video>
  let stalled = false;    // buffering: the time does not move although it is «playing»
  let soon = null;
  let last = 0;

  function report() {
    soon = null;
    const video = current;
    if (!video || !video.isConnected) return;
    last = Date.now();
    const src = video.currentSrc || "";
    try {
      chrome.runtime.sendMessage({
        type: "jarvis-video",
        page: location.href,
        time: video.currentTime,
        paused: video.paused,
        stalled: stalled,
        ended: video.ended,
        rate: video.playbackRate,
        duration: isFinite(video.duration) ? video.duration : 0,
        src: /^https?:/i.test(src) ? src : "",
      });
    } catch (e) { /* the extension was reloaded: this page needs a refresh */ }
  }

  function soonReport() {
    if (!soon) soon = setTimeout(report, 150);
  }

  function follow(event) {
    const video = event.target;
    if (!(video instanceof HTMLVideoElement)) return;
    if (event.type === "playing" || event.type === "play") current = video;
    else if (!current && video.readyState > 0) current = video;
    if (video !== current) return;
    if (event.type === "waiting" || event.type === "stalled") stalled = true;
    if (event.type === "playing" || event.type === "seeked" || event.type === "pause") stalled = false;
    soonReport();
  }

  // A video that started before this script loaded: adopted at its next time update (cheap: only while
  // nothing is followed yet).
  document.addEventListener("timeupdate", (event) => {
    if (!current && event.target instanceof HTMLVideoElement && !event.target.paused) {
      current = event.target;
      soonReport();
    }
  }, true);

  // Media events do not bubble, but the capture phase on the document sees them.
  for (const name of ["play", "playing", "pause", "seeked", "ratechange", "loadedmetadata", "waiting",
                      "stalled", "ended", "emptied"]) {
    document.addEventListener(name, follow, true);
  }
  setInterval(() => {
    const video = current;
    if (!video || !video.isConnected) return;
    const every = video.paused ? 3000 : 1000;
    if (Date.now() - last >= every) report();
  }, 1000);
})();

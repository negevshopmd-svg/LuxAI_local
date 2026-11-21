// Jarvis film captions - runs in every page and frame (players are often inside an iframe).
// Follows ONE player (the one that last played) through its own events instead of scanning the page.
// While Jarvis shows captions: a report at once on play/pause/seek/buffering/end (grouped within 150 ms) and
// a heartbeat every second while it plays, every 3 s while it is paused. While captions are off, Jarvis is
// only asked (through the extension) every 10 s while a video plays — nothing about the page is sent.
(function () {
  if (window.__jarvisFilmCaptions) return;
  window.__jarvisFilmCaptions = true;

  const MEDIA = /\.(m3u8|mp4|webm|m4v|mov|mkv)$/i;

  // Media this frame loaded (playlists, files), from the page's own resource list: available when captions are
  // turned on in the middle of a film, without recording anything beforehand.
  function seenMedia() {
    try {
      return performance.getEntriesByType("resource")
        .map((entry) => entry.name)
        .filter((name) => { try { return MEDIA.test(new URL(name).pathname); } catch (e) { return false; } })
        .slice(-10);
    } catch (e) {
      return [];
    }
  }

  function newId() {
    return crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + String(Date.now());
  }

  let current = null;     // the followed <video>
  let stalled = false;    // buffering: the time does not move although it is «playing»
  let soon = null;
  let last = 0;
  let want = false;       // Jarvis wants reports now (answered by the extension)
  let doc = newId();      // this document (a new address in the page = a new one)
  let href = location.href;
  let seq = 0;            // reports are numbered: Jarvis ignores a late one
  let session = 0;        // a new source in the player = a new media session

  function report() {
    soon = null;
    const video = current;
    if (!video || !video.isConnected) return;
    if (location.href !== href) {
      href = location.href;
      doc = newId();
      seq = 0;
    }
    last = Date.now();
    seq += 1;
    const src = video.currentSrc || "";
    try {
      chrome.runtime.sendMessage({
        type: "jarvis-video",
        doc: doc,
        seq: seq,
        session: session,
        page: location.href,
        visible: document.visibilityState === "visible",
        focused: document.hasFocus(),
        time: video.currentTime,
        paused: video.paused,
        stalled: stalled,
        ended: video.ended,
        rate: video.playbackRate,
        duration: isFinite(video.duration) ? video.duration : 0,
        src: /^https?:/i.test(src) ? src : "",
        seen: want ? seenMedia() : [],
      }, (answer) => {
        void chrome.runtime.lastError; // no answer (the extension restarted): nothing to do
        want = !!(answer && answer.want);
      });
    } catch (e) { /* the extension was reloaded: this page needs a refresh */ }
  }

  function soonReport() {
    if (!soon) soon = setTimeout(report, 150);
  }

  function adopt(video) {
    if (video !== current) {
      current = video;
      session += 1; // another player element
      stalled = false;
    }
  }

  function follow(event) {
    const video = event.target;
    if (!(video instanceof HTMLVideoElement)) return;
    if (event.type === "playing" || event.type === "play") adopt(video);
    else if (!current && video.readyState > 0) adopt(video);
    if (video !== current) return;
    if (event.type === "loadstart" || event.type === "emptied") session += 1; // a new source (blob players too)
    if (event.type === "waiting" || event.type === "stalled") stalled = true;
    if (event.type === "playing" || event.type === "seeked" || event.type === "pause") stalled = false;
    if (want || event.type === "playing") soonReport();
  }

  // A video that started before this script loaded: adopted at its next time update (cheap: only while
  // nothing is followed yet).
  document.addEventListener("timeupdate", (event) => {
    if (!current && event.target instanceof HTMLVideoElement && !event.target.paused) {
      adopt(event.target);
      soonReport();
    }
  }, true);

  // Media events do not bubble, but the capture phase on the document sees them.
  for (const name of ["play", "playing", "pause", "seeked", "ratechange", "loadedmetadata", "loadstart",
                      "waiting", "stalled", "ended", "emptied"]) {
    document.addEventListener(name, follow, true);
  }
  // Back/forward restored this page from the browser's memory: it is a NEW document for Jarvis (the old one
  // was closed when the page was hidden), and the player's state is sent again at once (audit 5 #2).
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    doc = newId();
    seq = 0;
    href = location.href;
    soonReport();
  });
  // The page goes away (navigation, closed tab): its document is closed at once.
  window.addEventListener("pagehide", () => {
    try {
      chrome.runtime.sendMessage({ type: "jarvis-bye", doc: doc }, () => void chrome.runtime.lastError);
    } catch (e) { /* extension reloaded */ }
  });
  setInterval(() => {
    const video = current;
    if (!video || !video.isConnected) return;
    let every = video.paused ? 3000 : 1000;
    if (!want) {
      if (video.paused) return; // captions off and nothing plays: silence
      every = 10000;
    }
    if (Date.now() - last >= every) report();
  }, 1000);
})();

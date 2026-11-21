// Jarvis film captions - runs in every page and frame (players are often inside an iframe).
// Follows ONE player (the one that last played) through its own events instead of scanning the page.
// While Jarvis shows captions: a report at once on play/pause/seek/buffering/end (grouped within 150 ms) and
// a heartbeat every second while it plays, every 3 s while it is paused. While captions are off, Jarvis is
// only asked (through the extension) every 10 s while a video plays — nothing about the page is sent.
(function () {
  if (window.__jarvisFilmCaptions) return;
  window.__jarvisFilmCaptions = true;

  const MEDIA = /\.(m3u8|mp4|webm|m4v|mov|mkv)$/i;
  const MEDIA_TYPES = /mpegurl|video\/(mp4|webm|x-matroska|quicktime)|audio\/(mp4|mpeg|aac|webm)/i;
  const liveOnly = /(^|\.)(youtube\.com|youtube-nocookie\.com|youtu\.be)$/i.test(location.hostname);
  const resources = new Map();
  let observer = null;
  let resourceSnapshot = [];
  let publishedResources = null;

  // Read buffered resource timings on activation, then only inspect new entries.
  function rememberResources(entries) {
    let changed = false;
    for (const entry of entries) {
      const url = entry.name;
      const type = entry.contentType || "";
      if (!/^https?:/i.test(url) || !(MEDIA_TYPES.test(type) || MEDIA.test(new URL(url).pathname))) continue;
      resources.delete(url);
      resources.set(url, { url: url, type: type });
      if (resources.size > 10) resources.delete(resources.keys().next().value);
      changed = true;
    }
    if (changed) resourceSnapshot = [...resources.values()];
  }

  function trackResources(active) {
    if (liveOnly) return; // Jarvis can caption the audio YouTube is already playing.
    if (active && !observer) {
      observer = new PerformanceObserver((list) => {
        if (want) rememberResources(list.getEntries());
      });
      observer.observe({ type: "resource", buffered: true });
    } else if (!active && observer) {
      observer.disconnect();
      observer = null;
      resources.clear();
      resourceSnapshot = [];
      publishedResources = null;
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
  let audioPacket = null;

  function armBufferedAudio(reset = false) {
    if (!liveOnly) return;
    window.postMessage({ type: "jarvis-buffer-control", active: want && !document.hidden,
                         src: current?.currentSrc || "", reset }, location.origin);
  }

  if (liveOnly) {
    function checkBufferedAudio() {
      chrome.runtime.sendMessage({ type: "jarvis-buffer-check" }, (answer) => {
        if (chrome.runtime.lastError || current) return;
        want = !!answer?.want;
        armBufferedAudio();
      });
    }
    checkBufferedAudio();
    window.addEventListener("message", (event) => {
      const packet = event.data;
      if (!want || document.hidden || event.source !== window || event.origin !== location.origin
          || packet?.type !== "jarvis-buffer-audio" || !(packet.bytes instanceof ArrayBuffer)
          || packet.bytes.byteLength > 312 * 1024 || !["webm", "mp4"].includes(packet.kind)
          || !Number.isInteger(packet.track) || !Number.isFinite(packet.offset)) return;
      const video = current || document.querySelector("video, audio");
      if (!video || video.currentSrc !== packet.src) return;
      adopt(video);
      const bytes = new Uint8Array(packet.bytes);
      let encoded = "";
      for (let i = 0; i < bytes.length; i += 8192) encoded += String.fromCharCode(...bytes.subarray(i, i + 8192));
      audioPacket = { src: packet.src, kind: packet.kind, track: packet.track, offset: packet.offset,
                      data: btoa(encoded) };
      soonReport();
    });
    document.addEventListener("visibilitychange", () => armBufferedAudio(document.hidden));
  }

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
    const reportDoc = doc;
    const reportSeq = seq;
    const seen = want && resourceSnapshot !== publishedResources ? resourceSnapshot : undefined;
    const audio = liveOnly && want && !document.hidden && audioPacket?.src === src ? audioPacket : undefined;
    audioPacket = null;
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
        src: !liveOnly && /^https?:/i.test(src) ? src : "",
        seen: seen,
        buffer: audio && { kind: audio.kind, track: audio.track, offset: audio.offset, data: audio.data },
      }, (answer) => {
        void chrome.runtime.lastError; // no answer (the extension restarted): nothing to do
        if (doc !== reportDoc || seq !== reportSeq) return;
        want = !!(answer && answer.want);
        if (answer?.needSeen) publishedResources = null;
        else if (want && seen) publishedResources = seen;
        trackResources(want);
        armBufferedAudio();
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
      armBufferedAudio();
    }
  }

  function isPlayer(element) {
    return element instanceof HTMLVideoElement || (liveOnly && element instanceof HTMLAudioElement);
  }

  function follow(event) {
    const video = event.target;
    if (!isPlayer(video)) return;
    if (event.type === "playing" || event.type === "play") adopt(video);
    else if (!current && video.readyState > 0) adopt(video);
    if (video !== current) return;
    if (event.type === "loadstart" || event.type === "emptied") session += 1; // a new source (blob players too)
    if (event.type === "seeking") {
      audioPacket = null;
      armBufferedAudio(true);
    }
    if (event.type === "waiting" || event.type === "stalled") stalled = true;
    if (event.type === "playing" || event.type === "seeked" || event.type === "pause") stalled = false;
    if (want || event.type === "playing") soonReport();
  }

  // A video that started before this script loaded: adopted at its next time update (cheap: only while
  // nothing is followed yet).
  document.addEventListener("timeupdate", (event) => {
    if (!current && isPlayer(event.target) && !event.target.paused) {
      adopt(event.target);
      soonReport();
    }
  }, true);

  // Media events do not bubble, but the capture phase on the document sees them.
  for (const name of ["play", "playing", "pause", "seeking", "seeked", "ratechange", "loadedmetadata", "loadstart",
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
    trackResources(false);
    if (liveOnly) {
      want = false;
      armBufferedAudio(true);
    }
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

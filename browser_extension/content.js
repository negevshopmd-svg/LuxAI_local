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
  const discoveryLimit = 7000;
  let preparationLimit = 10000;  // Jarvis says how long the video may wait (setting «Wait for captions»)
  let underrunLimit = 8000;
  let seekLimit = 8000;          // after a jump: until the first phrase there is ready (Jarvis says when)
  const SEEK_JUMP = 10;          // seconds; smaller skips (arrow keys) are never held
  let seekAllowedAt = 0;         // rapid scrubbing holds once, not at every step
  let seekPending = false;
  let lastTime = 0;              // where the followed video was before a jump
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
  let canPreroll = false;
  let activeTab = false;
  let checkedSession = -1;
  let triedOpening = false;
  let opening = null;
  let retryAfter = 0;
  // Holding the video is limited per page: at most «preparationLimit» in total, however often the player
  // changes its source (a YouTube page plays one ad after another), and never for short videos (ads,
  // previews). A real test held a page for 70 s before this budget.
  const MIN_HELD_DURATION = 60;
  let heldMs = 0;
  let protectedSource = false;
  let gestureUntil = 0;

  function notePlaybackGesture(event) {
    if (opening && event.isTrusted) gestureUntil = performance.now() + 750;
  }
  document.addEventListener("pointerdown", notePlaybackGesture, true);
  document.addEventListener("keydown", (event) => {
    if (["Space", "KeyK", "Enter"].includes(event.code)) notePlaybackGesture(event);
  }, true);

  function releaseOpening(resume) {
    if (!opening) return;
    const held = opening;
    opening = null;
    if (held.kind !== "seek") {
      retryAfter = performance.now() + 30000;
      heldMs += performance.now() - held.started; // seeks have their own short limit, every time
    }
    clearTimeout(held.timeout);
    clearInterval(held.poll);
    // Resumed also when the source changed during the hold: the user pressed Play, the video must go on.
    if (resume && held.video.isConnected && held.video.paused && held.page === location.href) {
      held.video.play().catch(() => {}); // the native player still controls autoplay restrictions
    }
    soonReport();
  }

  function tryOpening(video, kind = "start") {
    const underrun = kind === "underrun";
    const seek = kind === "seek";
    if (!video || video !== current || opening) return;
    if (seek ? performance.now() < seekAllowedAt
             : (triedOpening && !(underrun && performance.now() >= retryAfter))) return;
    if (!canPreroll || !want || !activeTab || document.hidden
        || protectedSource || video.paused || video.seeking || video.ended
        || !(video.duration >= MIN_HELD_DURATION) || video.duration === Infinity
        || (!video.currentSrc && !video.src) || (video.muted && video.loop)) return;
    if (liveOnly && video.closest?.(".ad-showing")) return; // a YouTube ad: never held
    const budget = seek ? seekLimit
      : Math.min(underrun ? underrunLimit : preparationLimit, preparationLimit - heldMs);
    if (budget < 500) return; // this page has waited enough
    if (seek) seekAllowedAt = performance.now() + 4000;
    else triedOpening = true;
    gestureUntil = 0;
    opening = { video, session, page: location.href, position: video.currentTime, kind,
                started: performance.now(), limit: budget, preparing: false,
                timeout: setTimeout(() => releaseOpening(true), seek ? budget : Math.min(discoveryLimit, budget)),
                poll: setInterval(() => {
                  if (opening && !opening.video.paused) opening.video.pause();
                  soonReport();
                }, 280) };
    video.pause();
    soonReport();
  }

  function checkPlayer() {
    if (checkedSession === session) return;
    const requested = session;
    checkedSession = requested;
    try {
      chrome.runtime.sendMessage({ type: "jarvis-buffer-check" }, (answer) => {
        if (chrome.runtime.lastError || requested !== session) return;
        want = !!answer?.want;
        activeTab = want;
        canPreroll = !!answer?.preroll;
        trackResources(want);
        armBufferedAudio();
        tryOpening(current);
      });
    } catch (e) { /* extension was reloaded */ }
  }

  function encode(buffer) {
    const bytes = new Uint8Array(buffer);
    let encoded = "";
    for (let i = 0; i < bytes.length; i += 8192) encoded += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(encoded);
  }

  function resync() {
    window.postMessage({ type: "jarvis-buffer-resync" }, location.origin);
  }

  function armBufferedAudio(reset = false) {
    const src = current?.currentSrc || current?.src || "";
    if (!/^blob:/i.test(src) && !liveOnly && !reset) return;
    window.postMessage({ type: "jarvis-buffer-control", active: want && activeTab && !document.hidden && !protectedSource,
                         src, reset }, location.origin);
  }

  if (liveOnly) checkPlayer();
  if (/^https?:$/.test(location.protocol)) {
    window.addEventListener("message", (event) => {
      const packet = event.data;
      if (!want || document.hidden || protectedSource || event.source !== window || event.origin !== location.origin
          || packet?.type !== "jarvis-buffer-audio" || !(packet.header instanceof ArrayBuffer)
          || packet.header.byteLength > 32 * 1024 || !Array.isArray(packet.pieces) || packet.pieces.length > 512
          || !["webm", "mp4"].includes(packet.kind) || !Number.isInteger(packet.track)
          || !Number.isInteger(packet.epoch) || !Number.isFinite(packet.offset)) return;
      let total = 0;
      for (const piece of packet.pieces) {
        if (!(piece?.bytes instanceof ArrayBuffer) || !Number.isInteger(piece.n) || !Number.isInteger(piece.from)) return;
        total += piece.bytes.byteLength;
      }
      if (total > 2080 * 1024) return;
      const video = current || document.querySelector("video, audio");
      // Only the followed player, playing from a MediaSource (blob:) whose buffer the hook really read.
      if (!video || video.currentSrc !== packet.src || !/^blob:/i.test(packet.src)) return;
      adopt(video);
      const next = { src: packet.src, kind: packet.kind, track: packet.track, offset: packet.offset,
                     epoch: packet.epoch, full: packet.full === true, header: encode(packet.header),
                     pieces: packet.pieces.map((piece) => [piece.n, piece.from, encode(piece.bytes)]), size: total };
      // A packet not sent yet is merged, never dropped: every piece must reach Jarvis once.
      const old = audioPacket;
      if (old && !next.full && old.src === next.src && old.kind === next.kind && old.track === next.track
          && old.epoch === next.epoch && old.offset === next.offset && old.size + next.size <= 2080 * 1024) {
        next.full = old.full;
        next.pieces = old.pieces.concat(next.pieces);
        next.size += old.size;
      } else if (old && !next.full) {
        resync(); // cannot be merged: Jarvis will ask for (and get) the whole window
      }
      audioPacket = next;
      soonReport();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) releaseOpening(true);
      armBufferedAudio(document.hidden);
    });
  }

  function report() {
    soon = null;
    const video = current;
    if (!video || !video.isConnected) return;
    if (location.href !== href) {
      if (opening && opening.page !== location.href) releaseOpening(false);
      href = location.href;
      doc = newId();
      seq = 0;
      heldMs = 0; // a new page (another film) gets its own short wait
    }
    last = Date.now();
    seq += 1;
    const src = video.currentSrc || "";
    const reportDoc = doc;
    const reportSeq = seq;
    const seen = want && resourceSnapshot !== publishedResources ? resourceSnapshot : undefined;
    const audio = want && !document.hidden && audioPacket?.src === src ? audioPacket : undefined;
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
        preroll: opening?.video === video,
        prerollKind: opening?.video === video ? opening.kind : undefined,
        stalled: stalled,
        ended: video.ended,
        rate: video.playbackRate,
        duration: isFinite(video.duration) ? video.duration : 0,
        src: !liveOnly && /^https?:/i.test(src) ? src : "",
        seen: seen,
        buffer: audio && { kind: audio.kind, track: audio.track, offset: audio.offset, epoch: audio.epoch,
                           full: audio.full, header: audio.header, pieces: audio.pieces },
      }, (answer) => {
        void chrome.runtime.lastError; // no answer (the extension restarted): nothing to do
        if (doc !== reportDoc || seq !== reportSeq) return;
        want = !!(answer && answer.want);
        canPreroll = !!answer?.preroll;
        activeTab = !!answer?.active;
        if (Number.isFinite(answer?.holdMs)) preparationLimit = Math.max(0, Math.min(30000, answer.holdMs));
        if (Number.isFinite(answer?.underrunMs)) underrunLimit = Math.max(0, Math.min(15000, answer.underrunMs));
        if (Number.isFinite(answer?.seekMs)) seekLimit = Math.max(0, Math.min(15000, answer.seekMs));
        if (opening && answer?.openingPreparing && !opening.preparing) {
          opening.preparing = true;
          clearTimeout(opening.timeout);
          opening.timeout = setTimeout(() => releaseOpening(true),
                                       Math.max(0, opening.limit - (performance.now() - opening.started)));
        }
        if (opening && (answer?.openingReady || !want || !activeTab || video.duration === Infinity)) {
          releaseOpening(true);
        } else if (!opening) {
          tryOpening(video, answer?.underrun === true ? "underrun" : "start");
        }
        if (answer?.needFull) resync();
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
      releaseOpening(true);
      current = video;
      session += 1; // another player element
      triedOpening = false;
      protectedSource = false;
      stalled = false;
      checkPlayer();
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
    else if (!current && (event.type === "loadstart" || video.readyState > 0)) adopt(video);
    if (video !== current) return;
    if (event.type === "loadstart" || event.type === "emptied") {
      const starting = opening && event.type === "loadstart" && opening.page === location.href
          && Math.abs(video.currentTime - opening.position) < 0.8;
      if (!starting) releaseOpening(true);
      session += 1; // a new source (blob players too)
      if (starting) opening.session = session; // play can arrive before the first loadstart
      triedOpening = !!starting;
      protectedSource = false;
      if (event.type === "loadstart") checkPlayer();
    }
    if (event.type === "encrypted") {
      protectedSource = true;
      audioPacket = null;
      releaseOpening(true);
      armBufferedAudio(true);
    }
    if (event.type === "play" || event.type === "playing") {
      if (opening) {
        if (performance.now() < gestureUntil) releaseOpening(false);
        else video.pause(); // a player's automatic retry must not cancel preparation
      } else if (event.type === "play") {
        tryOpening(video);
      }
    }
    if (event.type === "seeking") {
      if (!opening || performance.now() < gestureUntil || Math.abs(video.currentTime - opening.position) > 0.8) {
        releaseOpening(true);
        audioPacket = null;
        armBufferedAudio(true);
      }
      stalled = true;
      // A real jump (the user or YouTube moved to another minute): once the player plays there, it waits a
      // moment until Jarvis has the first phrase of the new place ready.
      if (Math.abs(video.currentTime - lastTime) >= SEEK_JUMP) seekPending = true;
    }
    if (seekPending && (event.type === "seeked" || event.type === "playing") && !video.paused && !video.seeking) {
      seekPending = false;
      tryOpening(video, "seek");
    }
    if (event.type === "pause" && !opening) seekPending = false; // paused by the user: nothing to wait for
    if (event.type === "waiting" || event.type === "stalled") stalled = true;
    if (event.type === "playing" || event.type === "seeked" || event.type === "pause") stalled = false;
    if (want || event.type === "playing") soonReport();
  }

  // A video that started before this script loaded: adopted at its next time update (cheap: only while
  // nothing is followed yet).
  document.addEventListener("timeupdate", (event) => {
    if (event.target === current && !current.seeking) lastTime = current.currentTime;
    if (!current && isPlayer(event.target) && !event.target.paused) {
      adopt(event.target);
      soonReport();
    }
  }, true);

  // Media events do not bubble, but the capture phase on the document sees them.
  for (const name of ["play", "playing", "pause", "seeking", "seeked", "ratechange", "loadedmetadata", "loadstart",
                      "waiting", "stalled", "ended", "emptied", "encrypted"]) {
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
    releaseOpening(false);
    trackResources(false);
    want = false;
    armBufferedAudio(true);
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

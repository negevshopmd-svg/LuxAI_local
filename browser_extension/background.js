// Jarvis film captions - background (service worker).
// While Jarvis shows captions (and only then) it remembers which media each tab and frame requests (HLS
// playlists, mp4/webm, with the content type) in the browser's session storage and forwards the player's
// state from content.js to Jarvis on this computer (127.0.0.1 only). With captions off nothing is recorded,
// the lists are cleared, and only a «hello» (installed, version) is sent once a minute.
const JARVIS = "http://127.0.0.1:47321/v1/";
const MEDIA_PATH = /\.(m3u8|mp4|webm|m4v|mov|mkv)$/i;
const MEDIA_TYPES = /mpegurl|video\/(mp4|webm|x-matroska|quicktime)|audio\/(mp4|mpeg|aac|webm)/i;
const KEEP = 20;
const TIMEOUT = 4000;   // one request may take this long, then it is abandoned
const WANT_EVERY = 10000; // while Jarvis does not want reports, it is asked again at most this often

// -- pairing: the secret Jarvis wrote into this extension's folder (pairing.json) --
let token = null;
async function pairing(reload) {
  if (token && !reload) return token;
  try {
    const answer = await fetch(chrome.runtime.getURL("pairing.json"), { cache: "no-store" });
    token = answer.ok ? (await answer.json()).token || "" : "";
  } catch (e) {
    token = ""; // Jarvis has not created it yet: it does on its next start
  }
  return token;
}

// -- talking to Jarvis: a time limit, errors noticed, a pause while Jarvis is away --
let pausedUntil = 0;
let wanted = null;      // null until the first check after a worker restart
let wantAskedAt = 0;
let prerollSupported = false;
let holdLimits = { holdMs: 10000, underrunMs: 8000, seekMs: 8000 }; // how long Jarvis lets the video wait
let wantPending = null;

async function post(path, body) {
  if (Date.now() < pausedUntil) return null;
  for (let attempt = 0; attempt < 2; attempt++) {
    const stop = new AbortController();
    const timer = setTimeout(() => stop.abort(), TIMEOUT);
    let answer;
    try {
      answer = await fetch(JARVIS + path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jarvis-Token": await pairing(attempt > 0) },
        body: JSON.stringify(body),
        signal: stop.signal,
      });
    } catch (e) {
      pausedUntil = Date.now() + 10000; // Jarvis is not running (or hangs): try again in 10 s
      setWanted(false);
      return null;
    } finally {
      clearTimeout(timer);
    }
    if (answer.status === 401 && attempt === 0) continue; // new pairing: read pairing.json again
    if (answer.status === 400) {
      return { rejected: true }; // this one packet was refused (e.g. the tab went to the background)
    }
    if (!answer.ok) {
      pausedUntil = Date.now() + 5000;
      setWanted(false);
      return null;
    }
    try {
      const data = await answer.json();
      if (data && "want" in data) {
        // Every answer says whether the video may wait (the setting can change at any time).
        prerollSupported = data.preroll === true;
        if (Number.isFinite(data.hold_ms)) {
          holdLimits = { holdMs: data.hold_ms, underrunMs: data.underrun_ms, seekMs: data.seek_ms };
        }
      }
      if (data && "want" in data) {
        setWanted(!!data.want);
        wantAskedAt = Date.now();
      }
      return data;
    } catch (e) {
      return null;
    }
  }
  return null;
}

async function askWant() {
  if (wantPending) await wantPending;
  if (Date.now() - wantAskedAt >= WANT_EVERY) {
    wantAskedAt = Date.now();
    wantPending = post("want", {}).finally(() => { wantPending = null; });
    await wantPending;
  }
  return wanted;
}

// «I am installed»: Jarvis shows that the extension works (install guide, settings). Repeated every minute
// so an open install guide sees it soon; costs one tiny local request.
function hello() {
  post("hello", { version: chrome.runtime.getManifest().version, browser: navigator.userAgent.includes("Edg/") ? "edge" : "chrome" });
}
chrome.runtime.onInstalled.addListener(hello);
chrome.runtime.onStartup.addListener(hello);
chrome.alarms.create("jarvis-hello", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => { if (alarm.name === "jarvis-hello") hello(); });

// -- per tab: ONE request in flight; while it runs only the newest state waits (older ones are dropped),
// and a «closed» is always sent before a newer state, so the order Jarvis sees is the real one --
const waiting = new Map(); // tab -> { closed: [docs] | null, state: body | null }
const busy = new Set();
function enqueue(tab, kind, value) {
  const slot = waiting.get(tab) || { closed: null, state: null };
  if (kind === "closed") {
    slot.closed = (slot.closed || []).concat(value);
    // A state of a closed document must never arrive after the «closed»; another frame's state stays.
    if (!value.length || value.includes(slot.state?.doc)) slot.state = null;
  } else {
    const old = slot.state?.buffer;
    if (old && slot.state.doc === value.doc && slot.state.session === value.session && value.active && value.visible) {
      const next = value.buffer;
      if (!next) {
        value.buffer = old;
      } else if (!next.full && old.kind === next.kind && old.track === next.track && old.epoch === next.epoch
                 && old.offset === next.offset) {
        // Two packets waiting for one request: both sets of pieces go, in order (none is lost).
        value.buffer = { ...next, full: old.full, pieces: old.pieces.concat(next.pieces) };
      }
    }
    slot.state = value;
  }
  waiting.set(tab, slot);
  if (!busy.has(tab)) pump(tab);
}
async function pump(tab) {
  busy.add(tab);
  try {
    while (waiting.has(tab)) {
      const slot = waiting.get(tab);
      waiting.delete(tab);
      // «wanted» is null right after a restart: the close is still sent (Jarvis ignores unknown tabs).
      if (wanted !== false && slot.closed) await post("state", { event: "closed", tab: tab, docs: slot.closed });
      if (wanted && slot.state) {
        const state = slot.state;
        const result = await post(state.buffer ? "audio" : "state", state);
        const document = docs.get(tab)?.get(state.doc);
        if (document?.session === state.session) {
          document.underrun = result?.underrun === true;
          // Jarvis lost pieces, or this audio packet was refused: the next packet is the whole window.
          if (result?.need_full || (result?.rejected && state.buffer)) document.needFull = true;
        }
        if (document?.session === state.session && typeof result?.opening_ready === "boolean") {
          document.openingReady = result.opening_ready;
          document.openingPreparing = result.opening_preparing === true;
          document.openingHold = state.hold_id; // the answer belongs to THIS hold (audit 6 #4)
        }
      }
    }
  } finally {
    busy.delete(tab);
  }
}

// -- documents that reported, per tab: closed when they go away --
const docs = new Map(); // tab -> Map(doc -> { page, frame })
function closeDocs(tab, which) {
  const known = docs.get(tab);
  if (!known) return;
  const gone = [...known.entries()].filter(which).map(([doc]) => doc);
  for (const doc of gone) known.delete(doc);
  if (!known.size) docs.delete(tab);
  if (gone.length) enqueue(tab, "closed", gone);
}

// -- media seen per tab: one write queue, so two requests at once never overwrite each other --
let queue = Promise.resolve();
let mediaGeneration = 0;
function update(tabId, change) {
  const generation = mediaGeneration;
  const key = "media:" + tabId;
  queue = queue.then(async () => {
    if (generation !== mediaGeneration) return;
    const stored = (await chrome.storage.session.get(key))[key] || [];
    if (generation !== mediaGeneration) return;
    const next = change(stored);
    if (next === null) await chrome.storage.session.remove(key);
    else await chrome.storage.session.set({ [key]: next });
  }).catch(() => { /* storage refused: the list stays as it was */ });
  return queue;
}

function forgetMedia() {
  mediaGeneration += 1;
  queue = queue.then(() => chrome.storage.session.clear()).catch(() => {});
}

function setWanted(next) {
  if (wanted !== false && !next) {
    forgetMedia();
    docs.clear();
    waiting.clear();
  }
  if (!!next !== !!wanted) setPlayerHook(!!next);
  wanted = next;
}

// The hook that reads a player's buffered audio is always present only on YouTube (it must see the start of
// the audio track). On other sites it is registered only while Jarvis shows captions, for pages opened from
// then on, and removed again when they are turned off: with captions off no other site is touched.
const HOOK_ID = "jarvis-buffer-audio";
let hookChange = Promise.resolve();
function setPlayerHook(on) {
  hookChange = hookChange.then(async () => {
    const present = (await chrome.scripting.getRegisteredContentScripts({ ids: [HOOK_ID] })).length > 0;
    if (on && !present) {
      await chrome.scripting.registerContentScripts([{
        id: HOOK_ID, js: ["youtube_audio.js"], matches: ["http://*/*", "https://*/*"],
        excludeMatches: ["*://*.youtube.com/*", "*://*.youtube-nocookie.com/*"],
        allFrames: true, runAt: "document_start", world: "MAIN", persistAcrossSessions: false,
      }]);
    } else if (!on && present) {
      await chrome.scripting.unregisterContentScripts({ ids: [HOOK_ID] });
    }
  }).catch(() => { /* an older browser without dynamic MAIN-world scripts: YouTube still works */ });
}
setPlayerHook(false); // a restarted worker starts from «captions off» until Jarvis says otherwise

function usesLiveAudio(url) {
  try {
    return /(^|\.)(youtube\.com|youtube-nocookie\.com|youtu\.be)$/i.test(new URL(url).hostname);
  } catch (e) {
    return false;
  }
}

function remember(details, type) {
  // Only while Jarvis shows captions (audit 5 #11).
  if (!wanted || details.tabId < 0 || !/^https?:/i.test(details.url)) return;
  if (usesLiveAudio(details.documentUrl) || usesLiveAudio(details.initiator)) return;
  const item = { url: details.url, type: type || "", frame: details.frameId };
  // One entry per (frame, address): two frames loading the same playlist both keep it, and a type seen
  // before is not lost (audit 5 #5).
  const same = (old) => old.url === item.url && old.frame === item.frame;
  update(details.tabId, (stored) => {
    const before = stored.find(same);
    if (before && !item.type) item.type = before.type;
    return [item].concat(stored.filter((old) => !same(old))).slice(0, KEEP);
  });
}

chrome.webRequest.onBeforeRequest.addListener((details) => {
  try {
    if (MEDIA_PATH.test(new URL(details.url).pathname)) remember(details, "");
  } catch (e) { /* not a URL */ }
}, { urls: ["<all_urls>"] });

// Playlists without a file extension are recognised by their content type.
chrome.webRequest.onHeadersReceived.addListener((details) => {
  const type = (details.responseHeaders || []).find((h) => h.name.toLowerCase() === "content-type");
  if (type && MEDIA_TYPES.test(type.value || "")) remember(details, type.value);
}, { urls: ["<all_urls>"] }, ["responseHeaders"]);

// A closed tab: its list goes and Jarvis stops preparing its film. A new address in the tab: the top page's
// old document is closed (a page inside a frame says goodbye itself, see «jarvis-bye»).
chrome.tabs.onRemoved.addListener((tabId) => {
  if (wanted) update(tabId, () => null);
  if (docs.has(tabId)) closeDocs(tabId, () => true);
  else if (wanted !== false) enqueue(tabId, "closed", []); // documents unknown (worker restarted): the whole tab
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url) {
    if (wanted) update(tabId, () => null);
    closeDocs(tabId, ([, info]) => info.frame === 0 && info.page !== change.url);
  }
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!message || !sender.tab) return;
  const tab = sender.tab.id;
  if (message.type === "jarvis-bye") {
    closeDocs(tab, ([doc]) => doc === message.doc);
    return;
  }
  if (message.type === "jarvis-buffer-check") {
    askWant().then((active) => reply({ want: !!active && sender.tab.active, preroll: prerollSupported, ...holdLimits }),
                   () => reply({ want: false }));
    return true;
  }
  if (message.type !== "jarvis-video") return;
  (async () => {
    if (!(await askWant())) {
      reply({ want: false }); // captions are off in Jarvis: nothing about this page leaves the browser
      return;
    }
    const generation = mediaGeneration;
    if (!docs.has(tab)) docs.set(tab, new Map());
    const documents = docs.get(tab);
    const previous = documents.get(message.doc);
    const seen = Array.isArray(message.seen) ? message.seen : previous?.seen;
    const document = { page: message.page || "", frame: sender.frameId, seen, session: message.session,
                       underrun: previous?.session === message.session && previous.underrun,
                       openingPreparing: previous?.session === message.session && previous.openingPreparing,
                       openingReady: previous?.session === message.session && previous.openingReady,
                       openingHold: previous?.session === message.session ? previous.openingHold : 0 };
    documents.set(message.doc, document);
    const key = "media:" + tab;
    const liveOnly = usesLiveAudio(sender.url || message.page);
    await queue;
    const all = liveOnly ? [] : (await chrome.storage.session.get(key))[key] || [];
    if (!wanted || generation !== mediaGeneration || !docs.get(tab)?.has(message.doc)) {
      reply({ want: false });
      return;
    }
    // Only what the player's own frame loaded (an ad iframe has its own frame id), plus an address the
    // player itself names; never other frames' media at random (audit 4 #6).
    const own = all.filter((item) => item.frame === sender.frameId || (message.src && item.url === message.src));
    // What this frame itself loaded before captions were turned on (its own resource list, sent by content.js).
    for (const item of (liveOnly ? [] : seen) || []) {
      if (item && typeof item.url === "string" && /^https?:/i.test(item.url)
          && !own.some((entry) => entry.url === item.url)) own.push(item);
    }
    enqueue(tab, "state", {
      tab: tab,
      frame: sender.frameId,
      doc: message.doc,
      seq: message.seq,
      session: message.session,
      visible: message.visible,
      active: sender.tab.active,
      focused: message.focused && sender.tab.active,
      page: message.page || "",
      time: message.time,
      paused: message.paused,
      preroll: message.preroll === true && sender.tab.active && message.visible,
      preroll_kind: message.prerollKind === "seek" ? "seek" : "start",
      hold_id: Number.isInteger(message.holdId) ? message.holdId : 0,
      stalled: message.stalled,
      ended: message.ended,
      rate: message.rate,
      duration: message.duration,
      src: liveOnly ? "" : message.src || "",
      buffer: sender.tab.active && message.visible ? message.buffer : undefined,
      media: own.map((item) => ({ url: item.url, type: item.type })),
    });
    reply({ want: true, needSeen: !liveOnly && !seen, preroll: prerollSupported, ...holdLimits,
            underrun: !!document.underrun, openingReady: !!document.openingReady, openingPreparing: !!document.openingPreparing,
            holdId: document.openingHold || 0,
            needFull: !!previous?.needFull && previous.session === message.session, active: sender.tab.active });
  })().catch(() => reply({ want: false }));
  return true; // the answer comes asynchronously
});

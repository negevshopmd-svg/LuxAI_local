// Jarvis film captions - background (service worker).
// Remembers which media each tab and frame requested (HLS playlists, mp4/webm, with the content type) in the
// browser's session storage, and forwards the player's state from content.js to Jarvis on this computer
// (127.0.0.1 only) — and ONLY while Jarvis shows captions and asks for it.
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
let wanted = false;     // Jarvis shows captions and wants the player's state
let wantAskedAt = 0;

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
      wanted = false;
      return null;
    } finally {
      clearTimeout(timer);
    }
    if (answer.status === 401 && attempt === 0) continue; // new pairing: read pairing.json again
    if (!answer.ok) {
      pausedUntil = Date.now() + 5000;
      return null;
    }
    try {
      const data = await answer.json();
      if (data && "want" in data) {
        wanted = !!data.want;
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
  if (Date.now() - wantAskedAt >= WANT_EVERY) {
    wantAskedAt = Date.now();
    await post("want", {});
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
    slot.state = null; // a state of the closed document must never arrive after the «closed»
  } else {
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
      if (slot.closed) await post("state", { event: "closed", tab: tab, docs: slot.closed });
      if (slot.state) await post("state", slot.state);
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
function update(tabId, change) {
  const key = "media:" + tabId;
  queue = queue.then(async () => {
    const stored = (await chrome.storage.session.get(key))[key] || [];
    const next = change(stored);
    if (next === null) await chrome.storage.session.remove(key);
    else await chrome.storage.session.set({ [key]: next });
  }).catch(() => { /* storage refused: the list stays as it was */ });
  return queue;
}

function remember(details, type) {
  if (details.tabId < 0 || !/^https?:/i.test(details.url)) return;
  const item = { url: details.url, type: type || "", frame: details.frameId };
  update(details.tabId, (stored) => [item].concat(stored.filter((old) => old.url !== item.url)).slice(0, KEEP));
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
  update(tabId, () => null);
  if (docs.has(tabId)) closeDocs(tabId, () => true);
  else enqueue(tabId, "closed", []);
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url) {
    update(tabId, () => null);
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
  if (message.type !== "jarvis-video") return;
  (async () => {
    if (!(await askWant())) {
      reply({ want: false }); // captions are off in Jarvis: nothing about this page leaves the browser
      return;
    }
    if (!docs.has(tab)) docs.set(tab, new Map());
    docs.get(tab).set(message.doc, { page: message.page || "", frame: sender.frameId });
    const key = "media:" + tab;
    const all = (await chrome.storage.session.get(key))[key] || [];
    // Only what the player's own frame loaded (an ad iframe has its own frame id), plus an address the
    // player itself names; never other frames' media at random (audit 4 #6).
    const own = all.filter((item) => item.frame === sender.frameId || (message.src && item.url === message.src));
    enqueue(tab, "state", {
      tab: tab,
      frame: sender.frameId,
      doc: message.doc,
      seq: message.seq,
      session: message.session,
      visible: message.visible,
      focused: message.focused && sender.tab.active,
      page: message.page || "",
      time: message.time,
      paused: message.paused,
      stalled: message.stalled,
      ended: message.ended,
      rate: message.rate,
      duration: message.duration,
      src: message.src || "",
      media: own.map((item) => ({ url: item.url, type: item.type })),
    });
    reply({ want: true });
  })().catch(() => reply({ want: false }));
  return true; // the answer comes asynchronously
});

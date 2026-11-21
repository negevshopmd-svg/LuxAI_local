// Jarvis film captions - background (service worker).
// Remembers which media each tab and frame requested (HLS playlists, mp4/webm, with the content type)
// and forwards the player's state from content.js to Jarvis on this computer (127.0.0.1 only).
const JARVIS = "http://127.0.0.1:47321/v1/";
const MEDIA_PATH = /\.(m3u8|mp4|webm|m4v|mov|mkv)$/i;
const MEDIA_TYPES = /mpegurl|video\/(mp4|webm|x-matroska|quicktime)|audio\/(mp4|mpeg|aac|webm)/i;
const KEEP = 20;

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

// -- talking to Jarvis: errors are noticed and the extension backs off while Jarvis is away --
let pausedUntil = 0;
async function send(path, body) {
  if (Date.now() < pausedUntil) return;
  for (let attempt = 0; attempt < 2; attempt++) {
    let answer;
    try {
      answer = await fetch(JARVIS + path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jarvis-Token": await pairing(attempt > 0) },
        body: JSON.stringify(body),
      });
    } catch (e) {
      pausedUntil = Date.now() + 10000; // Jarvis is not running: try again in 10 s, not every second
      return;
    }
    if (answer.status === 401 && attempt === 0) continue; // new pairing: read pairing.json again
    if (!answer.ok) pausedUntil = Date.now() + 5000;
    return;
  }
}

// «I am installed»: Jarvis shows that the extension works (install guide, settings).
function hello() {
  send("hello", { version: chrome.runtime.getManifest().version, browser: navigator.userAgent.includes("Edg/") ? "edge" : "chrome" });
}
chrome.runtime.onInstalled.addListener(hello);
chrome.runtime.onStartup.addListener(hello);

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

// Playlists without a file extension are recognised by their content type, which is sent to Jarvis.
chrome.webRequest.onHeadersReceived.addListener((details) => {
  const type = (details.responseHeaders || []).find((h) => h.name.toLowerCase() === "content-type");
  if (type && MEDIA_TYPES.test(type.value || "")) remember(details, type.value);
}, { urls: ["<all_urls>"] }, ["responseHeaders"]);

// A closed tab or a new page: the old media list goes, and Jarvis stops preparing that film.
chrome.tabs.onRemoved.addListener((tabId) => {
  update(tabId, () => null);
  send("state", { event: "closed", tab: tabId });
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url) {
    update(tabId, () => null);
    send("state", { event: "closed", tab: tabId });
  }
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message || message.type !== "jarvis-video" || !sender.tab) return;
  const key = "media:" + sender.tab.id;
  chrome.storage.session.get(key).then((stored) => {
    const all = stored[key] || [];
    // Only what the player's own frame loaded (an ad iframe has its own frame id).
    const own = all.filter((item) => item.frame === sender.frameId);
    return send("state", {
      tab: sender.tab.id,
      frame: sender.frameId,
      page: message.page || "",
      time: message.time,
      paused: message.paused,
      stalled: message.stalled,
      ended: message.ended,
      rate: message.rate,
      duration: message.duration,
      src: message.src || "",
      media: (own.length ? own : all).map((item) => ({ url: item.url, type: item.type })),
    });
  }).catch(() => {});
});

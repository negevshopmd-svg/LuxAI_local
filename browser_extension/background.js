// Jarvis film captions - background (service worker).
// Remembers which media files each tab requested (HLS playlists, mp4/webm) and forwards the
// player's position from content.js to Jarvis on this computer (127.0.0.1 only).
const JARVIS = "http://127.0.0.1:47321/v1/";
const MEDIA_PATH = /\.(m3u8|mp4|webm|m4v|mov|mkv)$/i;
const MEDIA_TYPES = /mpegurl|video\/(mp4|webm|x-matroska|quicktime)/i;
const KEEP = 20;

function send(path, body) {
  return fetch(JARVIS + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => { /* Jarvis is not running: nothing to do */ });
}

// «I am installed»: Jarvis shows that the extension works (install guide, settings).
function hello() {
  send("hello", { version: chrome.runtime.getManifest().version, browser: navigator.userAgent.includes("Edg/") ? "edge" : "chrome" });
}
chrome.runtime.onInstalled.addListener(hello);
chrome.runtime.onStartup.addListener(hello);

async function remember(tabId, url) {
  if (tabId < 0 || !/^https?:/i.test(url)) return;
  const key = "media:" + tabId;
  const stored = (await chrome.storage.session.get(key))[key] || [];
  const list = [url].concat(stored.filter((item) => item !== url)).slice(0, KEEP);
  await chrome.storage.session.set({ [key]: list });
}

chrome.webRequest.onBeforeRequest.addListener((details) => {
  try {
    if (MEDIA_PATH.test(new URL(details.url).pathname)) remember(details.tabId, details.url);
  } catch (e) { /* not a URL */ }
}, { urls: ["<all_urls>"] });

// Playlists without a file extension are recognised by their content type.
chrome.webRequest.onHeadersReceived.addListener((details) => {
  const type = (details.responseHeaders || []).find((h) => h.name.toLowerCase() === "content-type");
  if (type && MEDIA_TYPES.test(type.value || "")) remember(details.tabId, details.url);
}, { urls: ["<all_urls>"] }, ["responseHeaders"]);

chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove("media:" + tabId));

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message || message.type !== "jarvis-video" || !sender.tab) return;
  const key = "media:" + sender.tab.id;
  chrome.storage.session.get(key).then((stored) => send("state", {
    tab: sender.tab.id,
    page: message.page || "",
    time: message.time,
    paused: message.paused,
    rate: message.rate,
    duration: message.duration,
    src: message.src || "",
    media: stored[key] || [],
  }));
});

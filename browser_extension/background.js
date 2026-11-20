// Jarvis film captions - background (service worker).
// Remembers which media files each tab requested (HLS playlists, mp4/webm) and forwards the
// player's position from content.js to Jarvis on this computer (127.0.0.1 only).
const JARVIS = "http://127.0.0.1:47321/v1/state";
const MEDIA_PATH = /\.(m3u8|mp4|webm|m4v|mov|mkv)$/i;
const MEDIA_TYPES = /mpegurl|video\/(mp4|webm|x-matroska|quicktime)/i;
const KEEP = 20;

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
  chrome.storage.session.get(key).then((stored) => {
    const report = {
      tab: sender.tab.id,
      page: message.page || "",
      time: message.time,
      paused: message.paused,
      rate: message.rate,
      duration: message.duration,
      src: message.src || "",
      media: stored[key] || [],
    };
    return fetch(JARVIS, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    });
  }).catch(() => { /* Jarvis is not running: nothing to do */ });
});

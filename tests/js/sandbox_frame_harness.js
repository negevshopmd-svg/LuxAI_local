// Runs browser_extension/content.js in a simulated SANDBOXED frame: its address is
// https://cdn.platform.openai.com but its real origin is "null" (as the iframe chatgpt.com embeds). Like Chrome,
// window.postMessage throws when the target origin does not match the window's real origin.
// Prints {"errors": [...], "posted": n} after the page hides (pagehide), which made the extension post a reset.
// Used by tests/test_sandbox_frame_043q.py.
const fs = require("fs");
const path = require("path");

const errors = [];
const windowListeners = {};
const documentListeners = {};
let posted = 0;
global.self = { origin: "null" };
global.location = { origin: "https://cdn.platform.openai.com", href: "https://cdn.platform.openai.com/frame",
                    hostname: "cdn.platform.openai.com", protocol: "https:" };
global.window = {
  addEventListener: (type, fn) => { (windowListeners[type] = windowListeners[type] || []).push(fn); },
  postMessage: (message, target) => {
    if (target !== "*" && target !== self.origin) {
      throw new Error(`Failed to execute 'postMessage' on 'DOMWindow': The target origin provided ('${target}') `
                      + `does not match the recipient window's origin ('${self.origin}').`);
    }
    posted += 1;
  },
};
global.document = {
  hidden: false, visibilityState: "visible",
  addEventListener: (type, fn) => { (documentListeners[type] = documentListeners[type] || []).push(fn); },
  hasFocus: () => true, querySelector: () => null,
};
global.HTMLVideoElement = class {};
global.HTMLAudioElement = class {};
global.PerformanceObserver = class { observe() {} disconnect() {} };
global.performance = { now: () => Date.now(), getEntriesByType: () => [] };
global.crypto = { randomUUID: () => "doc-1" };
global.chrome = { runtime: { sendMessage: (_message, callback) => callback && callback({ want: true }), lastError: null } };
global.setInterval = () => 0;

try {
  eval(fs.readFileSync(path.join(__dirname, "..", "..", "browser_extension", "content.js"), "utf8"));
  for (const fn of windowListeners.pagehide || []) fn({});
  document.hidden = true;
  for (const fn of documentListeners.visibilitychange || []) fn({});
} catch (error) {
  errors.push(String(error && error.message || error));
}
process.stdout.write(JSON.stringify({ errors, posted }));

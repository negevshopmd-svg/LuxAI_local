// Runs browser_extension/youtube_audio.js in Node with MediaSource stubs that keep a real sourceBuffers list.
// Scenario (argv[2]):
//   late    — the player appends WebM audio BEFORE captions are turned on, then captions are turned on
//   removed — captions on, audio appended, the player removes that SourceBuffer, Jarvis asks for a resync
// Prints the published packets as JSON. Used by tests/test_audit7_fixes_043r.py (audit 7 #31, #32).
const fs = require("fs");
const path = require("path");

const posted = [];
const listeners = [];
class SourceBuffer { appendBuffer() {} }
class MediaSource {
  constructor() { this.sourceBuffers = []; this.readyState = "open"; }
  addSourceBuffer() { const buffer = new SourceBuffer(); this.sourceBuffers.push(buffer); return buffer; }
  removeSourceBuffer(buffer) { this.sourceBuffers = this.sourceBuffers.filter((item) => item !== buffer); }
}
global.window = {
  MediaSource, SourceBuffer,
  addEventListener: (type, fn) => listeners.push(fn),
  postMessage: (message) => posted.push(message),
};
global.MediaSource = MediaSource;
global.SourceBuffer = SourceBuffer;
global.self = { origin: "https://www.youtube.com" };
global.performance = { now: () => Date.now() };
const timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.clearTimeout = () => {};
const SRC = "blob:https://www.youtube.com/abc";
global.URL = { createObjectURL: () => SRC };

eval(fs.readFileSync(path.join(__dirname, "..", "..", "browser_extension", "youtube_audio.js"), "utf8"));

const EBML = [26, 69, 223, 163];
const CLUSTER = [31, 67, 182, 117];
const init = new Uint8Array([...EBML, 1, 2, 3, 4, 5, 6, ...CLUSTER, 9, 9, 9, 9]);
const cluster = (n) => new Uint8Array([...CLUSTER, n, n, n, n, n, n]);

function control(active) {
  for (const fn of listeners) {
    fn({ source: window, origin: self.origin, data: { type: "jarvis-buffer-control", active, src: SRC } });
  }
}
function resync() {
  for (const fn of listeners) fn({ source: window, origin: self.origin, data: { type: "jarvis-buffer-resync" } });
}
function flush() { while (timers.length) timers.shift()(); }

const source = new MediaSource();
URL.createObjectURL(source);
const buffer = source.addSourceBuffer("audio/webm; codecs=opus");
buffer.timestampOffset = 0;
const scenario = process.argv[2];
if (scenario === "late") {
  buffer.appendBuffer(init);
  buffer.appendBuffer(cluster(1));
  flush();
  const before = posted.length;
  control(true);
  flush();
  process.stdout.write(JSON.stringify({ before, after: posted.length,
                                        full: posted.map((message) => message.full),
                                        pieces: posted.map((message) => message.pieces.length) }));
} else if (scenario === "removed") {
  control(true);
  buffer.appendBuffer(init);
  buffer.appendBuffer(cluster(1));
  flush();
  const before = posted.length;
  source.removeSourceBuffer(buffer);
  resync();
  flush();
  process.stdout.write(JSON.stringify({ before, after: posted.length }));
}

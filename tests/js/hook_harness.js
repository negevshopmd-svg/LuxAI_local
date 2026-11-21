// Runs browser_extension/youtube_audio.js in Node with tiny MediaSource stubs: appends the files given on the
// command line (init segment first) and prints every packet the hook publishes as JSON (bytes as base64).
// Used by tests/test_audit6_fixes_043p.py.
const fs = require("fs");
const path = require("path");

const posted = [];
const listeners = [];
class MediaSource {}
class SourceBuffer { appendBuffer() {} }
MediaSource.prototype.addSourceBuffer = function () { return new SourceBuffer(); };
global.window = {
  MediaSource, SourceBuffer,
  addEventListener: (type, fn) => listeners.push(fn),
  postMessage: (message) => posted.push(message),
};
global.MediaSource = MediaSource;
global.SourceBuffer = SourceBuffer;
global.location = { origin: "https://www.youtube.com" };
global.self = { origin: "https://www.youtube.com" };
global.performance = { now: () => Date.now() };
const timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.clearTimeout = () => {};
global.URL = { createObjectURL: () => "blob:https://www.youtube.com/abc" };

eval(fs.readFileSync(path.join(__dirname, "..", "..", "browser_extension", "youtube_audio.js"), "utf8"));

const source = new MediaSource();
URL.createObjectURL(source);
const buffer = source.addSourceBuffer(process.argv[2]);
for (const fn of listeners) {
  fn({ source: window, origin: self.origin,
       data: { type: "jarvis-buffer-control", active: true, src: "blob:https://www.youtube.com/abc" } });
}
for (const file of process.argv.slice(3)) {
  buffer.timestampOffset = 0;
  buffer.appendBuffer(new Uint8Array(fs.readFileSync(file)));
  while (timers.length) timers.shift()();
}
const out = posted.map((message) => ({
  kind: message.kind, track: message.track, offset: message.offset, epoch: message.epoch, full: message.full,
  header: Buffer.from(message.header).toString("base64"),
  pieces: message.pieces.map((piece) => [piece.n, piece.from, Buffer.from(piece.bytes).toString("base64")]),
}));
process.stdout.write(JSON.stringify(out));

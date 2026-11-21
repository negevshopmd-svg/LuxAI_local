// Runs in the media page so we can read unencrypted audio chunks already appended by its player.
// Nothing is copied from the audio track until the extension confirms that Jarvis wants captions.
// Only NEW audio is sent (numbered pieces); Jarvis rebuilds the window and asks for the whole window again
// only when a piece is missing. Before, the whole window (up to 2 MB) was resent every time: a real YouTube
// test moved 34 MB to Jarvis in two minutes for about 2.4 MB of audio.
(() => {
  if (!window.MediaSource || !window.SourceBuffer) return;
  const add = MediaSource.prototype.addSourceBuffer;
  const append = SourceBuffer.prototype.appendBuffer;
  const createURL = URL.createObjectURL;
  const sources = new WeakMap();
  const buffers = new WeakMap();
  const captured = new Set();
  // Room for a minute of ordinary WebM/MP4 audio, including tracks above 192 kbps.
  const limit = 2 * 1024 * 1024;
  const minimumInterval = 1000;
  let active = false;
  let selected = "";
  let timer = null;
  let pending = null;
  let serial = 0;
  let generation = 0;
  let lastPublished = -Infinity;

  URL.createObjectURL = function (object) {
    const url = createURL.call(this, object);
    if (object instanceof MediaSource) sources.set(object, url);
    return url;
  };

  function reset(state) {
    state.chunks = [];
    state.size = 0;
    state.epoch = (state.epoch || 0) + 1; // Jarvis drops what it had for this track
    state.full = true;
    captured.delete(state);
  }

  MediaSource.prototype.addSourceBuffer = function (type) {
    const buffer = add.call(this, type);
    const kind = /^audio\/(webm|mp4)(?:;|$)/i.exec(type)?.[1].toLowerCase();
    if (kind) buffers.set(buffer, { source: this, kind, id: ++serial, header: null, chunks: [], size: 0,
                                    counter: 0, epoch: 0, full: true });
    return buffer;
  };

  function join(parts, size) {
    const result = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) {
      result.set(part, offset);
      offset += part.length;
    }
    return result;
  }

  function publish() {
    timer = null;
    const item = pending;
    pending = null;
    if (!active || !item || !item.state.header || item.state.size === 0) return;
    const { state, offset } = item;
    const src = sources.get(state.source);
    if (!src || (selected && src !== selected)) return;
    const full = state.full;
    const pieces = [];
    for (const chunk of state.chunks) {
      const from = full ? 0 : chunk.sent;
      if (chunk.size <= from) continue;
      const whole = join(chunk.parts, chunk.size);
      const bytes = from ? whole.slice(from) : whole;
      pieces.push({ n: chunk.n, from, bytes: bytes.buffer });
      chunk.sent = chunk.size;
    }
    if (!pieces.length) return;
    state.full = false;
    const header = state.header.slice();
    lastPublished = performance.now();
    window.postMessage({ type: "jarvis-buffer-audio", src, kind: state.kind, track: state.id, offset,
                         epoch: state.epoch, full, header: header.buffer, pieces },
                       location.origin, [header.buffer, ...pieces.map((piece) => piece.bytes)]);
  }

  function collect(state, bytes, offset) {
    const webm = state.kind === "webm";
    const element = webm ? [31, 67, 182, 117] : [109, 111, 111, 102]; // Cluster / moof
    const initial = webm ? [26, 69, 223, 163] : [102, 116, 121, 112]; // EBML / ftyp
    const typeAt = webm ? 0 : 4;
    const matches = (at, signature) => signature.every((byte, i) => bytes[at + i] === byte);
    let begins = matches(typeAt, element);
    if (matches(typeAt, initial)) {
      let boundary = typeAt + 4;
      while (boundary < bytes.length && !matches(boundary, element)) boundary += 1;
      const end = Math.min(bytes.length, boundary - typeAt);
      state.header = end && end <= 32 * 1024 ? bytes.slice(0, end) : null;
      reset(state);
      if (boundary === bytes.length) return;
      bytes = bytes.subarray(end);
      begins = true;
    }
    if (!active || !state.header || bytes.length > limit) return;
    const src = sources.get(state.source);
    if (!src || (selected && src !== selected)) return;
    if (state.offset !== offset || state.generation !== generation) reset(state);
    state.offset = offset;
    state.generation = generation;
    if (begins) state.chunks.push({ parts: [], size: 0, sent: 0, n: ++state.counter });
    const chunk = state.chunks.at(-1);
    if (!chunk) return;
    chunk.parts.push(bytes.slice());
    captured.add(state);
    chunk.size += bytes.length;
    state.size += bytes.length;
    while (state.size > limit && state.chunks.length) state.size -= state.chunks.shift().size;
    pending = { state, offset };
    if (timer === null) {
      const delay = Math.max(240, minimumInterval - (performance.now() - lastPublished));
      timer = setTimeout(publish, delay);
    }
  }

  SourceBuffer.prototype.appendBuffer = function (data) {
    const result = append.call(this, data);
    const state = buffers.get(this);
    if (state) {
      try {
        const bytes = ArrayBuffer.isView(data)
          ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : new Uint8Array(data);
        collect(state, bytes, this.timestampOffset);
      } catch (error) { /* a failed observation cannot break the player */ }
    }
    return result;
  };

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (event.source !== window || event.origin !== location.origin) return;
    if (message?.type === "jarvis-buffer-resync") {
      // Jarvis missed a piece: the next packet carries the whole window again.
      for (const state of captured) {
        state.full = true;
        pending = pending || { state, offset: state.offset };
      }
      if (pending && timer === null) timer = setTimeout(publish, 240);
      return;
    }
    if (message?.type !== "jarvis-buffer-control") return;
    const next = message.active === true;
    const src = typeof message.src === "string" ? message.src : "";
    if ((!next && active) || message.reset || (selected && src && selected !== src)) {
      generation += 1;
      for (const state of captured) reset(state);
      pending = null;
      clearTimeout(timer);
      timer = null;
      lastPublished = -Infinity;
    }
    active = next;
    selected = src;
  });
})();

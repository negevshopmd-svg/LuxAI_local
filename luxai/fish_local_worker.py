"""Isolated persistent Fish S2 CPU process. Never connects to the Internet.

Only JSON protocol replies are written to stdout with a fixed prefix. Load the
GGUF model once, reuse the pipeline and voice prompt across speech requests.
A parent cancellation terminates this process instead of interrupting native
C++ code on an unsafe foreign thread.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
from pathlib import Path
import struct
import sys
import wave

PREFIX = "FISH_LOCAL_JSON:"


def emit(**fields):
    sys.stdout.write(PREFIX + json.dumps(fields, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def bind(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


class Engine:
    def __init__(self, dll_path: str, model: str, tokenizer: str, reference: str,
                 transcript: str, threads: int):
        self.dll = ctypes.CDLL(dll_path)
        ptr, integer = ctypes.c_void_p, ctypes.c_int32
        self.free_pipeline = bind(self.dll, "ReleaseS2Pipeline", [ptr], None)
        self.free_params = bind(self.dll, "ReleaseS2GenerateParams", [ptr], None)
        self.free_audio = bind(self.dll, "ReleaseS2AudioBuffer", [ptr], None)
        self.free_codes = bind(self.dll, "ReleaseS2AudioPromptCodes", [ptr], None)
        self.pipeline = self.params = self.audio = self.codes = None
        self.transcript = transcript.strip()
        self.threads = threads
        try:
            bind(self.dll, "SetS2LogLevel", [integer], None)(0)
            self.pipeline = bind(self.dll, "AllocS2Pipeline", [], ptr)()
            self.params = bind(self.dll, "AllocS2GenerateParams", [], ptr)()
            self.audio = bind(self.dll, "AllocS2AudioBuffer", [integer], ptr)(0)
            if not all((self.pipeline, self.params, self.audio)):
                raise RuntimeError("native_allocation_failed")
            init = bind(self.dll, "InitializeS2PipelineFromFiles",
                        [ptr, ctypes.c_char_p, ctypes.c_char_p, integer, integer,
                         integer, ctypes.c_int], ctypes.c_int)
            # -1 selects upstream default CPU backend. Offloading is disabled
            # for the CPU-only DLL, so no GPU-specific dependency is required.
            if init(self.pipeline, model.encode("utf-8"), tokenizer.encode("utf-8"),
                    -1, -1, 0, 0) != 1:
                raise RuntimeError("model_load_failed")
            config = bind(self.dll, "InitializeS2GenerateParams",
                          [ptr, integer, ctypes.c_float, ctypes.c_float, integer,
                           integer, integer, ctypes.c_int], ctypes.c_int)
            if config(self.params, 512, 0.65, 0.9, 40, 0, threads, 0) != 1:
                raise RuntimeError("generation_config_failed")
            self.codes = bind(self.dll, "AllocS2AudioPromptCodes", [], ptr)()
            self.prompt_time = integer(0)
            if not self.codes:
                raise RuntimeError("prompt_allocation_failed")
            if reference:
                if not self.transcript:
                    raise RuntimeError("reference_transcript_required")
                prompt = bind(self.dll, "InitializeAudioPromptCodes",
                              [ptr, integer, ctypes.c_char_p, ptr,
                               ctypes.POINTER(integer)], ctypes.c_int)
                if prompt(self.pipeline, threads, reference.encode("utf-8"),
                          self.codes, ctypes.byref(self.prompt_time)) != 1:
                    raise RuntimeError("invalid_reference_audio")
            self.synthesize = bind(
                self.dll, "S2Synthesize",
                [ptr, ptr, ptr, ptr, ctypes.POINTER(integer), ctypes.c_char_p,
                 ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                 ctypes.POINTER(integer)], ctypes.c_int)
            self.audio_data = bind(self.dll, "GetS2AudioBufferDataPointer",
                                   [ptr], ctypes.POINTER(ctypes.c_float))
        except BaseException:
            self.close()
            raise

    def generate(self, text: str, destination: Path):
        if not text.strip() or len(text) > 350 or len(text.encode("utf-8")) > 1500:
            raise ValueError("text_length")
        length = ctypes.c_int32(0)
        status = self.synthesize(
            self.pipeline, self.params, self.audio, self.codes,
            ctypes.byref(self.prompt_time), None,
            self.transcript.encode("utf-8") if self.transcript else None,
            text.encode("utf-8"), None, ctypes.byref(length))
        if status != 1:
            raise RuntimeError("generation_failed_" + str(status))
        samples = int(length.value)
        if not 1 <= samples <= 24000 * 120:
            raise RuntimeError("invalid_audio_size")
        pointer = self.audio_data(self.audio)
        if not pointer:
            raise RuntimeError("empty_audio")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".working")
        try:
            with wave.open(str(temporary), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(24000)
                # Do not allocate unbounded arrays or expose raw voice data to logs.
                for start in range(0, samples, 4096):
                    values = []
                    for i in range(start, min(samples, start + 4096)):
                        v = float(pointer[i])
                        values.append(max(-32768, min(32767, round(v * 32767)))
                                      if math.isfinite(v) else 0)
                    out.writeframesraw(struct.pack("<" + "h" * len(values), *values))
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        for name, destructor in (("codes", "free_codes"), ("audio", "free_audio"),
                                  ("params", "free_params"), ("pipeline", "free_pipeline")):
            handle = getattr(self, name, None)
            if handle:
                getattr(self, destructor)(handle)
                setattr(self, name, None)


def main():
    parser = argparse.ArgumentParser()
    for name in ("dll", "model", "tokenizer"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--reference", default="")
    parser.add_argument("--transcript", default="")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    engine = None
    try:
        engine = Engine(args.dll, args.model, args.tokenizer,
                        args.reference, args.transcript,
                        max(1, min(16, args.threads)))
        emit(event="ready")
        for line in sys.stdin:
            request = None
            try:
                request = json.loads(line)
                if request.get("op") == "quit":
                    break
                if request.get("op") != "speak" or not isinstance(request.get("text"), str):
                    raise ValueError("request_invalid")
                dest = Path(request["output"])
                engine.generate(request["text"], dest)
                emit(event="done", id=request.get("id"))
            except Exception as exc:
                emit(event="error", id=request.get("id") if isinstance(request, dict) else None,
                     code=str(exc)[:80] if isinstance(exc, (ValueError, RuntimeError))
                     else type(exc).__name__)
    except Exception as exc:
        emit(event="error", code=str(exc)[:80] if isinstance(exc, RuntimeError)
             else type(exc).__name__)
        return 1
    finally:
        if engine is not None:
            engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

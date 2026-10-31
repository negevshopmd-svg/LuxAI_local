"""Build and verify the pinned, CPU-only Windows Fish S2 runtime.

This is a maintainer/CI tool. It never downloads model weights or publishes a
release. Both CPU variants are built from the same pinned source, smoke-tested
in isolated processes, and placed in a ZIP with fixed entry metadata. Identical
input files produce identical ZIP bytes; the manifest records the actual MSVC
toolchain because different toolchain versions can change native code.
"""
from __future__ import annotations

import argparse
import ctypes
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
import zipfile


SOURCE_REPOSITORY = "https://github.com/rodrigomatta/s2.cpp.git"
SOURCE_COMMIT = "2c33261938da1a41d713768b1b391b4d368d7d2c"
GGML_COMMIT = "57ea0bc119d722d74594196cc5b494a34dd87be4"
PACKAGE_NAME = "fish-s2-cpu-win-x64-2c332619-v1.zip"
VARIANTS = ("cpu-baseline", "cpu-avx2")
REQUIRED_EXPORTS = (
    "GetFishCpuFeatureBits",
    "AllocS2Pipeline", "ReleaseS2Pipeline", "SetS2LogLevel", "GetS2LogLevel",
    "InitializeS2PipelineFromFiles", "AllocS2GenerateParams",
    "ReleaseS2GenerateParams", "InitializeS2GenerateParams",
    "AllocS2AudioBuffer", "ReleaseS2AudioBuffer",
    "GetS2AudioBufferDataPointer", "S2Synthesize",
    "AllocS2AudioPromptCodes", "ReleaseS2AudioPromptCodes",
    "InitializeAudioPromptCodes", "S2SynthesizeStreaming",
    "S2SynthesizeStreamingEx", "AllocS2Tokenizer", "InitializeS2Tokenizer",
    "ReleaseS2Tokenizer", "ValidateFishAudioReferenceFile",
    "ValidateFishModelFileOpen",
)
OS_DLLS = frozenset({
    "kernel32.dll", "kernelbase.dll", "ntdll.dll", "advapi32.dll",
    "ws2_32.dll", "mswsock.dll", "shell32.dll", "shlwapi.dll", "user32.dll",
    "ole32.dll", "oleaut32.dll", "bcrypt.dll", "crypt32.dll", "secur32.dll",
    "iphlpapi.dll", "normaliz.dll", "version.dll", "winmm.dll", "rpcrt4.dll",
    "msvcrt.dll", "ucrtbase.dll",
})
_CMAKE_SHARED_TARGET = "    add_library(s2_shared SHARED ${S2_LIBRARY_SOURCES})\n"
CPU_FEATURE_SOURCE = r'''// LuxAI Local compatibility probe; no model or inference changes.
// The host must load the SSE2 baseline DLL before asking whether AVX2 is safe.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <intrin.h>
#include "ggml.h"
#include "s2_audio.h"

extern "C" __declspec(dllexport) std::uint32_t GetFishCpuFeatureBits() {
    int registers[4] = {};
    __cpuid(registers, 0);
    if (registers[0] < 7) return 0;
    __cpuidex(registers, 1, 0);
    const auto ecx = static_cast<std::uint32_t>(registers[2]);
    constexpr std::uint32_t osxsave = 1u << 27;
    constexpr std::uint32_t avx = 1u << 28;
    if ((ecx & (osxsave | avx)) != (osxsave | avx)) return 0;
    if ((_xgetbv(0) & 0x6u) != 0x6u) return 0;
    const bool fma = (ecx & (1u << 12)) != 0;
    const bool f16c = (ecx & (1u << 29)) != 0;
    __cpuidex(registers, 7, 0);
    const bool avx2 = (static_cast<std::uint32_t>(registers[1]) & (1u << 5)) != 0;
    return (avx2 ? 1u : 0u) | (fma ? 2u : 0u) | (f16c ? 4u : 0u);
}

// File-system smoke helpers use the same upstream readers as the pipeline.
// They need no model weights and are not called by normal speech synthesis.
extern "C" __declspec(dllexport) int ValidateFishAudioReferenceFile(const char* path) {
    if (!path) return 0;
    try {
        s2::AudioData audio;
        return s2::audio_read(path, audio) && !audio.samples.empty() && audio.sample_rate > 0 ? 1 : 0;
    } catch (...) {
        return 0;
    }
}

extern "C" __declspec(dllexport) int ValidateFishModelFileOpen(const char* path) {
    if (!path) return 0;
    std::FILE* file = ggml_fopen(path, "rb");
    if (!file) return 0;
    char magic[4] = {};
    const auto count = std::fread(magic, 1, sizeof(magic), file);
    std::fclose(file);
    return count == sizeof(magic) && std::memcmp(magic, "GGUF", 4) == 0 ? 1 : 0;
}
'''


def run(arguments: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(arguments, cwd=cwd, check=False, text=True,
                               encoding="utf-8", errors="replace",
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    completed.check_returncode()
    return completed.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def checkout_source(directory: Path) -> None:
    """Use an empty, task-owned checkout; never reset another checkout."""
    if directory.exists():
        raise ValueError("The source directory must not already exist")
    run(["git", "init", str(directory)])
    run(["git", "remote", "add", "origin", SOURCE_REPOSITORY], cwd=directory)
    run(["git", "fetch", "--depth", "1", "origin", SOURCE_COMMIT], cwd=directory)
    run(["git", "checkout", "--detach", SOURCE_COMMIT], cwd=directory)
    run(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"], cwd=directory)
    actual = run(["git", "rev-parse", "HEAD"], cwd=directory).strip()
    ggml = run(["git", "rev-parse", "HEAD"], cwd=directory / "ggml").strip()
    if actual != SOURCE_COMMIT or ggml != GGML_COMMIT:
        raise ValueError("Fish runtime source/submodule pin mismatch")


def add_cpu_probe_export(source: Path) -> str:
    """Add a baseline CPUID probe without changing upstream arithmetic code."""
    path = source / "CMakeLists.txt"
    original = path.read_text(encoding="utf-8")
    helper = source / "luxai_cpu_features.cpp"
    if original.count(_CMAKE_SHARED_TARGET) != 1 or helper.exists():
        raise ValueError("Pinned S2 shared target no longer matches")
    addition = (
        _CMAKE_SHARED_TARGET + "    if(WIN32)\n"
        "        target_sources(s2_shared PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/luxai_cpu_features.cpp)\n"
        "    endif()\n"
    )
    modified = original.replace(_CMAKE_SHARED_TARGET, addition)
    path.write_text(modified, encoding="utf-8", newline="\n")
    helper.write_text(CPU_FEATURE_SOURCE, encoding="utf-8", newline="\n")
    cmake_diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), modified.splitlines(keepends=True),
        fromfile="a/CMakeLists.txt", tofile="b/CMakeLists.txt",
    ))
    source_diff = "".join(difflib.unified_diff(
        [], CPU_FEATURE_SOURCE.splitlines(keepends=True),
        fromfile="/dev/null", tofile="b/luxai_cpu_features.cpp",
    ))
    return cmake_diff + source_diff


def apply_unicode_tokenizer_patch(source: Path) -> str:
    """Open UTF-8 tokenizer paths through upstream's existing wide-path wrapper."""
    path = source / "src/s2_tokenizer.cpp"
    original = path.read_text(encoding="utf-8")
    include = '#include "../include/s2_tokenizer.h"\n'
    open_file = "    std::ifstream f(path);"
    if original.count(include) != 1 or original.count(open_file) != 1:
        raise ValueError("Pinned S2 tokenizer file opener no longer matches")
    modified = original.replace(
        include, include + '#ifdef _WIN32\n#ifndef NOMINMAX\n#define NOMINMAX\n#endif\n#endif\n'
        '#include "../third_party/filesystem.hpp"\n',
    ).replace(open_file, "    ghc::filesystem::ifstream f{ghc::filesystem::u8path(path)};")
    path.write_text(modified, encoding="utf-8", newline="\n")
    return "".join(difflib.unified_diff(
        original.splitlines(keepends=True), modified.splitlines(keepends=True),
        fromfile="a/src/s2_tokenizer.cpp", tofile="b/src/s2_tokenizer.cpp",
    ))


def apply_unicode_audio_model_patches(source: Path) -> str:
    """Use wide-path readers for reference audio and GGUF tensor reopens."""
    path = source / "src/s2_audio.cpp"
    original = path.read_text(encoding="utf-8")
    include = '#include "../include/s2_audio.h"\n'
    wav_reader = (
        "        float * data = drwav_open_file_and_read_pcm_frames_f32(\n"
        "            path.c_str(), &channels, &sample_rate, &total_frames, nullptr);"
    )
    wav_wide = (
        "#ifdef _WIN32\n"
        "        const auto wide_path = ghc::filesystem::u8path(path).wstring();\n"
        "        float * data = drwav_open_file_and_read_pcm_frames_f32_w(\n"
        "            wide_path.c_str(), &channels, &sample_rate, &total_frames, nullptr);\n"
        "#else\n" + wav_reader + "\n#endif"
    )
    mp3_reader = (
        "        float * data = drmp3_open_file_and_read_pcm_frames_f32(\n"
        "            path.c_str(), &config, &total_frames, nullptr);"
    )
    mp3_wide = (
        "#ifdef _WIN32\n"
        "        const auto wide_path = ghc::filesystem::u8path(path).wstring();\n"
        "        drmp3 reader;\n"
        "        float * data = nullptr;\n"
        "        if (drmp3_init_file_w(&reader, wide_path.c_str(), nullptr)) {\n"
        "            data = drmp3__full_read_and_close_f32(&reader, &config, &total_frames);\n"
        "        }\n"
        "#else\n" + mp3_reader + "\n#endif"
    )
    if any(original.count(expected) != 1 for expected in (include, wav_reader, mp3_reader)):
        raise ValueError("Pinned S2 audio file openers no longer match")
    modified = original.replace(
        include, include + '#ifdef _WIN32\n#ifndef NOMINMAX\n#define NOMINMAX\n#endif\n#endif\n'
        '#include "../third_party/filesystem.hpp"\n',
    ).replace(wav_reader, wav_wide).replace(mp3_reader, mp3_wide)
    changes = [(path, original, modified)]
    narrow = 'std::fopen(gguf_path.c_str(), "rb")'
    for name in ("s2_model.cpp", "s2_codec.cpp"):
        model_path = source / "src" / name
        before = model_path.read_text(encoding="utf-8")
        if before.count(narrow) != 1:
            raise ValueError("Pinned S2 GGUF tensor file opener no longer matches")
        changes.append((model_path, before, before.replace(narrow, 'ggml_fopen(gguf_path.c_str(), "rb")')))
    patches = []
    for changed_path, before, after in changes:
        changed_path.write_text(after, encoding="utf-8", newline="\n")
        name = changed_path.relative_to(source).as_posix()
        patches.append("".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile="a/" + name, tofile="b/" + name,
        )))
    return "".join(patches)


def cmake_options(variant: str) -> list[str]:
    if variant not in VARIANTS:
        raise ValueError("Unknown CPU variant")
    avx2 = variant == "cpu-avx2"
    options = {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_POLICY_DEFAULT_CMP0091": "NEW",
        "CMAKE_MSVC_RUNTIME_LIBRARY": "MultiThreaded",
        "CMAKE_C_FLAGS_RELEASE": "/O2 /DNDEBUG",
        "CMAKE_CXX_FLAGS_RELEASE": "/O2 /DNDEBUG",
        "CMAKE_SHARED_LINKER_FLAGS": "/Brepro",
        "CMAKE_EXE_LINKER_FLAGS": "/Brepro",
        "S2_BUILD_SHARED_LIBRARIES": "ON",
        "S2_CUDA": "OFF", "S2_VULKAN": "OFF", "S2_METAL": "OFF",
        "BUILD_SHARED_LIBS": "OFF", "GGML_STATIC": "ON",
        "GGML_NATIVE": "OFF", "GGML_BACKEND_DL": "OFF",
        "GGML_OPENMP": "OFF", "GGML_BLAS": "OFF", "GGML_LLAMAFILE": "OFF",
        "GGML_CCACHE": "OFF", "GGML_CPU_ALL_VARIANTS": "OFF",
        "GGML_SSE42": "OFF", "GGML_AVX": "ON" if avx2 else "OFF",
        "GGML_AVX2": "ON" if avx2 else "OFF",
        "GGML_FMA": "ON" if avx2 else "OFF",
        "GGML_F16C": "ON" if avx2 else "OFF", "GGML_BMI2": "OFF",
        "GGML_AVX_VNNI": "OFF", "GGML_AVX512": "OFF",
        "GGML_AVX512_VBMI": "OFF", "GGML_AVX512_VNNI": "OFF",
        "GGML_AVX512_BF16": "OFF", "GGML_AMX_TILE": "OFF",
        "GGML_AMX_INT8": "OFF", "GGML_AMX_BF16": "OFF",
    }
    return [f"-D{name}={value}" for name, value in options.items()]


def visual_studio_generator() -> str:
    root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    vswhere = root / "Microsoft Visual Studio/Installer/vswhere.exe"
    data = json.loads(run([
        str(vswhere), "-latest", "-products", "*", "-requires",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-format", "json", "-utf8",
    ]).lstrip("\ufeff"))
    if not data:
        raise RuntimeError("MSVC x64 build tools were not found")
    major = int(data[0]["installationVersion"].split(".", 1)[0])
    generators = {16: "Visual Studio 16 2019", 17: "Visual Studio 17 2022",
                  18: "Visual Studio 18 2026"}
    if major not in generators:
        raise RuntimeError("Unsupported Visual Studio toolchain")
    return generators[major]


def pe_imports(path: Path) -> list[str]:
    """Read ordinary and delay-load imports without loading a native DLL."""
    data = path.read_bytes()
    if len(data) < 256 or data[:2] != b"MZ":
        raise ValueError("Runtime is not a PE binary")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Invalid PE header")
    machine, sections, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", data, pe + 4)
    opt = pe + 24
    if machine != 0x8664 or opt + opt_size > len(data):
        raise ValueError("The Fish runtime must target Windows x64")
    if struct.unpack_from("<H", data, opt)[0] != 0x20B or opt_size < 224:
        raise ValueError("The Fish runtime must be PE32+")
    section_table = opt + opt_size
    if section_table + sections * 40 > len(data):
        raise ValueError("Invalid PE section table")
    mapped = []
    for index in range(sections):
        entry = section_table + index * 40
        virtual_size, address, raw_size, offset = struct.unpack_from("<IIII", data, entry + 8)
        mapped.append((address, max(virtual_size, raw_size), raw_size, offset))

    def offset_for(rva: int, size: int = 1) -> int:
        for address, span, raw_size, offset in mapped:
            if address <= rva and rva - address + size <= span:
                relative = rva - address
                if relative + size > raw_size or offset + relative + size > len(data):
                    break
                return offset + relative
        raise ValueError("PE import points outside a file-backed section")

    def name_at(rva: int) -> str:
        offset = offset_for(rva)
        end = data.find(b"\0", offset, min(len(data), offset + 260))
        if end < 0:
            raise ValueError("Invalid PE import name")
        return data[offset:end].decode("ascii").lower()

    imports = set()
    for directory, entry_size, name_field in ((1, 20, 12), (13, 32, 4)):
        rva, length = struct.unpack_from("<II", data, opt + 112 + directory * 8)
        if not rva:
            continue
        if length < entry_size or length > 1024 * 1024:
            raise ValueError("Invalid PE import directory")
        for entry_rva in range(rva, rva + length, entry_size):
            offset = offset_for(entry_rva, entry_size)
            descriptor = data[offset:offset + entry_size]
            if not any(descriptor):
                break
            if directory == 13 and not struct.unpack_from("<I", descriptor)[0] & 1:
                raise ValueError("Non-RVA delay imports are not supported")
            imports.add(name_at(struct.unpack_from("<I", descriptor, name_field)[0]))
        else:
            raise ValueError("Unterminated PE import table")
    return sorted(imports)


def verify_cpu_imports(path: Path) -> list[str]:
    imports = pe_imports(path)
    unwanted = [name for name in imports if name not in OS_DLLS
                and not name.startswith(("api-ms-win-core-", "ext-ms-win-"))]
    if unwanted:
        raise ValueError("CPU runtime has external DLL dependencies: " + ", ".join(unwanted))
    return imports


def cpu_features(path: Path) -> int:
    """Call only the baseline DLL before loading an optimized variant."""
    dll = ctypes.CDLL(str(path.resolve()))
    dll.GetFishCpuFeatureBits.argtypes = []
    dll.GetFishCpuFeatureBits.restype = ctypes.c_uint32
    return int(dll.GetFishCpuFeatureBits())


def smoke_library(path: Path) -> None:
    """Exercise the actual ABI without model weights, including UTF-8 paths."""
    if sys.platform != "win32":
        raise RuntimeError("The Windows DLL smoke test requires Windows")
    dll = ctypes.CDLL(str(path.resolve()))
    for name in REQUIRED_EXPORTS:
        getattr(dll, name)
    pointer = ctypes.c_void_p
    integer = ctypes.c_int32
    dll.SetS2LogLevel.argtypes = [integer]
    dll.SetS2LogLevel.restype = None
    dll.GetS2LogLevel.argtypes = []
    dll.GetS2LogLevel.restype = integer
    dll.SetS2LogLevel(0)
    assert dll.GetS2LogLevel() == 0
    allocators = (("AllocS2Pipeline", "ReleaseS2Pipeline", []),
                  ("AllocS2GenerateParams", "ReleaseS2GenerateParams", []),
                  ("AllocS2AudioBuffer", "ReleaseS2AudioBuffer", [ctypes.c_int]),
                  ("AllocS2Tokenizer", "ReleaseS2Tokenizer", []))
    handles = []
    try:
        for alloc_name, free_name, arguments in allocators:
            alloc = getattr(dll, alloc_name)
            alloc.argtypes, alloc.restype = arguments, pointer
            release = getattr(dll, free_name)
            release.argtypes, release.restype = [pointer], None
            handle = alloc(0) if arguments else alloc()
            if not handle:
                raise RuntimeError("A native allocation failed")
            handles.append((handle, release))
        pipeline, params, buffer, tokenizer = (handle for handle, _ in handles)
        tokenizer_path = path.parent / "токенизатор-Știință.json"
        tokenizer_path.write_text(json.dumps({
            "model": {"vocab": {"a": 0, "Привет": 1}, "merges": []},
            "added_tokens": [],
        }, ensure_ascii=False), encoding="utf-8")
        dll.InitializeS2Tokenizer.argtypes = [pointer, ctypes.c_char_p]
        dll.InitializeS2Tokenizer.restype = ctypes.c_int
        assert dll.InitializeS2Tokenizer(tokenizer, str(tokenizer_path).encode("utf-8")) == 1, (
            "A valid UTF-8 tokenizer must load from a Unicode Windows path"
        )
        reference_path = path.parent / "эталон-Știință.wav"
        with wave.open(str(reference_path), "wb") as reference:
            reference.setnchannels(1)
            reference.setsampwidth(2)
            reference.setframerate(24000)
            reference.writeframes(b"\0\0" * 128)
        dll.ValidateFishAudioReferenceFile.argtypes = [ctypes.c_char_p]
        dll.ValidateFishAudioReferenceFile.restype = ctypes.c_int
        assert dll.ValidateFishAudioReferenceFile(str(reference_path).encode("utf-8")) == 1, (
            "A valid WAV reference must decode from a Unicode Windows path"
        )
        binary_path = path.parent / "байты-модели-Știință.bin"
        binary_path.write_bytes(b"GGUF")
        dll.ValidateFishModelFileOpen.argtypes = [ctypes.c_char_p]
        dll.ValidateFishModelFileOpen.restype = ctypes.c_int
        assert dll.ValidateFishModelFileOpen(str(binary_path).encode("utf-8")) == 1, (
            "The GGUF file opener must read bytes from a Unicode Windows path"
        )
        dll.InitializeS2GenerateParams.argtypes = [pointer, integer, ctypes.c_float,
            ctypes.c_float, integer, integer, integer, ctypes.c_int]
        dll.InitializeS2GenerateParams.restype = ctypes.c_int
        assert dll.InitializeS2GenerateParams(params, 64, 0.8, 0.8, 30, 0, 1, 0) == 1
        dll.InitializeS2PipelineFromFiles.argtypes = [pointer, ctypes.c_char_p,
            ctypes.c_char_p, integer, integer, integer, ctypes.c_int]
        dll.InitializeS2PipelineFromFiles.restype = ctypes.c_int
        missing = path.parent / "Не существует Știință" / "model.gguf"
        result = dll.InitializeS2PipelineFromFiles(
            pipeline, str(missing).encode("utf-8"),
            str(missing.with_name("tokenizer.json")).encode("utf-8"),
            -1, -1, 0, 0,
        )
        assert result != 1, "Missing weights must fail without a crash"
    finally:
        for handle, release in reversed(handles):
            release(handle)
    print("Native Fish S2 CPU ABI smoke passed.", flush=True)


def deterministic_zip(directory: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, strict_timestamps=True) as archive:
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            name = path.relative_to(directory).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 << 16)
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)


def package_runtime(stage: Path, output_dir: Path, manifest: dict) -> Path:
    """Package only fixed runtime files; hashes cover every file but the manifest."""
    required = {f"{variant}/s2.dll" for variant in VARIANTS}
    required.update({"LICENSE.txt", "GGML-LICENSE.txt", "NOTICE.txt", "BUILD-PATCHES.txt"})
    actual = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    if actual != required or any(p.is_symlink() for p in stage.rglob("*")):
        raise ValueError("Unexpected or missing runtime package files")
    result = dict(manifest)
    result["files"] = {name: {"sha256": sha256(stage / name),
                              "size": (stage / name).stat().st_size}
                       for name in sorted(required)}
    (stage / "manifest.json").write_text(
        json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    output = output_dir / PACKAGE_NAME
    deterministic_zip(stage, output)
    checksum = sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        checksum + "  " + output.name + "\n", encoding="ascii", newline="\n")
    print(json.dumps({"package": str(output), "sha256": checksum,
                      "size": output.stat().st_size}, sort_keys=True), flush=True)
    return output


def build_runtime(work_dir: Path, output_dir: Path, jobs: int) -> Path:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise RuntimeError("Build with 64-bit Python on Windows/MSVC")
    if work_dir.exists() and any(work_dir.iterdir()):
        raise ValueError("Choose an empty build work directory")
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "source"
    checkout_source(source)
    own_patch = (add_cpu_probe_export(source) + apply_unicode_tokenizer_patch(source)
                 + apply_unicode_audio_model_patches(source))
    generator = visual_studio_generator()
    stage = work_dir / "package"
    stage.mkdir()
    flags = {}
    dependencies = {}
    baseline_features = 0
    for variant in VARIANTS:
        if variant == "cpu-avx2" and baseline_features & 7 != 7:
            raise RuntimeError("The CI CPU lacks AVX2/FMA/F16C; the optimized DLL cannot be smoke-tested")
        build_dir = work_dir / variant
        flags[variant] = cmake_options(variant)
        run(["cmake", "-S", str(source), "-B", str(build_dir), "-G", generator,
             "-A", "x64", *flags[variant]])
        run(["cmake", "--build", str(build_dir), "--config", "Release",
             "--target", "s2_shared", "--parallel", str(jobs)])
        candidates = list(build_dir.rglob("s2.dll"))
        if len(candidates) != 1:
            raise RuntimeError("Expected one compiled s2.dll")
        dependencies[variant] = verify_cpu_imports(candidates[0])
        destination = stage / variant / "s2.dll"
        destination.parent.mkdir()
        shutil.copyfile(candidates[0], destination)
        if variant == "cpu-baseline":
            # Feature detection runs in a separate process, and is performed
            # only through the baseline DLL before optimized code can load.
            feature_output = run([sys.executable, str(Path(__file__).resolve()),
                                  "--probe-library", str(destination)])
            baseline_features = json.loads(feature_output)["cpu_features"]
        # Loading from a Unicode directory proves UTF-8 file handling at the
        # ABI boundary without loading weights or executing a synthesis.
        with tempfile.TemporaryDirectory(prefix="Проба Știință ", dir=work_dir) as folder:
            probe = Path(folder) / "s2.dll"
            shutil.copyfile(destination, probe)
            subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--smoke-library", str(probe)], check=True, timeout=60)
    shutil.copyfile(source / "LICENSE.md", stage / "LICENSE.txt")
    shutil.copyfile(source / "ggml/LICENSE", stage / "GGML-LICENSE.txt")
    patches = [own_patch]
    for patch in sorted((source / "patches").glob("*.patch")):
        patches.append("\n# Pinned upstream patch: " + patch.name + "\n")
        patches.append(patch.read_text(encoding="utf-8"))
    (stage / "BUILD-PATCHES.txt").write_text("".join(patches), encoding="utf-8", newline="\n")
    notice = (
        "Fish S2 local speech runtime, built for LuxAI Local.\n"
        f"Source: {SOURCE_REPOSITORY}\nCommit: {SOURCE_COMMIT}\n"
        f"ggml commit: {GGML_COMMIT}\n"
        "This model is licensed under the Fish Audio Research License, "
        "Copyright © 39 AI, INC. All Rights Reserved.\n"
        "See LICENSE.txt for permitted research/non-commercial use and terms.\n"
        "ggml attribution and license are retained in GGML-LICENSE.txt.\n"
        "CPU baseline: x64/SSE2, no GPU or vendor runtime dependency.\n"
        "CPU AVX2: AVX2, FMA and F16C required; BMI2 is disabled.\n"
        "Always query GetFishCpuFeatureBits in the baseline DLL before loading "
        "the optimized DLL. Bits: 1=AVX2, 2=FMA, 4=F16C; all require OSXSAVE "
        "and XGETBV-enabled SSE/YMM state. Missing probe or incomplete mask: use baseline.\n"
        "The build adds CPU/file-system verification exports to S2, opens UTF-8 "
        "tokenizer paths through upstream's existing wide-path filesystem wrapper, "
        "uses wide WAV/MP3 file readers on Windows, and reopens GGUF tensor data "
        "through ggml_fopen, "
        "and applies the pinned upstream patches. It does not modify inference arithmetic. "
        "Full added source and build changes: BUILD-PATCHES.txt.\n"
        "No model weights, tokenizer, user text, reference audio, keys or "
        "network services are included in this archive.\n"
    )
    (stage / "NOTICE.txt").write_text(notice, encoding="utf-8", newline="\n")
    manifest = {
        "format": 1, "engine": "s2.cpp", "target": "windows-x64",
        "source_repository": SOURCE_REPOSITORY, "source_commit": SOURCE_COMMIT,
        "ggml_commit": GGML_COMMIT, "generator": generator,
        "cmake_version": run(["cmake", "--version"]).splitlines()[0],
        "variants": {variant: {"path": f"{variant}/s2.dll",
            "required_cpu": "avx2+fma+f16c" if variant == "cpu-avx2" else "x64-sse2",
            "required_cpu_mask": 7 if variant == "cpu-avx2" else 0,
            "imports": dependencies[variant], "cmake_options": flags[variant]}
            for variant in VARIANTS},
        "gpu": False, "model_weights_included": False,
    }
    return package_runtime(stage, output_dir, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--smoke-library", type=Path)
    parser.add_argument("--probe-library", type=Path)
    args = parser.parse_args()
    if args.smoke_library:
        smoke_library(args.smoke_library)
        return 0
    if args.probe_library:
        if sys.platform != "win32":
            raise RuntimeError("The Windows CPU probe requires Windows")
        print(json.dumps({"cpu_features": cpu_features(args.probe_library)}), flush=True)
        return 0
    if args.work_dir is None or args.output_dir is None:
        parser.error("--work-dir and --output-dir are required for a build")
    if not 1 <= args.jobs <= 16:
        parser.error("--jobs must be between 1 and 16")
    build_runtime(args.work_dir.resolve(), args.output_dir.resolve(), args.jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

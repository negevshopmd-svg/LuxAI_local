"""The optional native package must stay CPU-only, pinned and verifiable."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_fish_runtime.py"
SPEC = importlib.util.spec_from_file_location("build_fish_runtime_039f", SCRIPT)
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def minimal_pe(imports, *, delayed=False):
    data = bytearray(2048)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 132, 0x8664, 1, 0, 0, 0, 240, 0)
    opt = 152
    struct.pack_into("<H", data, opt, 0x20B)
    struct.pack_into("<IIII", data, opt + 240 + 8, 1536, 4096, 1536, 512)
    entry_size, directory = (32, 13) if delayed else (20, 1)
    struct.pack_into("<II", data, opt + 112 + directory * 8,
                     4096, entry_size * (len(imports) + 1))
    name_pos = 900
    for index, name in enumerate(imports):
        entry = 512 + index * entry_size
        if delayed:
            struct.pack_into("<I", data, entry, 1)
        struct.pack_into("<I", data, entry + (4 if delayed else 12),
                         4096 + name_pos - 512)
        encoded = name.encode("ascii") + b"\0"
        data[name_pos:name_pos + len(encoded)] = encoded
        name_pos += len(encoded)
    return bytes(data)


class FishRuntimeBuildTests(unittest.TestCase):
    def test_variants_have_an_explicit_portable_instruction_contract(self):
        baseline = build.cmake_options("cpu-baseline")
        avx2 = build.cmake_options("cpu-avx2")
        for options in (baseline, avx2):
            for expected in ("-DS2_CUDA=OFF", "-DS2_VULKAN=OFF", "-DGGML_NATIVE=OFF",
                             "-DGGML_FMA=OFF", "-DGGML_F16C=OFF", "-DGGML_BMI2=OFF",
                             "-DGGML_OPENMP=OFF", "-DBUILD_SHARED_LIBS=OFF",
                             "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded"):
                self.assertIn(expected, options)
        self.assertIn("-DGGML_AVX2=OFF", baseline)
        self.assertIn("-DGGML_AVX2=ON", avx2)
        with self.assertRaises(ValueError):
            build.cmake_options("cuda")

    def test_compat_patch_is_small_and_rejects_a_changed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "ggml/src/ggml-cpu/CMakeLists.txt"
            path.parent.mkdir(parents=True)
            path.write_text("before\n" + build._AVX2_ORIGINAL + "\nafter\n", encoding="utf-8")
            patch = build.apply_cpu_contract_patch(root)
            self.assertIn("-" + build._AVX2_ORIGINAL, patch)
            self.assertIn("+" + build._AVX2_PORTABLE, patch)
            self.assertEqual(path.read_text(encoding="utf-8"),
                             "before\n" + build._AVX2_PORTABLE + "\nafter\n")
            with self.assertRaises(ValueError):
                build.apply_cpu_contract_patch(root)

    def test_pe_imports_reject_gpu_and_external_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            dll = Path(folder) / "s2.dll"
            dll.write_bytes(minimal_pe(["KERNEL32.dll", "WS2_32.dll"]))
            self.assertEqual(build.verify_cpu_imports(dll), ["kernel32.dll", "ws2_32.dll"])
            for dependency in ("ggml-cuda.dll", "nvcuda.dll", "vcomp140.dll",
                               "vcruntime140.dll", "ggml-vulkan.dll"):
                dll.write_bytes(minimal_pe([dependency]))
                with self.subTest(dependency=dependency), self.assertRaises(ValueError):
                    build.verify_cpu_imports(dll)
            dll.write_bytes(minimal_pe(["cublas64_12.dll"], delayed=True))
            with self.assertRaises(ValueError):
                build.verify_cpu_imports(dll)

    def test_malformed_or_non_x64_pe_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            dll = Path(folder) / "s2.dll"
            for invalid in (b"not-a-dll", minimal_pe(["KERNEL32.dll"])[:600]):
                dll.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    build.pe_imports(dll)
            x86 = bytearray(minimal_pe(["KERNEL32.dll"]))
            struct.pack_into("<H", x86, 132, 0x14C)
            dll.write_bytes(x86)
            with self.assertRaises(ValueError):
                build.pe_imports(dll)

    def test_packaging_is_deterministic_and_hashes_all_input_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stage = root / "stage"
            stage.mkdir()
            for variant in build.VARIANTS:
                (stage / variant).mkdir()
                (stage / variant / "s2.dll").write_bytes(b"fixture-" + variant.encode())
            for name in ("LICENSE.txt", "GGML-LICENSE.txt", "NOTICE.txt", "BUILD-PATCHES.txt"):
                (stage / name).write_text("Required notice Ș\n", encoding="utf-8")
            manifest = {"format": 1, "source_commit": build.SOURCE_COMMIT}
            first = build.package_runtime(stage, root / "one", manifest).read_bytes()
            (stage / "manifest.json").unlink()
            second = build.package_runtime(stage, root / "two", manifest).read_bytes()
            self.assertEqual(first, second)
            archive_path = root / "two" / build.PACKAGE_NAME
            with zipfile.ZipFile(archive_path) as archive:
                data = json.loads(archive.read("manifest.json"))
                self.assertEqual(data["source_commit"], build.SOURCE_COMMIT)
                for name, details in data["files"].items():
                    content = archive.read(name)
                    self.assertEqual(details["sha256"], hashlib.sha256(content).hexdigest())
                    self.assertEqual(details["size"], len(content))
                    self.assertEqual(archive.getinfo(name).date_time, (1980, 1, 1, 0, 0, 0))
            checksum = archive_path.with_suffix(".zip.sha256").read_text(encoding="ascii")
            self.assertEqual(checksum.split()[0], hashlib.sha256(second).hexdigest())

    def test_unknown_package_file_is_not_distributed(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "private-key.txt").write_text("fixture", encoding="utf-8")
            with self.assertRaises(ValueError):
                build.package_runtime(stage, stage / "out", {})

    def test_existing_source_is_never_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(build, "run") as run:
                with self.assertRaises(ValueError):
                    build.checkout_source(root)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

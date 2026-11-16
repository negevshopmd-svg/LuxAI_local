"""0.4.1d Converter: operations, circle sectors, runtime flow and settings page."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from luxai import converter
from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime


def make_wav(path: Path, seconds=0.5):
    import wave
    samples = (np.sin(np.linspace(0, 440 * 2 * np.pi * seconds, int(16000 * seconds))) * 12000).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(samples.tobytes())
    return path


def make_video(path: Path, frames=20):
    import av
    with av.open(str(path), "w") as out:
        video = out.add_stream("libx264", rate=10)
        video.width, video.height, video.pix_fmt = 320, 180, "yuv420p"
        audio = out.add_stream("aac", rate=48000)
        audio.layout = "stereo"
        for index in range(frames):
            array = np.zeros((180, 320, 3), np.uint8)
            array[:, : index * 16] = (0, 200, 255)
            for packet in video.encode(av.VideoFrame.from_ndarray(array, format="rgb24")):
                out.mux(packet)
        for packet in video.encode(None):
            out.mux(packet)
        for _ in range(94):
            frame = av.AudioFrame.from_ndarray(np.zeros((2, 1024), np.float32), format="fltp", layout="stereo")
            frame.sample_rate = 48000
            for packet in audio.encode(frame):
                out.mux(packet)
        for packet in audio.encode(None):
            out.mux(packet)
    return path


class OperationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.image = self.base / "pic.png"
        Image.new("RGBA", (800, 400), (255, 0, 0, 128)).save(self.image)

    def test_image_operations_never_overwrite(self):
        self.assertEqual(converter.image_format(self.image, "jpg").name, "pic.jpg")
        self.assertEqual(converter.image_format(self.image, "png").name, "pic_copy.png")
        with Image.open(converter.image_resize(self.image, percent=50)) as half:
            self.assertEqual(half.size, (400, 200))
        with Image.open(converter.image_resize(self.image, max_side=200)) as small:
            self.assertEqual(small.size, (200, 100))
        with Image.open(converter.image_rotate(self.image, "right")) as rotated:
            self.assertEqual(rotated.size, (400, 800))
        with Image.open(converter.image_crop(self.image, (10, 10, 110, 60))) as cropped:
            self.assertEqual(cropped.size, (100, 50))
        self.assertTrue(converter.image_compress(self.image).name.endswith("_compressed.png"))
        self.assertTrue(converter.image_strip_metadata(self.image).is_file())
        self.assertTrue(converter.images_to_pdf([self.image, self.image]).name.endswith(".pdf"))
        out = self.base / "out"
        self.assertEqual(converter.image_format(self.image, "webp", out_dir=out).parent, out)
        with Image.open(self.image) as original:
            self.assertEqual(original.size, (800, 400))

    def test_audio_and_video(self):
        wav = make_wav(self.base / "voice.wav")
        for fmt in converter.AUDIO_FORMATS:
            result = converter.audio_convert(wav, fmt)
            self.assertTrue(result.is_file() and result.stat().st_size > 500, fmt)
        clip = make_video(self.base / "clip.mp4")
        import av
        for mode, video, audio in (("mp4", 1, 1), ("compress", 1, 1), ("mute", 1, 0)):
            with av.open(str(converter.video_convert(clip, mode=mode))) as check:
                self.assertEqual((len(check.streams.video), len(check.streams.audio)), (video, audio), mode)
        self.assertEqual(converter.video_convert(clip, mode="gif").suffix, ".gif")
        self.assertEqual(converter.audio_convert(clip, "mp3", tag="audio").name, "clip_audio.mp3")
        self.assertIn("PyAV", converter.ffmpeg_version())

    def test_kinds(self):
        self.assertEqual(converter.kind_of("a.JPG"), "image")
        self.assertEqual(converter.kind_of("a.flac"), "audio")
        self.assertEqual(converter.kind_of("a.mkv"), "video")
        self.assertEqual(converter.kind_of("a.exe"), "")


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru", "ui_theme": "dark"}
        self.tray_icon = None


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        engine = runtime.ExtensionsRuntime(_Host())
        engine.apply(catalog.normalize_state({"converter": {"enabled": True, "settings": settings}}))

        def dispose():
            engine.stop()
            for name in ("_circle", "_convert_overlay"):
                widget = getattr(engine, name, None)
                if widget is not None:
                    try:
                        widget.close()
                        widget.deleteLater()
                    except RuntimeError:
                        pass
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine

    def test_sectors_follow_settings(self):
        engine = self.make(s_crop=False, s_ogg=False)
        image_actions = [action for action, _, _ in engine.convert_sectors("image")]
        self.assertEqual(image_actions, ["format", "compress", "resize", "rotate", "nometa", "pdf", "clipboard"])
        self.assertNotIn("audio:ogg", [action for action, _, _ in engine.convert_sectors("audio")])
        self.assertEqual(len(engine.convert_sectors("video")), 5)
        self.assertEqual(engine.hotkey_entries(), [{"id": "converter.hotkey", "enabled": True, "hotkey": "ctrl+alt+x"}])

    def test_circle_and_sub_ring_by_keyboard(self):
        engine = self.make()
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "photo.png"
            Image.new("RGB", (300, 200), "blue").save(image)
            engine._show_convert_circle([image, Path(folder) / "notes.txt"])
            menu = engine._circle
            self.assertEqual(len(menu.items), 8)
            picked = []
            with mock.patch.object(engine, "run_conversion", side_effect=lambda a, s, **k: picked.append((a, s))):
                QTest.keyClick(menu, Qt.Key.Key_1)  # "Формат" opens the format ring
                self.app.processEvents()
                sub = engine._circle
                self.assertIsNot(sub, menu)
                self.assertEqual(sub.items[1][0], "format:jpg")
                QTest.keyClick(sub, Qt.Key.Key_Right)
                QTest.keyClick(sub, Qt.Key.Key_Right)
                QTest.keyClick(sub, Qt.Key.Key_Return)
            self.assertEqual(picked, [("format:jpg", [image])])

    def test_run_conversion_to_folder_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "converted"
            engine = self.make(destination="folder", folder=str(out))
            image = Path(folder) / "photo.png"
            Image.new("RGB", (300, 200), "blue").save(image)
            notices = []
            engine.notice.connect(notices.append)
            engine.run_conversion("resize:50", [image], wait=True)
            self.app.processEvents()
            results, errors = engine.last_conversion
            self.assertEqual(errors, [])
            self.assertEqual(Path(results[0]).parent, out)
            self.assertIn("Готово: photo_50pct.png", notices[-1])
            self.assertFalse(engine._converting)

    def test_clipboard_image_becomes_a_source(self):
        from PySide6.QtGui import QImage
        with tempfile.TemporaryDirectory() as folder:
            engine = self.make(folder=folder)
            image = QImage(40, 30, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.red)
            clipboard = QApplication.clipboard()
            clipboard.setImage(image)
            sources = engine._clipboard_sources(clipboard)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].parent, Path(folder))
            self.assertTrue(sources[0].is_file())


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_luxify_like_sections(self):
        from luxai.ui_extension_settings import PluginSettingsView
        state = catalog.normalize_state({"converter": {"enabled": True}})
        view = PluginSettingsView(catalog.PLUGIN_BY_ID["converter"], state["converter"], "ru")
        self.addCleanup(lambda: (view.deleteLater(), QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        self.assertEqual(list(view.cards), ["basic", "keys", "result", "sectors", "video", "appearance"])
        self.assertFalse(view.rows["folder"].isEnabled())
        view.fields["destination"].set_value("folder")
        view._refresh()
        self.assertTrue(view.rows["folder"].isEnabled())
        view.fields["s_gif"].setChecked(False)
        self.assertTrue(view.dirty)
        self.assertFalse(view.collect()["s_gif"])
        self.assertEqual(view.how_chip.text(), "Ctrl+Alt+X")


if __name__ == "__main__":
    unittest.main()

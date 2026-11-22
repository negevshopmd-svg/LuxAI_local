"""Converter operations (0.4.1d): images with Pillow, audio/video with PyAV.

No Qt here. Every operation writes a NEW file (never overwrites the
source) into ``out_dir`` (default: next to the source) and returns its path.
PyAV ships with Jarvis (faster-whisper depends on it) and bundles FFmpeg
with MP3, AAC, FLAC, Opus, H.264 and GIF encoders, so nothing is downloaded.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from fractions import Fraction
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".heic", ".avif"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v", ".flv", ".3gp", ".mpg", ".mpeg", ".ts"}

IMAGE_FORMATS = ("png", "jpg", "webp", "ico", "bmp")
AUDIO_FORMATS = ("mp3", "m4a", "wav", "flac", "ogg", "opus")


def kind_of(path) -> str:
    suffix = Path(path).suffix.casefold()
    if suffix in IMAGE_EXT:
        return "image"
    if suffix in AUDIO_EXT:
        return "audio"
    if suffix in VIDEO_EXT:
        return "video"
    return ""


def _reserve(path: Path) -> bool:
    """Create the file exclusively: two conversions can never pick the same name (audit #21)."""
    try:
        handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.close(handle)
    return True


@contextmanager
def _removed_on_error(target):
    """The reserved (empty) output is deleted when anything after the reservation fails (audit 2 #11)."""
    try:
        yield
    except BaseException:
        try:
            Path(target).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def unique_path(path: Path) -> Path:
    """A free name, already reserved on disk (an empty file the converter then writes)."""
    path = Path(path)
    if _reserve(path):
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if _reserve(candidate):
            return candidate
    raise OSError("Слишком много файлов с одинаковым именем.")


def target_path(source: Path, ext: str, tag: str = "", out_dir: Path | None = None) -> Path:
    """New name next to the source: «photo.jpg» → «photo.png» / «photo_small.jpg»."""
    source = Path(source)
    ext = ext.lstrip(".").casefold()
    stem = source.stem + (f"_{tag}" if tag else "")
    folder = Path(out_dir) if out_dir else source.parent
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"{stem}.{ext}"
    if candidate.resolve() == source.resolve():
        candidate = folder / f"{stem}_copy.{ext}"
    return unique_path(candidate)


# --- images -------------------------------------------------------------------

def _open_image(source):
    from PIL import Image, ImageOps
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
        return image.copy() if image is opened else image


def _flatten(image):
    from PIL import Image
    if image.mode in ("RGB", "L"):
        return image
    background = Image.new("RGB", image.size, "white")
    rgba = image.convert("RGBA")
    background.paste(rgba, mask=rgba.split()[-1])
    return background


def save_image(image, target: Path, quality: int = 85):
    with _removed_on_error(target):
        return _save_image(image, Path(target), quality)


def _save_image(image, target: Path, quality: int = 85):
    fmt = target.suffix.casefold().lstrip(".")
    if fmt in ("jpg", "jpeg"):
        _flatten(image).save(target, "JPEG", quality=int(quality), optimize=True, progressive=True)
    elif fmt == "webp":
        image.save(target, "WEBP", quality=int(quality), method=6)
    elif fmt == "ico":
        # Icons are square: centre the picture on a transparent square first (a 100×12 PNG failed, audit #20).
        from PIL import Image
        side = max(16, min(256, max(image.size)))
        picture = image.convert("RGBA")
        picture.thumbnail((side, side))
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(picture, ((side - picture.width) // 2, (side - picture.height) // 2))
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side]
        square.save(target, "ICO", sizes=sizes)
    elif fmt == "bmp":
        _flatten(image).save(target, "BMP")
    elif fmt == "pdf":
        _flatten(image).save(target, "PDF", resolution=150.0)
    else:
        image.save(target, "PNG", optimize=True)
    return target


def image_format(source, fmt, *, quality=85, out_dir=None) -> Path:
    if fmt not in IMAGE_FORMATS:
        raise ValueError("Неподдерживаемый формат.")
    return save_image(_open_image(source), target_path(source, fmt, out_dir=out_dir), quality)


def image_compress(source, *, quality=85, out_dir=None) -> Path:
    """JPG/WebP re-encoded at ``quality``; PNG reduced to 256 colours."""
    source = Path(source)
    image = _open_image(source)
    ext = source.suffix.casefold().lstrip(".")
    if ext in ("png", "gif", "bmp", "tif", "tiff"):
        image = image.convert("RGBA").quantize(colors=256, method=2, dither=1)
        target = target_path(source, "png", "compressed", out_dir)
        with _removed_on_error(target):  # a failed write leaves no broken «…_compressed.png» (audit 6 #10)
            image.save(target, "PNG", optimize=True)
        return target
    ext = "webp" if ext == "webp" else "jpg"
    return save_image(image, target_path(source, ext, "compressed", out_dir), min(int(quality), 80))


def image_resize(source, *, percent=0, max_side=0, quality=85, out_dir=None) -> Path:
    image = _open_image(source)
    width, height = image.size
    if percent:
        scale = percent / 100.0
    else:
        scale = min(1.0, max_side / float(max(width, height)))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    from PIL import Image
    resized = image.resize(size, Image.Resampling.LANCZOS)
    tag = f"{percent}pct" if percent else f"{max_side}px"
    ext = Path(source).suffix.casefold().lstrip(".") or "png"
    ext = "jpg" if ext == "jpeg" else ext
    if ext not in IMAGE_FORMATS:
        ext = "png"
    return save_image(resized, target_path(source, ext, tag, out_dir), quality)


def image_rotate(source, how: str, *, quality=85, out_dir=None) -> Path:
    from PIL import Image
    image = _open_image(source)
    operations = {"right": Image.Transpose.ROTATE_270, "left": Image.Transpose.ROTATE_90,
                  "180": Image.Transpose.ROTATE_180, "mirror": Image.Transpose.FLIP_LEFT_RIGHT}
    image = image.transpose(operations[how])
    ext = Path(source).suffix.casefold().lstrip(".")
    ext = "jpg" if ext == "jpeg" else (ext if ext in IMAGE_FORMATS else "png")
    return save_image(image, target_path(source, ext, {"right": "rot90", "left": "rot-90", "180": "rot180",
                                                       "mirror": "mirror"}[how], out_dir), quality)


def image_crop(source, box, *, quality=85, out_dir=None) -> Path:
    """``box`` = (left, top, right, bottom) in image pixels."""
    image = _open_image(source)
    left, top, right, bottom = (int(round(value)) for value in box)
    left, top = max(0, left), max(0, top)
    right, bottom = min(image.width, right), min(image.height, bottom)
    if right - left < 2 or bottom - top < 2:
        raise ValueError("Слишком маленькая область.")
    ext = Path(source).suffix.casefold().lstrip(".")
    ext = "jpg" if ext == "jpeg" else (ext if ext in IMAGE_FORMATS else "png")
    return save_image(image.crop((left, top, right, bottom)), target_path(source, ext, "crop", out_dir), quality)


def image_strip_metadata(source, *, quality=95, out_dir=None) -> Path:
    """Copy without EXIF/GPS/comments: save_image never passes metadata on."""
    image = _open_image(source)
    image.info = {}
    if hasattr(image, "_exif"):
        image._exif = None
    ext = Path(source).suffix.casefold().lstrip(".")
    ext = "jpg" if ext == "jpeg" else (ext if ext in IMAGE_FORMATS else "png")
    return save_image(image, target_path(source, ext, "clean", out_dir), quality)


def images_to_pdf(sources, *, out_dir=None) -> Path:
    images = [_flatten(_open_image(source)) for source in sources]
    if not images:
        raise ValueError("Нет картинок.")
    first = Path(sources[0])
    tag = "" if len(images) == 1 else f"{len(images)}pages"
    target = target_path(first, "pdf", tag, out_dir)
    with _removed_on_error(target):
        images[0].save(target, "PDF", resolution=150.0, save_all=True, append_images=images[1:])
    return target


# --- audio / video (PyAV) ---------------------------------------------------------

_AUDIO_CODECS = {"mp3": ("mp3", "libmp3lame", "fltp"), "m4a": ("ipod", "aac", "fltp"), "wav": ("wav", "pcm_s16le", "s16"),
                 "flac": ("flac", "flac", "s16"), "ogg": ("ogg", "libopus", "flt"), "opus": ("ogg", "libopus", "flt")}


def _throttled(progress):
    """Report only when the whole percent changes (audit 2 #29): not one Qt event per frame."""
    if progress is None:
        return None
    last = [-1]

    def report(value):
        percent = int(value * 100)
        if percent != last[0]:
            last[0] = percent
            progress(value)
    return report


def _progress_from(container, stream, frame, progress):
    if progress is None or frame.pts is None or not stream.time_base:
        return
    duration = container.duration / 1_000_000 if container.duration else 0
    if duration > 0:
        progress(min(0.99, float(frame.pts * stream.time_base) / duration))


def audio_convert(source, fmt, *, out_dir=None, progress=None, tag="") -> Path:
    """Convert or extract the audio track of an audio/video file."""
    import av
    if fmt not in _AUDIO_CODECS:
        raise ValueError("Неподдерживаемый формат.")
    container_format, codec, sample_format = _AUDIO_CODECS[fmt]
    progress = _throttled(progress)
    target = target_path(source, fmt, tag, out_dir)
    with _removed_on_error(target), av.open(str(source)) as inp:
        if not inp.streams.audio:
            raise ValueError("В файле нет звука.")
        in_stream = inp.streams.audio[0]
        rate = in_stream.rate or 44100
        if codec == "libopus":
            rate = 48000
        elif codec == "libmp3lame" and rate not in (32000, 44100, 48000):
            rate = 44100
        try:
            with av.open(str(target), "w", format=container_format) as out:
                out_stream = out.add_stream(codec, rate=rate)
                layout = "stereo" if (in_stream.channels or 2) >= 2 else "mono"
                out_stream.layout = layout
                if codec in ("libmp3lame", "aac"):
                    out_stream.bit_rate = 192_000
                elif codec == "libopus":
                    out_stream.bit_rate = 128_000
                resampler = av.AudioResampler(format=sample_format, layout=layout, rate=rate)
                for frame in inp.decode(in_stream):
                    _progress_from(inp, in_stream, frame, progress)
                    frame.pts = None
                    for resampled in resampler.resample(frame):
                        for packet in out_stream.encode(resampled):
                            out.mux(packet)
                for resampled in resampler.resample(None):
                    for packet in out_stream.encode(resampled):
                        out.mux(packet)
                for packet in out_stream.encode(None):
                    out.mux(packet)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target


def _even(value):
    value = max(2, int(value))
    return value - value % 2


def video_convert(source, *, mode="mp4", out_dir=None, progress=None) -> Path:
    """mode: mp4 (H.264+AAC), compress (smaller H.264, ≤1280px), gif, mute (no audio)."""
    import av
    source = Path(source)
    if mode == "gif":
        target = target_path(source, "gif", out_dir=out_dir)
    elif mode == "compress":
        target = target_path(source, "mp4", "compressed", out_dir)
    elif mode == "mute":
        target = target_path(source, "mp4", "nosound", out_dir)
    else:
        target = target_path(source, "mp4", out_dir=out_dir)
    progress = _throttled(progress)
    if mode == "gif":
        with _removed_on_error(target):
            return _video_to_gif(source, target, progress)
    rotation = _video_rotation(source)
    with _removed_on_error(target), av.open(str(source)) as inp:
        if not inp.streams.video:
            raise ValueError("В файле нет видео.")
        vin = inp.streams.video[0]
        width, height = _shown_size(vin, rotation)
        limit = {"compress": 1280}.get(mode, 0)
        if limit and max(width, height) > limit:
            scale = limit / float(max(width, height))
            width, height = width * scale, height * scale
        width, height = _even(width), _even(height)
        rate = vin.average_rate or vin.guessed_rate or Fraction(25, 1)
        try:
            with av.open(str(target), "w", format="mp4") as out:
                vout = out.add_stream("libx264", rate=rate)
                vout.pix_fmt = "yuv420p"
                vout.options = {"crf": "28" if mode == "compress" else "21", "preset": "veryfast"}
                vout.width, vout.height = width, height
                ain = inp.streams.audio[0] if (inp.streams.audio and mode in ("mp4", "compress")) else None
                aout = resampler = None
                if ain is not None:
                    aout = out.add_stream("aac", rate=48000)
                    aout.layout = "stereo"
                    aout.bit_rate = 96_000 if mode == "compress" else 160_000
                    resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
                # Keep the source's own times (variable frame rate, pauses, the offset between the
                # video and the sound): rewriting every pts put four frames at 0.00 s (audit #2).
                vout.codec_context.time_base = vin.time_base or Fraction(1, 1000)
                video_base = vout.codec_context.time_base
                start = float(inp.start_time or 0) / av.time_base
                last_pts = None
                audio_next = None
                streams = [vin] + ([ain] if ain is not None else [])
                for frame in inp.decode(*streams):
                    if isinstance(frame, av.VideoFrame):
                        _progress_from(inp, vin, frame, progress)
                        image = _upright(frame, rotation).reformat(width=width, height=height, format="yuv420p")
                        seconds = (frame.time if frame.time is not None else 0.0) - start
                        pts = max(0, int(round(seconds / float(video_base))))
                        if last_pts is not None and pts <= last_pts:
                            pts = last_pts + 1  # the encoder needs strictly growing times
                        last_pts = pts
                        image.pts = pts
                        image.time_base = video_base
                        for packet in vout.encode(image):
                            out.mux(packet)
                    elif aout is not None:
                        offset = (frame.time if frame.time is not None else start) - start
                        expected = max(0, int(round(offset * 48000)))
                        if audio_next is None or expected - audio_next > 2400:
                            # The first frame AND every later gap (> 50 ms) follow the source's own
                            # timeline, so a track with pauses stays in sync (audit 2 #13).
                            audio_next = expected
                        frame.pts = None
                        for resampled in resampler.resample(frame):
                            resampled.pts = audio_next
                            resampled.time_base = Fraction(1, 48000)
                            audio_next += resampled.samples
                            for packet in aout.encode(resampled):
                                out.mux(packet)
                if resampler is not None and audio_next is not None:
                    for resampled in resampler.resample(None):  # the samples still inside the resampler
                        resampled.pts = audio_next
                        resampled.time_base = Fraction(1, 48000)
                        audio_next += resampled.samples
                        for packet in aout.encode(resampled):
                            out.mux(packet)
                for stream in [vout] + ([aout] if aout is not None else []):
                    for packet in stream.encode(None):
                        out.mux(packet)
            expected = _media_seconds(source)
            _check_duration(target, expected)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target


def _video_rotation(path) -> int:
    """Degrees (counter-clockwise) the first video frame must be turned to be seen upright (audit 7 #22).

    Phones store portrait video sideways plus a display matrix; the encoder writes plain pixels, so
    without turning them the result came out rotated."""
    import av
    try:
        with av.open(str(path)) as probe:
            if not probe.streams.video:
                return 0
            for frame in probe.decode(probe.streams.video[0]):
                value = int(round(float(getattr(frame, "rotation", 0) or 0)))
                return value % 360 if value % 90 == 0 else 0
    except Exception:
        return 0
    return 0


def _shown_size(stream, rotation: int) -> tuple[int, int]:
    """Width and height as the video is SEEN: a portrait phone video is stored sideways."""
    width, height = stream.codec_context.width, stream.codec_context.height
    return (height, width) if rotation % 180 else (width, height)


def _upright(frame, rotation: int):
    """The frame turned upright (a new frame); the frame itself when no turn is needed."""
    if not rotation:
        return frame
    import av
    turned = av.VideoFrame.from_image(frame.to_image().rotate(rotation, expand=True))
    turned.pts = frame.pts
    if frame.time_base is not None:
        turned.time_base = frame.time_base
    return turned


def _media_seconds(path) -> float:
    import av
    try:
        with av.open(str(path)) as media:
            if media.duration:
                return float(media.duration) / av.time_base
            longest = 0.0
            for stream in media.streams:
                if stream.duration and stream.time_base:
                    longest = max(longest, float(stream.duration * stream.time_base))
            return longest
    except Exception:
        return 0.0


def _check_duration(target, expected: float) -> None:
    """A file that exists is not yet a success: its length must match the source."""
    if expected < 0.3:
        return
    actual = _media_seconds(target)
    if actual < expected * 0.6 or actual > expected * 1.6 + 1:
        raise ValueError(f"Длительность результата {actual:.2f} с не совпадает с исходной {expected:.2f} с.")


GIF_MAX_SECONDS = 20


def _video_to_gif(source, target, progress=None, fps=12, max_side=480):
    """Decode with PyAV, palette and write with Pillow (better colours)."""
    import av
    from PIL import Image
    frames = []
    moments = []
    with av.open(str(source)) as inp:
        if not inp.streams.video:
            raise ValueError("В файле нет видео.")
        vin = inp.streams.video[0]
        rate = vin.average_rate or vin.guessed_rate
        step = 1.0 / float(rate) if rate else 1.0 / fps
        last = -1.0
        end = 0.0
        first = None
        previous = None
        rotation = _video_rotation(source)
        for frame in inp.decode(vin):
            # Audit 7 #21: times count from the FIRST frame. A file whose clock starts at, say, 30 s
            # (cut from a stream) used to have every frame «after 20 s» and gave an empty GIF; a frame
            # without a time follows the one before it.
            if frame.time is None:
                moment = (previous + step) if previous is not None else 0.0
            else:
                if first is None:
                    first = frame.time
                moment = max(0.0, frame.time - first)
            previous = moment
            if moment > GIF_MAX_SECONDS:
                break
            end = moment + step  # this decoded frame is shown until the next one
            if last >= 0 and moment - last < 1.0 / fps * 0.99:
                continue
            last = moment
            image = frame.to_image()
            if rotation:
                image = image.rotate(rotation, expand=True)
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            frames.append(image.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))
            moments.append(moment)
            if progress is not None:
                progress(min(0.99, moment / GIF_MAX_SECONDS))
    if not frames:
        raise ValueError("Не удалось прочитать кадры.")
    # Each kept frame stays until the NEXT kept frame (audit 2 #12): pauses keep their length
    # instead of a fixed 80 ms per frame (a 1 s clip became 160 ms).
    durations = [max(20, int(round((after - moment) * 1000)))
                 for moment, after in zip(moments, moments[1:] + [max(end, moments[-1] + 1.0 / fps)])]
    try:
        frames[0].save(target, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                       loop=0, optimize=True, disposal=2)
    except Exception:
        Path(target).unlink(missing_ok=True)
        raise
    return Path(target)


def ffmpeg_version() -> str:
    try:
        import av
        return f"PyAV {av.__version__}, FFmpeg {av.library_versions.get('libavcodec', ('?',))[0]}"
    except Exception:
        return ""

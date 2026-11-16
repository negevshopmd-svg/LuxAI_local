"""Converter operations (0.4.1d): images with Pillow, audio/video with PyAV.

No Qt here. Every operation writes a NEW file (never overwrites the
source) into ``out_dir`` (default: next to the source) and returns its path.
PyAV ships with Jarvis (faster-whisper depends on it) and bundles FFmpeg
with MP3, AAC, FLAC, Opus, H.264 and GIF encoders, so nothing is downloaded.
"""
from __future__ import annotations

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


def unique_path(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
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
    fmt = target.suffix.casefold().lstrip(".")
    if fmt in ("jpg", "jpeg"):
        _flatten(image).save(target, "JPEG", quality=int(quality), optimize=True, progressive=True)
    elif fmt == "webp":
        image.save(target, "WEBP", quality=int(quality), method=6)
    elif fmt == "ico":
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(image.size)] or [(16, 16)]
        image.save(target, "ICO", sizes=sizes)
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
    images[0].save(target, "PDF", resolution=150.0, save_all=True, append_images=images[1:])
    return target


# --- audio / video (PyAV) ---------------------------------------------------------

_AUDIO_CODECS = {"mp3": ("mp3", "libmp3lame", "fltp"), "m4a": ("ipod", "aac", "fltp"), "wav": ("wav", "pcm_s16le", "s16"),
                 "flac": ("flac", "flac", "s16"), "ogg": ("ogg", "libopus", "flt"), "opus": ("ogg", "libopus", "flt")}


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
    target = target_path(source, fmt, tag, out_dir)
    with av.open(str(source)) as inp:
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
    if mode == "gif":
        return _video_to_gif(source, target, progress)
    with av.open(str(source)) as inp:
        if not inp.streams.video:
            raise ValueError("В файле нет видео.")
        vin = inp.streams.video[0]
        width, height = vin.codec_context.width, vin.codec_context.height
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
                streams = [vin] + ([ain] if ain is not None else [])
                for frame in inp.decode(*streams):
                    if isinstance(frame, av.VideoFrame):
                        _progress_from(inp, vin, frame, progress)
                        image = frame.reformat(width=width, height=height, format="yuv420p")
                        image.pts = None
                        for packet in vout.encode(image):
                            out.mux(packet)
                    elif aout is not None:
                        frame.pts = None
                        for resampled in resampler.resample(frame):
                            for packet in aout.encode(resampled):
                                out.mux(packet)
                for stream in [vout] + ([aout] if aout is not None else []):
                    for packet in stream.encode(None):
                        out.mux(packet)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target


GIF_MAX_SECONDS = 20


def _video_to_gif(source, target, progress=None, fps=12, max_side=480):
    """Decode with PyAV, palette and write with Pillow (better colours)."""
    import av
    from PIL import Image
    frames = []
    with av.open(str(source)) as inp:
        if not inp.streams.video:
            raise ValueError("В файле нет видео.")
        vin = inp.streams.video[0]
        last = -1.0
        for frame in inp.decode(vin):
            moment = frame.time or 0.0
            if moment > GIF_MAX_SECONDS:
                break
            if last >= 0 and moment - last < 1.0 / fps * 0.99:
                continue
            last = moment
            image = frame.to_image()
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            frames.append(image.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))
            if progress is not None:
                progress(min(0.99, moment / GIF_MAX_SECONDS))
    if not frames:
        raise ValueError("Не удалось прочитать кадры.")
    try:
        frames[0].save(target, "GIF", save_all=True, append_images=frames[1:], duration=int(1000 / fps),
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

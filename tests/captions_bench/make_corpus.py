"""Build the live-captions benchmark audio: known sentences read by the local Piper voices (ru / en / ro).

Each language becomes one 16 kHz mono stream like a video: sentences with natural pauses, some joined without
a pause (continuous speech), a varied speaking rate and quiet background noise. Writes <out>/<lang>.wav and
<out>/<lang>.json (the reference text and where each sentence starts and ends). Nothing is downloaded.

    python tests/captions_bench/make_corpus.py <install folder> <out folder>
"""
from __future__ import annotations

import io
import json
import sys
import wave
from pathlib import Path

import numpy as np

SENTENCES = {
    "en": [
        "Good evening and welcome to the news at nine.",
        "Heavy rain is expected across the north of the country tomorrow morning.",
        "The government said the new bridge will open to traffic in early spring.",
        "Scientists have discovered a new species of frog in the mountains of Peru.",
        "Ticket prices for the national football final rose by almost twenty percent.",
        "Now let's go over to our reporter, who is standing outside the station.",
        "Thank you, James. As you can see, the trains are running again after the strike.",
        "Many passengers told us they had waited for more than two hours.",
        "The company promised to refund every ticket that was cancelled this week.",
        "In other news, the city museum will stay open late every Friday this summer.",
        "And finally, a dog in Scotland has learned to ring the doorbell when it wants to come home.",
        "That is all for tonight, thank you for watching and good night.",
    ],
    "ru": [
        "Добрый вечер, в эфире вечерние новости.",
        "Завтра утром на севере страны ожидаются сильные дожди и порывистый ветер.",
        "Правительство сообщило, что новый мост откроют для движения ранней весной.",
        "Учёные обнаружили в горах новый вид лягушек, который раньше никто не видел.",
        "Цены на билеты на финал чемпионата выросли почти на двадцать процентов.",
        "А теперь слово нашему корреспонденту, который находится у вокзала.",
        "Спасибо. Как видите, после забастовки поезда снова ходят по расписанию.",
        "Многие пассажиры рассказали нам, что ждали больше двух часов.",
        "Компания пообещала вернуть деньги за все отменённые на этой неделе билеты.",
        "Городской музей этим летом будет работать по пятницам до позднего вечера.",
        "И напоследок: собака в Шотландии научилась звонить в дверь, когда хочет домой.",
        "На этом всё, спасибо, что были с нами, и спокойной ночи.",
    ],
    "ro": [
        "Bună seara și bine ați venit la știrile de la ora nouă.",
        "Mâine dimineață sunt așteptate ploi puternice în nordul țării.",
        "Guvernul a anunțat că noul pod va fi deschis circulației la începutul primăverii.",
        "Cercetătorii au descoperit o nouă specie de broască în munții din Peru.",
        "Prețul biletelor pentru finala campionatului a crescut cu aproape douăzeci la sută.",
        "Acum mergem la reporterul nostru, care se află în fața gării.",
        "Mulțumesc. După cum vedeți, trenurile circulă din nou după grevă.",
        "Mulți pasageri ne-au spus că au așteptat mai mult de două ore.",
        "Compania a promis că va returna banii pentru toate biletele anulate săptămâna aceasta.",
        "Muzeul orașului va rămâne deschis până seara târziu în fiecare vineri din această vară.",
        "Și în încheiere, un câine din Scoția a învățat să sune la ușă când vrea să intre acasă.",
        "Asta a fost tot pentru astă seară, vă mulțumim și noapte bună.",
    ],
}
VOICES = {"en": "en_US-lessac-medium.onnx", "ru": "ru_RU-dmitri-medium.onnx", "ro": "ro_RO-mihai-medium.onnx"}
# pause after each sentence (s); 0 = the next one follows at once (continuous speech)
PAUSES = [0.6, 0.25, 0.0, 0.8, 0.3, 0.5, 0.0, 0.4, 0.7, 0.0, 0.5, 1.5]
RATES = [1.0, 1.08, 0.95, 1.12, 1.0, 1.05, 1.1, 0.97, 1.03, 1.15, 1.0, 1.0]
SAMPLE_RATE = 16000


def resample(audio: np.ndarray, rate: int) -> np.ndarray:
    import av
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    frame = av.AudioFrame.from_ndarray(audio.astype(np.float32)[None, :], format="flt", layout="mono")
    frame.sample_rate = rate
    parts = [out.to_ndarray().reshape(-1) for out in resampler.resample(frame)]
    parts += [out.to_ndarray().reshape(-1) for out in resampler.resample(None)]
    return np.concatenate(parts).astype(np.float32)


def speak(voice, text: str, rate: float) -> np.ndarray:
    from piper.config import SynthesisConfig
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        voice.synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1.0 / rate))
    buffer.seek(0)
    with wave.open(buffer, "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        return resample(samples, wav.getframerate())


def pink_noise(count: int, rng) -> np.ndarray:
    white = rng.standard_normal(count).astype(np.float32)
    spectrum = np.fft.rfft(white)
    spectrum /= np.sqrt(np.arange(1, len(spectrum) + 1))
    noise = np.fft.irfft(spectrum, n=count).astype(np.float32)
    return noise / (np.max(np.abs(noise)) or 1.0)


def build(install: Path, out: Path, language: str) -> None:
    from piper import PiperVoice
    voice = PiperVoice.load(str(install / "voices" / VOICES[language]))
    rng = np.random.default_rng(7)
    pieces, timeline, position = [np.zeros(int(SAMPLE_RATE * 1.0), dtype=np.float32)], [], 1.0
    for index, sentence in enumerate(SENTENCES[language]):
        audio = speak(voice, sentence, RATES[index]) * 0.5  # a video plays quieter than full scale
        timeline.append({"text": sentence, "start": round(position, 3), "end": round(position + len(audio) / SAMPLE_RATE, 3)})
        pieces.append(audio)
        position += len(audio) / SAMPLE_RATE
        pause = np.zeros(int(SAMPLE_RATE * PAUSES[index]), dtype=np.float32)
        pieces.append(pause)
        position += len(pause) / SAMPLE_RATE
    stream = np.concatenate(pieces)
    stream = stream + pink_noise(len(stream), rng) * 0.02  # background noise ~ -28 dB under the speech
    stream = np.clip(stream, -1.0, 1.0)
    out.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out / f"{language}.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes((stream * 32767).astype(np.int16).tobytes())
    (out / f"{language}.json").write_text(json.dumps({"language": language, "seconds": round(len(stream) / SAMPLE_RATE, 2),
                                                      "sentences": timeline}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(language, round(len(stream) / SAMPLE_RATE, 1), "s")


if __name__ == "__main__":
    install, out = Path(sys.argv[1]), Path(sys.argv[2])
    for code in ("en", "ru", "ro"):
        build(install, out, code)

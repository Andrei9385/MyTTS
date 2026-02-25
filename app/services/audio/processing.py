import json
import subprocess
from pathlib import Path

import numpy as np
from pydub import AudioSegment, effects, silence


def ffmpeg_normalize(input_path: str, output_path: str) -> None:
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-ac', '1', '-ar', '48000', '-sample_fmt', 's16', output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def trim_and_loudnorm(path: str) -> str:
    audio = AudioSegment.from_file(path)
    chunks = silence.split_on_silence(audio, min_silence_len=250, silence_thresh=audio.dBFS - 18, keep_silence=80)
    if chunks:
        audio = sum(chunks)
    audio = effects.normalize(audio)
    processed = str(Path(path).with_name(f"{Path(path).stem}_clean.wav"))
    audio.export(processed, format='wav')
    return processed


def concat_with_pauses(chunks: list[str], output: str, line_pause_ms: int = 220, stanza_pause_ms: int = 550) -> str:
    merged = AudioSegment.silent(duration=1)
    for chunk in chunks:
        if chunk == '__STANZA_BREAK__':
            merged += AudioSegment.silent(duration=stanza_pause_ms)
            continue
        seg = AudioSegment.from_file(chunk)
        # pydub requires crossfade <= both appended segments.
        crossfade = min(40, len(seg), len(merged))
        merged = merged.append(seg, crossfade=max(crossfade, 0))
        merged += AudioSegment.silent(duration=line_pause_ms)
    merged.export(output, format=Path(output).suffix.lstrip('.'))
    return output


def embed_from_wav(path: str) -> dict:
    audio = AudioSegment.from_file(path)
    samples = np.array(audio.get_array_of_samples()).astype(np.float32)
    if samples.size == 0:
        return {'energy': 0.0, 'pitch_hint': 0.0}
    spec = np.fft.rfft(samples[: min(samples.size, 48000)])
    energy = float(np.mean(np.abs(samples)))
    pitch_hint = float(np.argmax(np.abs(spec)) / max(len(spec), 1))
    return {'energy': energy, 'pitch_hint': pitch_hint, 'duration_sec': len(audio) / 1000.0}


def save_json(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

from pathlib import Path

import torch
from pydub import AudioSegment


class SileroBackend:
    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        Path(models_dir).mkdir(parents=True, exist_ok=True)
        self.device = torch.device('cpu')
        self.model, self.sample_rate = self._load()

    def _load(self):
        torch.set_num_threads(4)
        model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-models',
            model='silero_tts',
            language='ru',
            speaker='v4_ru',
            trust_repo=True,
        )
        model.to(self.device)
        return model, 48000

    def _pick_speaker(self, profile_params: dict | None) -> str:
        base = 'baya'
        if not profile_params:
            return base
        pitch = profile_params.get('pitch_hint', 0)
        if pitch > 0.2:
            return 'xenia'
        if pitch < 0.08:
            return 'aidar'
        return base

    def tts_to_file(self, text: str, output_wav: str, speed: float = 1.0, profile_params: dict | None = None):
        speaker = self._pick_speaker(profile_params)
        self.model.save_wav(text=text, speaker=speaker, sample_rate=self.sample_rate, audio_path=output_wav)
        if abs(speed - 1.0) > 1e-3:
            seg = AudioSegment.from_wav(output_wav)
            seg = seg._spawn(seg.raw_data, overrides={'frame_rate': int(seg.frame_rate * speed)}).set_frame_rate(seg.frame_rate)
            seg.export(output_wav, format='wav')

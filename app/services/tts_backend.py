import hashlib
import json
import warnings
from pathlib import Path

import torch
from pydub import AudioSegment




def _ensure_torch_load_compat() -> None:
    """Force trusted local XTTS checkpoints to load with weights_only=False on torch>=2.6."""
    original_load = getattr(torch, 'load', None)
    if original_load is None or getattr(original_load, '_voiceai_patched', False):
        return

    def _patched_torch_load(*args, **kwargs):
        kwargs.setdefault('weights_only', False)
        return original_load(*args, **kwargs)

    _patched_torch_load._voiceai_patched = True
    torch.load = _patched_torch_load

def _ensure_transformers_compat() -> None:
    """Patch Transformers API differences required by TTS XTTS loader."""
    try:
        import transformers
    except Exception:
        return

    if getattr(transformers, 'BeamSearchScorer', None) is None:
        try:
            from transformers.generation.beam_search import BeamSearchScorer

            transformers.BeamSearchScorer = BeamSearchScorer
        except Exception:
            return


def _suppress_known_torchaudio_deprecation_warnings() -> None:
    """Silence noisy upstream torchaudio deprecation warnings from XTTS internals."""
    warnings.filterwarnings(
        'ignore',
        message=r'.*load_with_torchcodec.*',
        category=UserWarning,
        module=r'torchaudio\._backend\.utils',
    )
    warnings.filterwarnings(
        'ignore',
        message=r'.*StreamingMediaDecoder has been deprecated.*',
        category=UserWarning,
        module=r'torchaudio\._backend\.ffmpeg',
    )


class XTTSBackend:
    def __init__(self, models_dir: str):
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.device = 'cpu'
        self.model = None

    def _load(self):
        if self.model is not None:
            return self.model
        _suppress_known_torchaudio_deprecation_warnings()
        _ensure_torch_load_compat()
        _ensure_transformers_compat()
        from TTS.api import TTS

        torch.set_num_threads(4)
        self.model = TTS(model_name='tts_models/multilingual/multi-dataset/xtts_v2', progress_bar=False).to(self.device)
        return self.model

    @staticmethod
    def _hash_paths(paths: list[str]) -> str:
        key = '|'.join(sorted(paths))
        return hashlib.sha256(key.encode('utf-8')).hexdigest()

    def build_profile_cache(self, speaker_wavs: list[str], profile_dir: str) -> dict:
        profile_path = Path(profile_dir)
        profile_path.mkdir(parents=True, exist_ok=True)
        refs = [str(Path(x)) for x in speaker_wavs]
        cache = {
            'backend': 'xtts_v2',
            'mode': 'multi_reference_cloning',
            'speaker_wavs': refs,
            'refs_hash': self._hash_paths(refs),
            'language': 'ru',
        }
        p = profile_path / 'conditioning.json'
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
        cache['cache_path'] = str(p)
        return cache

    def tts_to_file(self, text: str, output_wav: str, speed: float, speaker_wavs: list[str], language: str = 'ru') -> None:
        model = self._load()
        model.tts_to_file(text=text, file_path=output_wav, speaker_wav=speaker_wavs, language=language, speed=speed)

    @staticmethod
    def transcode_if_needed(path_wav: str, final_path: str) -> str:
        if final_path.endswith('.wav'):
            return path_wav
        AudioSegment.from_wav(path_wav).export(final_path, format='mp3', bitrate='192k')
        return final_path

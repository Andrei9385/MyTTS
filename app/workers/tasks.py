import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Artifact, JobStatus, TTSJob, TrainJob, VoiceProfile, VoiceSample
from app.services.audio.processing import concat_with_pauses, save_json
from app.services.text.frontend import RussianTextFrontend
from app.services.tts_backend import XTTSBackend
from app.workers.celery_app import celery_app

settings = get_settings()
_frontend = None
_tts = None


def _get_frontend():
    global _frontend
    if _frontend is None:
        _frontend = RussianTextFrontend(settings.accent_overrides_path)
    return _frontend


def _get_tts():
    global _tts
    if _tts is None:
        _tts = XTTSBackend(settings.models_dir)
    return _tts


def _profile_refs(db, voice_id: str, profile_id: str | None = None) -> list[str]:
    if profile_id:
        profile = db.get(VoiceProfile, profile_id)
        if profile and profile.params.get('speaker_wavs'):
            return profile.params['speaker_wavs']
    return [x.normalized_path for x in db.execute(select(VoiceSample).where(VoiceSample.voice_id == voice_id)).scalars().all()]


@celery_app.task(bind=True, name='app.workers.tasks.run_preview')
def run_preview(self, job_id: str, payload: dict):
    db = SessionLocal()
    try:
        job = db.get(TTSJob, job_id)
        job.status = JobStatus.running
        job.progress = 10
        db.commit()
        frontend = _get_frontend()
        prepared = frontend.preprocess(
            payload['text'],
            payload.get('use_accenting', True),
            payload.get('use_user_overrides', True),
            payload.get('accent_mode', 'auto_plus_overrides'),
        )
        stress_hint_mode = payload.get('stress_hint_mode', 'none')
        backend_text = frontend.to_tts_stress_format(prepared, mode=stress_hint_mode)
        job.input_params = {
            **(job.input_params or {}),
            'prepared_text': prepared,
            'backend_text': backend_text,
            'stress_hint_mode': stress_hint_mode,
        }
        db.commit()

        refs = _profile_refs(db, payload['voice_id'])
        if not refs:
            raise RuntimeError('No reference samples for preview')
        out_dir = Path(settings.outputs_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output = str(out_dir / f'{job_id}.wav')
        _get_tts().tts_to_file(text=backend_text, output_wav=output, speed=1.0, speaker_wavs=refs)
        job.status = JobStatus.done
        job.progress = 100
        job.output_path = output
        db.add(Artifact(job_id=job_id, kind='preview', path=output, meta={'backend': 'xtts_v2'}))
        db.commit()
        return {'output': output}
    except Exception as exc:
        db.rollback()
        job = db.get(TTSJob, job_id)
        if job:
            job.status = JobStatus.failed
            job.error_text = str(exc)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name='app.workers.tasks.run_train')
def run_train(self, job_id: str, voice_id: str, profile_name: str):
    db = SessionLocal()
    try:
        job = db.get(TrainJob, job_id)
        job.status = JobStatus.running
        job.progress = 10
        db.commit()
        refs = _profile_refs(db, voice_id)
        if not refs:
            raise RuntimeError('No samples for profile improve')
        profile = VoiceProfile(voice_id=voice_id, name=profile_name, status='building', params={'legacy': False, 'speaker_wavs': refs})
        db.add(profile)
        db.flush()
        profile_dir = Path(settings.profiles_dir) / voice_id / profile.id
        cache = _get_tts().build_profile_cache(refs, str(profile_dir))
        profile.params = {**profile.params, **cache}
        profile.status = 'ready'
        profile.model_path = cache['cache_path']
        save_json(str(profile_dir / 'profile.json'), profile.params)
        job.progress = 100
        job.status = JobStatus.done
        job.output_path = profile.model_path
        db.add(Artifact(job_id=job_id, kind='profile', path=profile.model_path, meta={'backend': 'xtts_v2'}))
        db.commit()
        return {'profile_id': profile.id}
    except Exception as exc:
        db.rollback()
        job = db.get(TrainJob, job_id)
        if job:
            job.status = JobStatus.failed
            job.error_text = str(exc)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name='app.workers.tasks.run_tts')
def run_tts(self, job_id: str, payload: dict):
    db = SessionLocal()
    try:
        job = db.get(TTSJob, job_id)
        job.status = JobStatus.running
        job.progress = 5
        db.commit()
        frontend = _get_frontend()
        prepared = frontend.preprocess(
            payload['text'],
            payload['use_accenting'],
            payload['use_user_overrides'],
            payload.get('accent_mode', 'auto_plus_overrides'),
        )
        stress_hint_mode = payload.get('stress_hint_mode', 'none')
        backend_text = frontend.to_tts_stress_format(prepared, mode=stress_hint_mode)
        job.input_params = {
            **(job.input_params or {}),
            'prepared_text': prepared,
            'backend_text': backend_text,
            'stress_hint_mode': stress_hint_mode,
        }
        db.commit()
        parts = frontend.split_poem(backend_text) if payload['mode'] == 'poem' else frontend.split_story(backend_text)
        refs = _profile_refs(db, payload['voice_id'], payload.get('profile_id'))
        if not refs:
            raise RuntimeError('No references found for selected voice/profile')
        out_dir = Path(settings.jobs_dir) / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        chunk_paths = []
        usable = [x for x in parts if x != '__STANZA_BREAK__']
        total = max(len(usable), 1)
        idx = 0
        for part in parts:
            if part == '__STANZA_BREAK__':
                chunk_paths.append('__STANZA_BREAK__')
                continue
            idx += 1
            wav = str(out_dir / f'chunk_{idx}.wav')
            _get_tts().tts_to_file(text=part, output_wav=wav, speed=payload['speed'], speaker_wavs=refs)
            chunk_paths.append(wav)
            job.progress = min(95, int((idx / total) * 90) + 5)
            db.commit()

        final_ext = payload['format']
        final_path = str(Path(settings.outputs_dir) / f'{job_id}.{final_ext}')
        temp_wav = str(Path(settings.outputs_dir) / f'{job_id}.wav')
        pause_line = 260 if payload['mode'] == 'story' else 350
        pause_stanza = 550 if payload['mode'] == 'story' else 900
        concat_with_pauses(chunk_paths, temp_wav, line_pause_ms=pause_line, stanza_pause_ms=pause_stanza)
        if final_ext == 'mp3':
            _get_tts().transcode_if_needed(temp_wav, final_path)
            os.remove(temp_wav)
        else:
            final_path = temp_wav

        job.status = JobStatus.done
        job.progress = 100
        job.output_path = final_path
        db.add(Artifact(job_id=job_id, kind='tts', path=final_path, meta={'backend': 'xtts_v2', 'mode': payload['mode']}))
        db.commit()
        return {'output': final_path}
    except Exception as exc:
        db.rollback()
        job = db.get(TTSJob, job_id)
        if job:
            job.status = JobStatus.failed
            job.error_text = str(exc)
            db.commit()
        raise
    finally:
        db.close()

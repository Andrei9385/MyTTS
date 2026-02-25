import os
from pathlib import Path

from pydub import AudioSegment
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Artifact, JobStatus, TTSJob, TrainJob, VoiceProfile, VoiceSample
from app.services.audio.processing import concat_with_pauses, embed_from_wav, ffmpeg_normalize, save_json, trim_and_loudnorm
from app.services.text.frontend import RussianTextFrontend
from app.services.tts_backend import SileroBackend
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
        _tts = SileroBackend(settings.models_dir)
    return _tts


@celery_app.task(bind=True, name='app.workers.tasks.run_preview')
def run_preview(self, job_id: str, voice_id: str, text: str):
    db = SessionLocal()
    try:
        job = db.get(TTSJob, job_id)
        job.status = JobStatus.running
        job.progress = 10
        db.commit()

        sample = db.execute(select(VoiceSample).where(VoiceSample.voice_id == voice_id).order_by(VoiceSample.created_at.desc())).scalars().first()
        if not sample:
            raise RuntimeError('No voice sample found for preview')
        emb = embed_from_wav(sample.normalized_path)

        out_dir = Path(settings.outputs_dir) / voice_id
        out_dir.mkdir(parents=True, exist_ok=True)
        output = str(out_dir / f'preview_{job_id}.wav')
        _get_tts().tts_to_file(text=text, output_wav=output, speed=1.0, profile_params=emb)

        job.status = JobStatus.done
        job.progress = 100
        job.output_path = output
        db.add(Artifact(job_id=job_id, kind='preview', path=output, meta=emb))
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
        job.progress = 5
        db.commit()

        samples = db.execute(select(VoiceSample).where(VoiceSample.voice_id == voice_id)).scalars().all()
        if not samples:
            raise RuntimeError('No samples for training')

        embeds = [embed_from_wav(s.normalized_path) for s in samples]
        energy = sum(e['energy'] for e in embeds) / len(embeds)
        pitch = sum(e['pitch_hint'] for e in embeds) / len(embeds)
        params = {'energy': energy, 'pitch_hint': pitch, 'strategy': 'light-adaptation'}

        profile = VoiceProfile(voice_id=voice_id, name=profile_name, status='ready', params=params)
        db.add(profile)
        db.flush()

        profile_path = str(Path(settings.profiles_dir) / voice_id / f'{profile.id}.json')
        save_json(profile_path, params)
        profile.model_path = profile_path

        job.progress = 100
        job.status = JobStatus.done
        job.output_path = profile_path
        db.add(Artifact(job_id=job_id, kind='profile', path=profile_path, meta=params))
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
        job.progress = 2
        db.commit()

        profile_params = None
        if payload.get('profile_id'):
            profile = db.get(VoiceProfile, payload['profile_id'])
            profile_params = profile.params if profile else None

        frontend = _get_frontend()
        prepared = frontend.preprocess(payload['text'], payload['use_accenting'], payload['use_user_overrides'])
        parts = frontend.split_poem(prepared) if payload['mode'] == 'poem' else frontend.split_story(prepared)

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
            _get_tts().tts_to_file(text=part, output_wav=wav, speed=payload['speed'], profile_params=profile_params)
            chunk_paths.append(wav)
            job.progress = min(95, int((idx / total) * 90) + 5)
            db.commit()

        final_ext = payload['format']
        final_path = str(Path(settings.outputs_dir) / f'{job_id}.{final_ext}')
        pause_line = 260 if payload['mode'] == 'story' else 350
        pause_stanza = 550 if payload['mode'] == 'story' else 900
        temp_wav = str(Path(settings.outputs_dir) / f'{job_id}.wav')
        concat_with_pauses(chunk_paths, temp_wav, line_pause_ms=pause_line, stanza_pause_ms=pause_stanza)

        if final_ext == 'mp3':
            AudioSegment.from_wav(temp_wav).export(final_path, format='mp3', bitrate='192k')
            os.remove(temp_wav)
        else:
            final_path = temp_wav

        job.status = JobStatus.done
        job.progress = 100
        job.output_path = final_path
        db.add(Artifact(job_id=job_id, kind='tts', path=final_path, meta={'mode': payload['mode']}))
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

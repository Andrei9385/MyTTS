import json
import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import JobStatus, JobType, TTSJob, TrainJob, UISession, Voice, VoiceProfile, VoiceSample
from app.schemas.api import JobOut, PreviewRequest, ProfileOut, SimpleJobResponse, TTSRequest, TrainRequest, UISessionPayload, VoiceCreateResponse, VoiceOut
from app.services.audio.processing import ffmpeg_normalize, trim_and_loudnorm
from app.services.repository import list_jobs, list_profiles, list_voices
from app.workers.celery_app import celery_app

settings = get_settings()
app = FastAPI(title='Voice AI API (XTTS)')
app.mount('/media', StaticFiles(directory=settings.data_root), name='media')


@app.on_event('startup')
def startup() -> None:
    for p in [settings.uploads_dir, settings.voices_dir, settings.profiles_dir, settings.jobs_dir, settings.outputs_dir, settings.models_dir]:
        Path(p).mkdir(parents=True, exist_ok=True)


@app.get('/', response_class=HTMLResponse)
def wizard_ui():
    return Path('app/ui/wizard.html').read_text(encoding='utf-8')


@app.get('/health')
def health():
    return {'status': 'ok', 'backend': 'xtts_v2'}


def _get_or_create_ui_session(db: Session, session_id: str | None) -> UISession:
    sess = db.get(UISession, session_id) if session_id else None
    if sess:
        return sess
    sess = db.execute(select(UISession).order_by(desc(UISession.updated_at))).scalars().first()
    if sess:
        return sess
    sess = UISession()
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


@app.get('/v1/ui/session')
def get_ui_session(session_id: str | None = None, db: Session = Depends(get_db)):
    sess = _get_or_create_ui_session(db, session_id)
    return {c.name: getattr(sess, c.name) for c in sess.__table__.columns}


@app.post('/v1/ui/session')
def update_ui_session(payload: UISessionPayload, db: Session = Depends(get_db)):
    sess = _get_or_create_ui_session(db, payload.session_id)
    for k, v in payload.model_dump(exclude_none=True).items():
        if k != 'session_id':
            setattr(sess, k, v)
    db.commit()
    db.refresh(sess)
    return {c.name: getattr(sess, c.name) for c in sess.__table__.columns}


@app.post('/v1/ui/session/reset')
def reset_ui_session(db: Session = Depends(get_db)):
    sess = UISession()
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return {c.name: getattr(sess, c.name) for c in sess.__table__.columns}


@app.get('/v1/ui/history')
def ui_history(db: Session = Depends(get_db)):
    jobs = list_jobs(db)
    jobs = sorted(jobs, key=lambda x: x.updated_at, reverse=True)[:20]
    return [JobOut(**{c.name: getattr(j, c.name) for c in j.__table__.columns}) for j in jobs]


@app.post('/v1/ui/retry-job')
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(TTSJob, job_id) or db.get(TrainJob, job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    params = job.input_params
    if isinstance(job, TrainJob):
        new_job = TrainJob(type=JobType.train, status=JobStatus.pending, input_params=params)
        db.add(new_job)
        db.commit()
        celery_app.send_task('app.workers.tasks.run_train', args=[new_job.id, params['voice_id'], params['profile_name']])
    else:
        new_job = TTSJob(type=job.type, status=JobStatus.pending, input_params=params)
        db.add(new_job)
        db.commit()
        if job.type == JobType.preview:
            celery_app.send_task('app.workers.tasks.run_preview', args=[new_job.id, params])
        else:
            celery_app.send_task('app.workers.tasks.run_tts', args=[new_job.id, params])
    return {'job_id': new_job.id}


@app.post('/v1/voices', response_model=VoiceCreateResponse)
async def create_voice(
    name: str = Form(...),
    description: str = Form(default=''),
    samples: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    voice = Voice(name=name, description=description)
    db.add(voice)
    db.flush()
    sample_ids = []
    target_voice_dir = Path(settings.voices_dir) / voice.id
    target_voice_dir.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        ext = Path(sample.filename).suffix.lower()
        if ext not in ['.wav', '.mp3', '.m4a', '.ogg']:
            raise HTTPException(400, f'Unsupported file: {sample.filename}')
        raw_path = target_voice_dir / f'{uuid.uuid4()}{ext}'
        with raw_path.open('wb') as f:
            shutil.copyfileobj(sample.file, f)
        normalized = target_voice_dir / f'{raw_path.stem}_norm.wav'
        ffmpeg_normalize(str(raw_path), str(normalized))
        cleaned = trim_and_loudnorm(str(normalized))
        sample_entity = VoiceSample(voice_id=voice.id, source_path=str(raw_path), normalized_path=cleaned)
        db.add(sample_entity)
        db.flush()
        sample_ids.append(sample_entity.id)
    db.commit()
    return VoiceCreateResponse(voice_id=voice.id, sample_ids=sample_ids)


@app.get('/v1/voices', response_model=list[VoiceOut])
def get_voices(db: Session = Depends(get_db)):
    return list_voices(db)


@app.get('/v1/voices/{voice_id}', response_model=VoiceOut)
def get_voice(voice_id: str, db: Session = Depends(get_db)):
    voice = db.get(Voice, voice_id)
    if not voice:
        raise HTTPException(404, 'Voice not found')
    return voice


@app.post('/v1/voices/{voice_id}/preview', response_model=SimpleJobResponse)
def preview_voice(voice_id: str, req: PreviewRequest, db: Session = Depends(get_db)):
    if not db.get(Voice, voice_id):
        raise HTTPException(404, 'Voice not found')
    payload = {
        'voice_id': voice_id,
        'text': req.text,
        'use_accenting': req.use_accenting,
        'use_user_overrides': req.use_user_overrides,
        'accent_mode': req.accent_mode,
    }
    job = TTSJob(type=JobType.preview, status=JobStatus.pending, input_params=payload)
    db.add(job)
    db.commit()
    celery_app.send_task('app.workers.tasks.run_preview', args=[job.id, payload])
    return SimpleJobResponse(job_id=job.id, status='pending')


@app.post('/v1/voices/{voice_id}/train', response_model=SimpleJobResponse)
def train_voice(voice_id: str, req: TrainRequest, db: Session = Depends(get_db)):
    if not db.get(Voice, voice_id):
        raise HTTPException(404, 'Voice not found')
    job = TrainJob(type=JobType.train, status=JobStatus.pending, input_params={'voice_id': voice_id, 'profile_name': req.profile_name})
    db.add(job)
    db.commit()
    celery_app.send_task('app.workers.tasks.run_train', args=[job.id, voice_id, req.profile_name])
    return SimpleJobResponse(job_id=job.id, status='pending')


@app.get('/v1/voices/{voice_id}/profiles', response_model=list[ProfileOut])
def get_profiles(voice_id: str, db: Session = Depends(get_db)):
    return list_profiles(db, voice_id)


@app.post('/v1/tts', response_model=SimpleJobResponse)
def tts(req: TTSRequest, db: Session = Depends(get_db)):
    if not db.get(Voice, req.voice_id):
        raise HTTPException(404, 'Voice not found')
    if req.profile_id and not db.get(VoiceProfile, req.profile_id):
        raise HTTPException(404, 'Profile not found')
    payload = req.model_dump()
    job = TTSJob(type=JobType.tts, status=JobStatus.pending, input_params=payload)
    db.add(job)
    db.commit()
    celery_app.send_task('app.workers.tasks.run_tts', args=[job.id, payload])
    return SimpleJobResponse(job_id=job.id, status='pending')


@app.get('/v1/jobs/{job_id}', response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(TTSJob, job_id) or db.get(TrainJob, job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    return JobOut(**{c.name: getattr(job, c.name) for c in job.__table__.columns})


@app.get('/v1/jobs', response_model=list[JobOut])
def get_jobs(db: Session = Depends(get_db)):
    all_jobs = list_jobs(db)
    return [JobOut(**{c.name: getattr(j, c.name) for c in j.__table__.columns}) for j in all_jobs]


@app.post('/v1/accent-overrides')
def set_override(word: str, accented: str):
    p = Path(settings.accent_overrides_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    data[word.lower()] = accented
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'saved', 'count': len(data)}

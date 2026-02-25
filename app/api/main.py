import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import JobStatus, JobType, TTSJob, TrainJob, Voice, VoiceProfile, VoiceSample
from app.schemas.api import JobOut, PreviewRequest, ProfileOut, SimpleJobResponse, TTSRequest, TrainRequest, VoiceCreateResponse, VoiceOut
from app.services.audio.processing import ffmpeg_normalize, trim_and_loudnorm
from app.services.repository import list_jobs, list_profiles, list_voices
from app.workers.celery_app import celery_app

settings = get_settings()
app = FastAPI(title='Voice AI API')


@app.on_event('startup')
def startup() -> None:
    for p in [settings.uploads_dir, settings.voices_dir, settings.profiles_dir, settings.jobs_dir, settings.outputs_dir, settings.models_dir]:
        Path(p).mkdir(parents=True, exist_ok=True)


@app.get('/health')
def health():
    return {'status': 'ok'}


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
    job = TTSJob(type=JobType.preview, status=JobStatus.pending, input_params={'voice_id': voice_id, 'text': req.text})
    db.add(job)
    db.commit()
    celery_app.send_task('app.workers.tasks.run_preview', args=[job.id, voice_id, req.text])
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

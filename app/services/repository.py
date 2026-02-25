from sqlalchemy import select

from app.models import TTSJob, TrainJob, Voice, VoiceProfile, VoiceSample


def list_voices(db):
    return db.execute(select(Voice).order_by(Voice.created_at.desc())).scalars().all()


def get_voice(db, voice_id: str):
    return db.get(Voice, voice_id)


def get_profile(db, profile_id: str):
    return db.get(VoiceProfile, profile_id)


def list_profiles(db, voice_id: str):
    return db.execute(select(VoiceProfile).where(VoiceProfile.voice_id == voice_id)).scalars().all()


def list_jobs(db):
    tts = db.execute(select(TTSJob)).scalars().all()
    trn = db.execute(select(TrainJob)).scalars().all()
    return tts + trn

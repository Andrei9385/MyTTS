from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VoiceCreateResponse(BaseModel):
    voice_id: str
    sample_ids: list[str]


class VoiceOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime


class ProfileOut(BaseModel):
    id: str
    voice_id: str
    name: str
    status: str
    params: dict


class TTSRequest(BaseModel):
    voice_id: str
    profile_id: str | None = None
    text: str
    mode: Literal['story', 'poem'] = 'story'
    format: Literal['wav', 'mp3'] = 'wav'
    speed: float = Field(default=1.0, ge=0.5, le=1.5)
    use_accenting: bool = True
    use_user_overrides: bool = True


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    progress: int
    input_params: dict
    error_text: str | None
    output_path: str | None
    created_at: datetime
    updated_at: datetime


class PreviewRequest(BaseModel):
    text: str = 'Привет! Это тест вашего голоса.'


class TrainRequest(BaseModel):
    profile_name: str = 'default-profile'


class SimpleJobResponse(BaseModel):
    job_id: str
    status: str

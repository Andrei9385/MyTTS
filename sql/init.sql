CREATE TABLE IF NOT EXISTS voices (
    id VARCHAR PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_samples (
    id VARCHAR PRIMARY KEY,
    voice_id VARCHAR REFERENCES voices(id),
    source_path VARCHAR(1024) NOT NULL,
    normalized_path VARCHAR(1024) NOT NULL,
    duration_sec DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_profiles (
    id VARCHAR PRIMARY KEY,
    voice_id VARCHAR REFERENCES voices(id),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(32) DEFAULT 'ready',
    params JSONB DEFAULT '{}'::jsonb,
    model_path VARCHAR(1024),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tts_jobs (
    id VARCHAR PRIMARY KEY,
    type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER DEFAULT 0,
    input_params JSONB DEFAULT '{}'::jsonb,
    error_text TEXT,
    output_path VARCHAR(1024),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS train_jobs (
    id VARCHAR PRIMARY KEY,
    type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress INTEGER DEFAULT 0,
    input_params JSONB DEFAULT '{}'::jsonb,
    error_text TEXT,
    output_path VARCHAR(1024),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id VARCHAR PRIMARY KEY,
    job_id VARCHAR NOT NULL,
    kind VARCHAR(64) NOT NULL,
    path VARCHAR(1024) NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ui_sessions (
    id VARCHAR PRIMARY KEY,
    current_step INTEGER DEFAULT 1,
    selected_voice_id VARCHAR,
    selected_profile_id VARCHAR,
    preview_text_draft TEXT DEFAULT 'Привет! Это быстрый тест.',
    tts_text_draft TEXT DEFAULT '',
    mode VARCHAR(16) DEFAULT 'story',
    format VARCHAR(8) DEFAULT 'wav',
    speed DOUBLE PRECISION DEFAULT 1.0,
    use_accenting BOOLEAN DEFAULT TRUE,
    use_user_overrides BOOLEAN DEFAULT TRUE,
    active_preview_job_id VARCHAR,
    active_train_job_id VARCHAR,
    active_tts_job_id VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

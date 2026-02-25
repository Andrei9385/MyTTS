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

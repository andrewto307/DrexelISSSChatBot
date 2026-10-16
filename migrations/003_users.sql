CREATE TABLE users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email text NOT NULL UNIQUE CHECK (email = lower(email)),
    password_hash text NOT NULL,
    verified_at timestamptz,
    session_version integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);

CREATE TABLE email_codes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN ('verify', 'reset')),
    code_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX email_codes_user_idx ON email_codes (user_id, purpose, created_at);

ALTER TABLE conversations ADD COLUMN user_id bigint REFERENCES users (id) ON DELETE CASCADE;

CREATE INDEX conversations_user_idx ON conversations (user_id);

CREATE TABLE daily_usage (
    user_id bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    day date NOT NULL,
    questions integer NOT NULL DEFAULT 0,
    cost_usd numeric(10, 6) NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE INDEX daily_usage_day_idx ON daily_usage (day);

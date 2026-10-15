CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    client_ip_hash text
);

CREATE TABLE messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    position integer NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content json NOT NULL,
    in_history boolean NOT NULL DEFAULT true,
    question_text text,
    search_queries jsonb,
    sources jsonb,
    stop_reason text,
    usage jsonb,
    cost_usd numeric(10, 6),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, position)
);

CREATE INDEX messages_created_at_idx ON messages (created_at);

CREATE TABLE feedback (
    message_id bigint PRIMARY KEY REFERENCES messages (id) ON DELETE CASCADE,
    rating smallint NOT NULL CHECK (rating IN (-1, 1)),
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);

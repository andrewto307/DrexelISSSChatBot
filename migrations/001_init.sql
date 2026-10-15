CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS pages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url text NOT NULL UNIQUE,
    title text NOT NULL,
    page_type text NOT NULL CHECK (page_type IN ('page', 'announcement', 'document')),
    content_type text NOT NULL,
    announcement_date date,
    text text NOT NULL,
    content_hash text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'gone')),
    first_seen timestamptz NOT NULL DEFAULT now(),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    changed_at timestamptz NOT NULL DEFAULT now(),
    indexed_hash text,
    indexed_model text
);

CREATE TABLE IF NOT EXISTS links (
    from_page_id bigint NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    url text NOT NULL,
    anchor_text text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('isss_page', 'isss_document', 'drexel_other', 'external', 'login_only')),
    PRIMARY KEY (from_page_id, url)
);

CREATE TABLE IF NOT EXISTS chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    page_id bigint NOT NULL REFERENCES pages (id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    heading_path text NOT NULL,
    content text NOT NULL,
    token_count integer NOT NULL,
    embedding vector(1024) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', heading_path || ' ' || content)) STORED,
    UNIQUE (page_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

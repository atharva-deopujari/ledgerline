-- The only schema source. Applied at boot, every boot, so every statement is IF NOT EXISTS.
-- No migration tool until there is a second schema version to migrate between; the upgrade path
-- is alembic, and the day a column changes type is the day to add it.
--
-- Money is text holding the Decimal string. numeric would be correct too, but every driver on the
-- way in and out of it is one float coercion away from losing a paisa, and every figure here is
-- money someone is counting on.

CREATE TABLE IF NOT EXISTS users (
    phone        text PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    forgotten_at timestamptz
);

-- Slim on purpose: Langfuse holds every turn and tool call, the JSON recording holds the
-- transcript. This row is what ties the three together, and the only thing queried by our keys.
CREATE TABLE IF NOT EXISTS sessions (
    id                text PRIMARY KEY,
    -- Nullable on purpose: forgetting a person nulls this and keeps the row, so the call itself
    -- stays countable while nothing about it points at them any more.
    phone             text REFERENCES users (phone),
    started_at        timestamptz NOT NULL DEFAULT now(),
    ended_at          timestamptz,
    ended_by          text,
    prompt_version    text,
    langfuse_trace_id text,
    recording_path    text
);

CREATE INDEX IF NOT EXISTS sessions_phone_started_at ON sessions (phone, started_at DESC);

-- One row per stated fact. A change supersedes rather than overwrites, so "rent 11,000 then
-- 12,000" is two rows and the history is readable on the review screen.
CREATE TABLE IF NOT EXISTS profile_facts (
    id                bigserial PRIMARY KEY,
    phone             text NOT NULL REFERENCES users (phone),
    kind              text NOT NULL,
    name              text NOT NULL,
    field             text NOT NULL,
    value             text,
    certainty         text,
    source_session_id text REFERENCES sessions (id),
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    last_confirmed_at timestamptz NOT NULL DEFAULT now(),
    superseded_by     bigint REFERENCES profile_facts (id)
);

-- The active facts for a caller: the lookup on the call path, so it has its own index.
CREATE INDEX IF NOT EXISTS profile_facts_active
    ON profile_facts (phone) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS profile_notes (
    id                  bigserial PRIMARY KEY,
    phone               text NOT NULL REFERENCES users (phone),
    category            text NOT NULL,
    text                text NOT NULL,
    evidence_session_id text REFERENCES sessions (id),
    evidence_turn       integer,
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    superseded_by       bigint REFERENCES profile_notes (id)
);

CREATE INDEX IF NOT EXISTS profile_notes_active
    ON profile_notes (phone) WHERE superseded_by IS NULL;

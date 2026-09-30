CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE provisions (
    ref            text PRIMARY KEY,          -- 'AI-verordening:art_6', 'AI-verordening:art_4a',
                                              -- split parts: 'AVG:art_9#2'
    doc            text NOT NULL,             -- 'AI-verordening' | 'AVG' | 'CRA' | 'Omnibus'
    kind           text NOT NULL CHECK (kind IN ('article', 'recital', 'annex')),
    label          text NOT NULL,             -- '6', '4a', 'III'
    parent_ref     text NOT NULL,             -- ref without part suffix
    part_no        int  NOT NULL DEFAULT 1,
    part_count     int  NOT NULL DEFAULT 1,
    title          text,
    chapter        text,                      -- display line, e.g. 'Hoofdstuk III: AI-SYSTEMEN MET EEN HOOG RISICO'
    section        text,                      -- display line, e.g. 'Afdeling 1: Classificatie van ...'
    part_label     text,                      -- split provisions only, e.g. 'leden 3 tot en met 5'
    header         text NOT NULL,             -- full lineage header, part of embedded and displayed text
    body           text NOT NULL,             -- legal text, amendment markers stripped
    token_estimate int  NOT NULL,
    amended_by     text[] NOT NULL DEFAULT '{}',   -- e.g. {'Omnibus'}, from amendment markers (running state, see below)
    embedding      vector(2000) NOT NULL      -- fixed by this migration, must match EMBEDDING_DIMENSIONS
);
CREATE INDEX provisions_parent_idx ON provisions (parent_ref);

CREATE TABLE index_meta (
    id               boolean PRIMARY KEY DEFAULT true CHECK (id),   -- single row
    embedding_model  text NOT NULL,
    dimension        int  NOT NULL,
    serving_profile  text NOT NULL,
    corpus_snapshot  date NOT NULL,
    corpus_hash      text NOT NULL,
    ingested_at      timestamptz NOT NULL
);

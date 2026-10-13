-- Authoritative metadata only. Files are the content source of truth;
-- Qdrant ingestion and version activation are separate application operations.
CREATE TABLE knowledge_document (
  document_id UUID PRIMARY KEY,
  document_code TEXT NOT NULL,
  document_version BIGINT NOT NULL CHECK(document_version > 0),
  title TEXT NOT NULL,
  source_uri TEXT,
  access_class TEXT NOT NULL CHECK(access_class = 'FACTORY_INTERNAL'),
  active BOOLEAN NOT NULL,
  content_hash TEXT NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(document_code, document_version)
);

CREATE UNIQUE INDEX knowledge_document_one_active_version
  ON knowledge_document(document_code) WHERE active;

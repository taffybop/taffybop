-- PX1-02: private owner-scoped records. DTO validation remains in Python;
-- relationships and immutable capture boundaries are enforced here as well.
CREATE SCHEMA IF NOT EXISTS product;

CREATE TABLE product.owners (
    owner_key text PRIMARY KEY CHECK (length(owner_key) BETWEEN 1 AND 200)
);

CREATE TABLE product.documents (
    id uuid PRIMARY KEY,
    owner_key text NOT NULL REFERENCES product.owners(owner_key),
    display_name text NOT NULL CHECK (
        length(display_name) BETWEEN 1 AND 180 AND display_name NOT IN ('.', '..')
        AND position('/' IN display_name) = 0 AND position(E'\\' IN display_name) = 0
        AND position('"' IN display_name) = 0 AND display_name !~ '[[:cntrl:]]'
    ),
    page_count integer NOT NULL CHECK (page_count BETWEEN 1 AND 10),
    created_at timestamptz NOT NULL,
    expires_at timestamptz,
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'deleted', 'expired')),
    deleted_at timestamptz,
    source_artifact_id uuid NOT NULL,
    UNIQUE (owner_key, id),
    CHECK ((state = 'deleted') = (deleted_at IS NOT NULL)),
    CHECK (state <> 'expired' OR expires_at IS NOT NULL),
    CHECK (expires_at IS NULL OR expires_at >= created_at),
    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

CREATE TABLE product.artifacts (
    id uuid PRIMARY KEY,
    owner_key text NOT NULL,
    document_id uuid NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL CHECK (
        media_type IN ('application/pdf', 'image/png', 'image/jpeg', 'application/json')
    ),
    UNIQUE (owner_key, document_id, id),
    FOREIGN KEY (owner_key, document_id) REFERENCES product.documents(owner_key, id)
        DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE product.documents ADD CONSTRAINT document_source_fk
    FOREIGN KEY (owner_key, id, source_artifact_id)
    REFERENCES product.artifacts(owner_key, document_id, id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE product.jobs (
    id uuid PRIMARY KEY,
    owner_key text NOT NULL,
    document_id uuid NOT NULL,
    idempotency_key text NOT NULL CHECK (
        octet_length(idempotency_key) BETWEEN 1 AND 128
        AND idempotency_key ~ '^[ -~]+$'
    ),
    result_id uuid,
    raw_artifact_id uuid,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    UNIQUE (owner_key, idempotency_key),
    UNIQUE (owner_key, document_id, id),
    FOREIGN KEY (owner_key, document_id) REFERENCES product.documents(owner_key, id),
    FOREIGN KEY (owner_key, document_id, raw_artifact_id)
        REFERENCES product.artifacts(owner_key, document_id, id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK ((payload->>'id') IS NOT DISTINCT FROM id::text),
    CHECK ((payload->>'document_id') IS NOT DISTINCT FROM document_id::text),
    CHECK ((payload->>'result_id') IS NOT DISTINCT FROM result_id::text),
    CHECK ((payload->'raw_response'->>'id') IS NOT DISTINCT FROM raw_artifact_id::text),
    CHECK ((payload->>'status') IN (
        'queued', 'submitting', 'submission_unknown', 'running', 'succeeded',
        'failed', 'cancel_requested', 'cancelled'
    )),
    CHECK (((payload->>'status') = 'succeeded') = (result_id IS NOT NULL))
);

CREATE TABLE product.parse_results (
    id uuid PRIMARY KEY,
    owner_key text NOT NULL,
    document_id uuid NOT NULL,
    job_id uuid NOT NULL UNIQUE,
    raw_artifact_id uuid NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    UNIQUE (owner_key, document_id, job_id, id),
    FOREIGN KEY (owner_key, document_id, job_id)
        REFERENCES product.jobs(owner_key, document_id, id),
    FOREIGN KEY (owner_key, document_id, raw_artifact_id)
        REFERENCES product.artifacts(owner_key, document_id, id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK ((payload->>'id') IS NOT DISTINCT FROM id::text),
    CHECK ((payload->>'document_id') IS NOT DISTINCT FROM document_id::text),
    CHECK ((payload->>'job_id') IS NOT DISTINCT FROM job_id::text),
    CHECK ((payload->'raw'->>'id') IS NOT DISTINCT FROM raw_artifact_id::text)
);
ALTER TABLE product.jobs ADD CONSTRAINT job_result_fk
    FOREIGN KEY (owner_key, document_id, id, result_id)
    REFERENCES product.parse_results(owner_key, document_id, job_id, id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX documents_owner_history ON product.documents(owner_key, created_at DESC, id DESC);
CREATE INDEX jobs_pending ON product.jobs((payload->>'status'), (payload->>'created_at'), id);

CREATE FUNCTION product.protect_capture() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME IN ('artifacts', 'parse_results') THEN
        RAISE EXCEPTION '% captures are immutable', TG_TABLE_NAME USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'records must be revoked, not deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'documents' THEN
        IF ROW(NEW.id, NEW.owner_key, NEW.display_name, NEW.page_count,
               NEW.created_at, NEW.source_artifact_id)
           IS DISTINCT FROM
           ROW(OLD.id, OLD.owner_key, OLD.display_name, OLD.page_count,
               OLD.created_at, OLD.source_artifact_id) THEN
            RAISE EXCEPTION 'document identity and source are immutable' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF ROW(NEW.id, NEW.owner_key, NEW.document_id, NEW.idempotency_key,
               NEW.payload->'settings', NEW.payload->'created_at', NEW.payload->'attempt',
               NEW.payload->'schema_version', NEW.payload->'stage')
           IS DISTINCT FROM
           ROW(OLD.id, OLD.owner_key, OLD.document_id, OLD.idempotency_key,
               OLD.payload->'settings', OLD.payload->'created_at', OLD.payload->'attempt',
               OLD.payload->'schema_version', OLD.payload->'stage') THEN
            RAISE EXCEPTION 'job identity and settings are immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.payload->>'status' IN ('succeeded', 'failed', 'cancelled')
           AND (NEW.payload - 'usage' - 'updated_at') IS DISTINCT FROM (OLD.payload - 'usage' - 'updated_at') THEN
            RAISE EXCEPTION 'terminal job capture is immutable except usage reconciliation'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE ON product.artifacts
    FOR EACH ROW EXECUTE FUNCTION product.protect_capture();
CREATE TRIGGER results_immutable BEFORE UPDATE OR DELETE ON product.parse_results
    FOR EACH ROW EXECUTE FUNCTION product.protect_capture();
CREATE TRIGGER documents_identity BEFORE UPDATE OR DELETE ON product.documents
    FOR EACH ROW EXECUTE FUNCTION product.protect_capture();
CREATE TRIGGER jobs_identity BEFORE UPDATE OR DELETE ON product.jobs
    FOR EACH ROW EXECUTE FUNCTION product.protect_capture();

CREATE FUNCTION product.check_document_source() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    d product.documents%ROWTYPE;
    a product.artifacts%ROWTYPE;
BEGIN
    SELECT * INTO d FROM product.documents WHERE id = NEW.id;
    SELECT * INTO a FROM product.artifacts WHERE id = d.source_artifact_id;
    IF NOT FOUND OR a.owner_key IS DISTINCT FROM d.owner_key
       OR a.document_id IS DISTINCT FROM d.id
       OR a.media_type = 'application/json' OR a.size_bytes NOT BETWEEN 1 AND 10485760
       OR (a.media_type <> 'application/pdf' AND d.page_count <> 1) THEN
        RAISE EXCEPTION 'invalid document source artifact' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER document_source_valid AFTER INSERT OR UPDATE ON product.documents
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product.check_document_source();

CREATE FUNCTION product.check_parse_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    j product.jobs%ROWTYPE;
    r product.parse_results%ROWTYPE;
    a product.artifacts%ROWTYPE;
    reference jsonb;
BEGIN
    IF TG_TABLE_NAME = 'jobs' THEN
        SELECT * INTO j FROM product.jobs WHERE id = NEW.id;
    ELSE
        SELECT * INTO j FROM product.jobs WHERE id = NEW.job_id;
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'parse capture requires its job' USING ERRCODE = '23514';
    END IF;
    IF j.raw_artifact_id IS NOT NULL THEN
        SELECT * INTO a FROM product.artifacts WHERE id = j.raw_artifact_id;
        reference := jsonb_build_object('id', a.id, 'sha256', a.sha256,
            'size_bytes', a.size_bytes, 'media_type', a.media_type);
        IF NOT FOUND OR a.owner_key IS DISTINCT FROM j.owner_key
           OR a.document_id IS DISTINCT FROM j.document_id
           OR a.media_type <> 'application/json' OR a.size_bytes = 0
           OR reference IS DISTINCT FROM j.payload->'raw_response'
           OR j.payload->>'status' NOT IN ('succeeded', 'failed', 'cancelled') THEN
            RAISE EXCEPTION 'invalid terminal raw artifact' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT * INTO r FROM product.parse_results WHERE job_id = j.id;
    IF j.payload->>'status' = 'succeeded' THEN
        IF NOT FOUND OR j.result_id IS DISTINCT FROM r.id
           OR j.raw_artifact_id IS DISTINCT FROM r.raw_artifact_id
           OR j.payload->'settings' IS DISTINCT FROM r.payload->'settings'
           OR r.payload->'raw' IS DISTINCT FROM j.payload->'raw_response' THEN
            RAISE EXCEPTION 'successful job and result capture must agree'
                USING ERRCODE = '23514';
        END IF;
    ELSIF FOUND THEN
        RAISE EXCEPTION 'only successful jobs have parse results' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER job_capture_valid AFTER INSERT OR UPDATE ON product.jobs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product.check_parse_capture();
CREATE CONSTRAINT TRIGGER result_capture_valid AFTER INSERT ON product.parse_results
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product.check_parse_capture();

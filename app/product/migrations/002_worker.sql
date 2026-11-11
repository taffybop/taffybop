-- PX1-03: one conservative full-job provider slot and fenced worker claims.
CREATE TABLE product.worker_control (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    admission_paused boolean NOT NULL DEFAULT false,
    pause_reason text
);
INSERT INTO product.worker_control(singleton) VALUES (true);

CREATE TABLE product.worker_executions (
    job_id uuid PRIMARY KEY REFERENCES product.jobs(id),
    provider_job_id text UNIQUE CHECK (length(provider_job_id) BETWEEN 1 AND 200),
    capacity_slot integer CHECK (capacity_slot = 1),
    claim_token uuid,
    lease_until timestamptz,
    next_poll_at timestamptz NOT NULL DEFAULT now(),
    poll_failures integer NOT NULL DEFAULT 0 CHECK (poll_failures >= 0),
    last_poll_error text,
    admitted_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((claim_token IS NULL) = (lease_until IS NULL))
);
CREATE UNIQUE INDEX worker_one_global_slot ON product.worker_executions(capacity_slot)
    WHERE capacity_slot IS NOT NULL;

CREATE FUNCTION product.protect_worker_execution() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'worker admission history cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF NEW.job_id IS DISTINCT FROM OLD.job_id OR NEW.admitted_at IS DISTINCT FROM OLD.admitted_at
       OR (OLD.provider_job_id IS NOT NULL AND NEW.provider_job_id IS DISTINCT FROM OLD.provider_job_id)
       OR (OLD.capacity_slot IS NULL AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'worker identity and terminal admission are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER worker_execution_identity BEFORE UPDATE OR DELETE ON product.worker_executions
    FOR EACH ROW EXECUTE FUNCTION product.protect_worker_execution();

CREATE FUNCTION product.check_worker_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    e product.worker_executions%ROWTYPE;
    j product.jobs%ROWTYPE;
    identity uuid;
BEGIN
    IF TG_TABLE_NAME = 'jobs' THEN identity := NEW.id; ELSE identity := NEW.job_id; END IF;
    SELECT * INTO e FROM product.worker_executions WHERE job_id = identity;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT * INTO j FROM product.jobs WHERE id = identity;
    IF (e.capacity_slot IS NULL) IS DISTINCT FROM (j.payload->>'status' IN ('succeeded','failed','cancelled'))
       OR (j.payload->>'status' IN ('running','succeeded') AND e.provider_job_id IS NULL)
       OR j.payload->>'status' = 'queued'
       OR (e.capacity_slot IS NULL AND e.claim_token IS NOT NULL) THEN
        RAISE EXCEPTION 'worker slot and durable job state disagree' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER worker_capture_valid AFTER INSERT OR UPDATE ON product.worker_executions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product.check_worker_capture();
CREATE CONSTRAINT TRIGGER worker_job_valid AFTER INSERT OR UPDATE ON product.jobs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION product.check_worker_capture();

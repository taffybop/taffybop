-- PX1-03: finite, immutable allowances for explicitly simulated local runs.
-- Monetary values are authored simulation bounds, never live price estimates.
CREATE TABLE product.test_allowances (
    id uuid PRIMARY KEY,
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[a-f0-9]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    max_jobs integer NOT NULL CHECK (max_jobs BETWEEN 1 AND 100),
    max_pages integer NOT NULL CHECK (max_pages BETWEEN 1 AND 1000),
    credit_limit numeric NOT NULL CHECK (credit_limit > 0 AND credit_limit < 'Infinity'::numeric),
    usd_limit numeric NOT NULL CHECK (usd_limit > 0 AND usd_limit < 'Infinity'::numeric),
    credits_per_page numeric NOT NULL CHECK (credits_per_page > 0 AND credits_per_page < 'Infinity'::numeric),
    usd_per_credit numeric NOT NULL CHECK (usd_per_credit > 0 AND usd_per_credit < 'Infinity'::numeric),
    expires_at timestamptz NOT NULL CHECK (isfinite(expires_at)),
    CHECK ((payload->>'id') IS NOT DISTINCT FROM id::text),
    CHECK ((payload->>'provider') IS NOT DISTINCT FROM 'simulated'),
    CHECK (jsonb_typeof(payload->'job_ids') IS NOT DISTINCT FROM 'array'),
    CHECK (jsonb_array_length(payload->'job_ids') BETWEEN 1 AND 100),
    CHECK ((payload->>'max_jobs')::integer IS NOT DISTINCT FROM max_jobs),
    CHECK ((payload->>'max_pages')::integer IS NOT DISTINCT FROM max_pages),
    CHECK ((payload->>'credit_limit')::numeric IS NOT DISTINCT FROM credit_limit),
    CHECK ((payload->>'usd_limit')::numeric IS NOT DISTINCT FROM usd_limit),
    CHECK ((payload->>'credits_per_page')::numeric IS NOT DISTINCT FROM credits_per_page),
    CHECK ((payload->>'usd_per_credit')::numeric IS NOT DISTINCT FROM usd_per_credit),
    CHECK ((payload->>'expires_at')::timestamptz IS NOT DISTINCT FROM expires_at)
);

CREATE TABLE product.test_allowance_reservations (
    job_id uuid PRIMARY KEY REFERENCES product.worker_executions(job_id)
        DEFERRABLE INITIALLY DEFERRED,
    allowance_id uuid NOT NULL REFERENCES product.test_allowances(id),
    reserved_pages integer NOT NULL CHECK (reserved_pages BETWEEN 1 AND 10),
    reserved_credits numeric NOT NULL CHECK (reserved_credits > 0 AND reserved_credits < 'Infinity'::numeric),
    reserved_usd numeric NOT NULL CHECK (reserved_usd > 0 AND reserved_usd < 'Infinity'::numeric),
    reserved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX test_allowance_consumption ON product.test_allowance_reservations(allowance_id);

CREATE FUNCTION product.protect_test_allowance() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'test allowances and reservations are immutable' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER test_allowances_immutable BEFORE UPDATE OR DELETE ON product.test_allowances
    FOR EACH ROW EXECUTE FUNCTION product.protect_test_allowance();
CREATE TRIGGER test_allowance_reservations_immutable BEFORE UPDATE OR DELETE ON product.test_allowance_reservations
    FOR EACH ROW EXECUTE FUNCTION product.protect_test_allowance();

CREATE FUNCTION product.check_test_reservation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    a product.test_allowances%ROWTYPE;
    j product.jobs%ROWTYPE;
    total record;
BEGIN
    PERFORM pg_advisory_xact_lock(729041, 103);
    SELECT * INTO a FROM product.test_allowances WHERE id=NEW.allowance_id;
    SELECT * INTO j FROM product.jobs WHERE id=NEW.job_id;
    IF a.id IS NULL OR j.id IS NULL OR a.expires_at <= clock_timestamp()
       OR NOT (a.payload->'job_ids' @> jsonb_build_array(NEW.job_id::text))
       OR j.payload->'settings' IS DISTINCT FROM a.payload->'settings'
       OR j.payload->>'status' IS DISTINCT FROM 'queued'
       OR NEW.reserved_pages IS DISTINCT FROM (j.payload->'settings'->>'max_pages')::integer
       OR NEW.reserved_credits IS DISTINCT FROM NEW.reserved_pages * a.credits_per_page
       OR NEW.reserved_usd IS DISTINCT FROM NEW.reserved_credits * a.usd_per_credit THEN
        RAISE EXCEPTION 'test reservation does not match its allowance and queued job' USING ERRCODE = '23514';
    END IF;
    SELECT count(*) AS jobs,coalesce(sum(reserved_pages),0) AS pages,
        coalesce(sum(reserved_credits),0) AS credits,coalesce(sum(reserved_usd),0) AS usd
        INTO total FROM product.test_allowance_reservations WHERE allowance_id=NEW.allowance_id;
    IF total.jobs + 1 > a.max_jobs OR total.pages + NEW.reserved_pages > a.max_pages
       OR total.credits + NEW.reserved_credits > a.credit_limit
       OR total.usd + NEW.reserved_usd > a.usd_limit THEN
        RAISE EXCEPTION 'finite test allowance exhausted' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER test_reservation_valid BEFORE INSERT ON product.test_allowance_reservations
    FOR EACH ROW EXECUTE FUNCTION product.check_test_reservation();

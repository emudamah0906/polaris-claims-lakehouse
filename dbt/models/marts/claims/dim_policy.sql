-- One row per policy: the current version only. Full history (SCD2) is built
-- in Silver with MERGE once Stage 3 exists (ADR-0004).

select
    policy_id,
    customer_id,
    product_type,
    effective_date,
    expiry_date,
    annual_premium,
    coverage_limit,
    status,
    updated_at
from {{ ref('stg_policies') }}

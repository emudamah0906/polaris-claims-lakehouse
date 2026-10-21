-- Reconciliation 1: no rows lost or added between RAW and staging.
-- Staging keeps one row per key, so this compares distinct keys in RAW with
-- rows in staging. Returns a row for each table that disagrees; 0 rows = pass.

with counts as (
    select 'customers' as table_name,
           (select count(distinct customer_id) from {{ source('raw', 'customers') }}) as raw_keys,
           (select count(*) from {{ ref('stg_customers') }})                          as staging_rows
    union all
    select 'policies',
           (select count(distinct policy_id) from {{ source('raw', 'policies') }}),
           (select count(*) from {{ ref('stg_policies') }})
    union all
    select 'claims',
           (select count(distinct claim_id) from {{ source('raw', 'claims') }}),
           (select count(*) from {{ ref('stg_claims') }})
    union all
    select 'claim_payments',
           (select count(distinct payment_id) from {{ source('raw', 'claim_payments') }}),
           (select count(*) from {{ ref('stg_claim_payments') }})
)

select * from counts where raw_keys != staging_rows

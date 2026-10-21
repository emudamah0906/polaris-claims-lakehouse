-- Reconciliation 2: the money is the same at every layer.
-- RAW payments total = payments fact total = finance mart total = sum of
-- total_paid on fct_claims. Any difference over half a cent fails.

with totals as (
    select
        (select sum(try_to_decimal(payment_amount, 18, 2))
           from {{ source('raw', 'claim_payments') }})            as raw_total,
        (select sum(payment_amount) from {{ ref('fct_claim_payments') }})          as fact_total,
        (select sum(total_paid) from {{ ref('finance_claims_paid_monthly') }})     as finance_total,
        (select sum(total_paid) from {{ ref('fct_claims') }})                      as claims_total
)

select *
from totals
where abs(raw_total - fact_total) > 0.005
   or abs(raw_total - finance_total) > 0.005
   or abs(raw_total - claims_total) > 0.005

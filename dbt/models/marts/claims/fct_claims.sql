-- One row per claim, with what's been paid on it and how fast it was reported.

with claims as (
    select * from {{ ref('stg_claims') }}
),

paid as (
    select * from {{ ref('int_claim_payment_totals') }}
),

policies as (
    select policy_id, effective_date from {{ ref('stg_policies') }}
)

select
    c.claim_id,
    c.claim_number,
    c.policy_id,
    c.customer_id,
    c.product_type,
    c.claim_type,
    c.adjuster_id,
    c.status,
    c.loss_date,
    c.report_date,
    datediff('day', c.loss_date, c.report_date)                          as report_lag_days,
    -- Late FNOL: reported more than the window after the loss (ADR-0005)
    datediff('day', c.loss_date, c.report_date)
        > {{ var('fnol_late_arrival_window_days') }}                     as is_late_fnol,
    datediff('day', p.effective_date, c.loss_date)                       as days_policy_start_to_loss,
    c.claim_amount,
    coalesce(paid.total_paid, 0)                                         as total_paid,
    coalesce(paid.paid_indemnity, 0)                                     as paid_indemnity,
    coalesce(paid.paid_expense, 0)                                       as paid_expense,
    coalesce(paid.paid_recovery, 0)                                      as paid_recovery,
    coalesce(paid.payment_count, 0)                                      as payment_count,
    paid.first_payment_date,
    paid.last_payment_date,
    c.is_fraud,
    c.fraud_score
from claims c
left join paid using (claim_id)
left join policies p using (policy_id)

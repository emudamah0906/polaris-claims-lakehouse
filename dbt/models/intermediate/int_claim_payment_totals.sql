-- Payments rolled up to one row per claim. Ephemeral: compiled into the
-- marts that use it, never built as its own object.

select
    claim_id,
    count(*)                                                        as payment_count,
    sum(payment_amount)                                             as total_paid,
    sum(iff(payment_type = 'INDEMNITY', payment_amount, 0))        as paid_indemnity,
    sum(iff(payment_type = 'EXPENSE', payment_amount, 0))          as paid_expense,
    sum(iff(payment_type = 'RECOVERY', payment_amount, 0))         as paid_recovery,
    min(payment_date)                                               as first_payment_date,
    max(payment_date)                                               as last_payment_date
from {{ ref('stg_claim_payments') }}
group by claim_id

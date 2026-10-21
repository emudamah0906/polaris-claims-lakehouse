-- Claims paid per month and product, split by payment type. The number
-- finance reconciles each month-end. Its grand total must equal the sum of
-- every payment in RAW (tests/assert_payments_reconcile.sql).

select
    payment_month,
    product_type,
    sum(iff(payment_type = 'INDEMNITY', payment_amount, 0))    as paid_indemnity,
    sum(iff(payment_type = 'EXPENSE', payment_amount, 0))      as paid_expense,
    sum(iff(payment_type = 'RECOVERY', payment_amount, 0))     as paid_recovery,
    sum(payment_amount)                                         as total_paid,
    count(*)                                                    as payment_count,
    count(distinct claim_id)                                    as claim_count
from {{ ref('fct_claim_payments') }}
group by payment_month, product_type

-- One row per payment, with the claim's product and type for slicing.

select
    pay.payment_id,
    pay.claim_id,
    c.policy_id,
    c.product_type,
    c.claim_type,
    pay.payment_type,
    pay.payment_date,
    date_trunc('month', pay.payment_date)         as payment_month,
    pay.payment_amount
from {{ ref('stg_claim_payments') }} pay
join {{ ref('stg_claims') }} c using (claim_id)

-- Business rule: a CLOSED or PAID claim's payments add up to its claim amount,
-- and OPEN or DENIED claims have no payments. Returns every claim that breaks
-- either rule.

select claim_id, status, claim_amount, total_paid, payment_count
from {{ ref('fct_claims') }}
where (status in ('CLOSED', 'PAID') and abs(total_paid - claim_amount) > 0.01)
   or (status in ('OPEN', 'DENIED') and payment_count > 0)

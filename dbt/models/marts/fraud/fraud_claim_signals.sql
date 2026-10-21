-- Claims with at least one fraud signal, for the investigations (SIU) queue.
-- Three rule-based signals plus the model score. More signals = look first.
--
-- Left out on purpose: "claim close to the coverage limit". The generated
-- claim amounts are too large (74% of claims hit 70% of their limit), so it
-- would flag nearly everything. It comes back when the generator is fixed.

with flagged as (
    select
        claim_id,
        policy_id,
        product_type,
        claim_type,
        loss_date,
        report_date,
        claim_amount,
        fraud_score,
        is_fraud,
        days_policy_start_to_loss < {{ var('fraud_recent_policy_days') }}   as sig_recent_policy,
        is_late_fnol                                                       as sig_late_fnol,
        fraud_score >= {{ var('fraud_model_score_threshold') }}            as sig_model_score
    from {{ ref('fct_claims') }}
)

select
    *,
    sig_recent_policy::int + sig_late_fnol::int + sig_model_score::int     as signal_count
from flagged
where sig_recent_policy or sig_late_fnol or sig_model_score

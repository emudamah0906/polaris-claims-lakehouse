-- One row per customer, typed, with direct PII removed.
-- Analysts can read STAGING, so SIN, full birth date, name, email, phone and
-- street address stop here. They stay in RAW, which only the loader and dbt
-- roles can read.

with source as (
    select * from {{ source('raw', 'customers') }}
    -- latest copy of each customer, in case a file is ever loaded twice
    qualify row_number() over (
        partition by customer_id order by _loaded_at desc, _file_row_number desc
    ) = 1
)

select
    customer_id,
    year(try_to_date(dob))                       as birth_year,
    city,
    province,
    left(postal_code, 3)                         as postal_fsa,  -- area only, not the full code
    try_to_timestamp_ntz(created_at)::date       as customer_since,
    try_to_timestamp_ntz(created_at)             as created_at,
    try_to_timestamp_ntz(updated_at)             as updated_at,
    _loaded_at
from source

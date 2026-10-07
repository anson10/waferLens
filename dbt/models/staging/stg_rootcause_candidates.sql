select
    candidate_id,
    excursion_id,
    window_start as window_start_at,
    window_end as window_end_at,
    signal,
    pattern,
    factor_type,
    chamber_id,
    recipe_id,
    n_through,
    low_through,
    n_population,
    n_low,
    lift,
    chi2,
    suspect_rank
from {{ source('waferlens', 'rootcause_candidates') }}

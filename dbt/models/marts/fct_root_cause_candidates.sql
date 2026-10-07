-- Grain: one row per excursion window x signal x suspect (chamber or recipe version), from
-- the commonality analysis that saw only the window. Signal 'yield' marks low-yield wafers
-- as bad (every excursion); 'pattern' marks wafers FabEye sees the excursion's pattern on
-- (spatial excursions, pattern-led). Labels for reports and whether the suspect is the
-- excursion's true cause.
select
    c.candidate_id,
    c.excursion_id,
    c.signal,
    c.pattern,
    c.factor_type,
    c.chamber_id,
    c.recipe_id,
    case
        when c.factor_type = 'chamber' then ch.chamber_label
        else r.recipe_name || ' v' || r.recipe_version
    end as suspect,
    c.suspect_rank,
    c.lift,
    c.chi2,
    c.low_through,
    c.n_through,
    c.n_low,
    c.n_population,
    (c.factor_type = 'chamber' and c.chamber_id = e.chamber_id and e.recipe_id is null)
    or (c.factor_type = 'recipe' and c.recipe_id = e.recipe_id) as is_true_cause
from {{ ref('stg_rootcause_candidates') }} as c
inner join {{ ref('stg_excursions_ground_truth') }} as e on c.excursion_id = e.excursion_id
left join {{ ref('dim_chamber') }} as ch on c.chamber_id = ch.chamber_id
left join {{ ref('dim_recipe') }} as r on c.recipe_id = r.recipe_id

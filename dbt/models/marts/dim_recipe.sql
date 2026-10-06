-- Each recipe version with the window it was in force: effective_to is the next version's
-- start on the same route step (lead), null for the version still in force.
select
    r.recipe_id,
    r.route_step_id,
    r.recipe_name,
    r.recipe_version,
    r.effective_from_at,
    lead(r.effective_from_at) over (
        partition by r.route_step_id order by r.recipe_version
    ) as effective_to_at,
    r.recipe_version = max(r.recipe_version) over (partition by r.route_step_id)
        as is_current
from {{ ref('stg_recipes') }} as r

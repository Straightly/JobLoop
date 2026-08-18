# Rubric Tuning Loop

This loop is intentionally repeatable.

The first goal is not to discover the perfect weights.
The first goal is to produce comparative outputs that make it easy to decide what kind of shortlist is actually useful.

## One Tuning Cycle

1. Score the same normalized job batch with all current weight profiles.
2. Generate one shortlist per profile.
3. Generate one comparison view that shows:
   - jobs that consistently rank high
   - jobs that only rise under one profile
   - jobs that collapse when gap risk is emphasized
4. Review the outputs and ask:
   - which list feels most honest?
   - which list feels most useful?
   - which jobs look wrongly promoted?
   - which jobs look wrongly suppressed?
5. Adjust the weight profiles.
6. Rerun the same batch.

## What To Learn From Each Cycle

### If the shortlist looks too cautious

- reduce `gap_risk`
- increase `energy_interest`
- increase `story_fit`

### If the shortlist looks too optimistic

- increase `gap_risk`
- increase `background_fit`
- reduce `energy_interest`

### If the shortlist feels technically right but personally wrong

- increase `energy_interest`

### If the shortlist contains roles that are hard to defend honestly

- increase `story_fit`
- increase `gap_risk`

## Output Expectations

Each comparative run should produce:

- one ranked list per profile
- a merged comparison report
- notes on why a role moved up or down under different profiles
- a provisional statement of which profile currently seems best

## Locking Rule

Do not treat the profile as final.

At most, treat one profile as the current working default until:

- another tuning cycle proves it wrong, or
- the user deliberately changes the preference

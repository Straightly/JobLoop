# Job Posting Schema

Use this schema to normalize each posting into a comparable record.

## Core Fields

- `source`: Amazon | LinkedIn | other
- `job_id`: source job id if visible
- `title`
- `company`
- `team_org`
- `location`
- `work_model`: remote | hybrid | onsite | unknown
- `url`
- `date_captured`

## Qualifications

- `required_qualifications`
- `preferred_qualifications`
- `hard_requirements`
- `soft_preferences`

## Role Classification

- `role_family_guess`
  - applied scientist / research-heavy
  - applied AI solutions
  - agentic AI / LLM applications
  - ML platform / evaluation / infrastructure
  - unclear
- `seniority_guess`
- `customer_facing_signal`
- `research_signal`
- `model_training_signal`
- `orchestration_signal`
- `evaluation_signal`

## Fit Assessment

- `background_fit`
- `story_fit`
- `gap_risk`
- `energy_interest`
- `access_network_path`
- `overall_recommendation`
  - apply
  - maybe
  - skip

## Notes

- `top_strengths_for_this_role`
- `main_concerns_for_this_role`
- `rejection_reasons`
- `ranking_notes`

## Suggested Markdown Shape

```md
# <title>

- Source:
- Job ID:
- URL:
- Team / Org:
- Location:
- Captured:

## Required Qualifications

-

## Preferred Qualifications

-

## Role Classification

- Role family:
- Seniority:
- Research signal:
- Model-training signal:
- Customer-facing signal:
- Orchestration / evaluation signal:

## Fit Assessment

- Background fit:
- Story fit:
- Gap risk:
- Interest:
- Access / network path:
- Recommendation:

## Notes

- Top strengths:
- Main concerns:
- Ranking notes:
```

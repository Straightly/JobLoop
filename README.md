# JobLoop

An agent which loops to work with you till you find a job.

Every Monday it searches for roles, scores them against your profile, prepares the strongest one far
enough that finishing the application is short work — and then you tune it. The tuning is the point: the
search criteria, rubric, and weights are a small model you train by hand, week over week.

**Status:** early. Scaffold and startup validation only.

## Requirements

Python 3.10 or newer. That's it.

JobLoop's core has **no third-party runtime dependencies** — it runs on the standard library alone. No
virtualenv, no package manager, no interpreter pinning, nothing to install before it works. This is a
design rule, not an accident: a dependency gets added only when the standard library genuinely cannot do
the job, and the reason is recorded in `pyproject.toml`.

`pandoc` is needed later, for rendering tailored resumes to `.docx`/`.pdf`. Not yet.

## Setup

```bash
git clone git@github.com:Straightly/JobLoop.git
cd JobLoop

cp .env.example .env      # then fill it in
python3 -m jobloop doctor
```

`doctor` validates that every root resolves and every credential is loadable. Run it first, and run it
again after moving anything.

To run the tests you need `pytest`, the one dev-only dependency:

```bash
pip install pytest
python3 -m pytest -q
```

## Configuration

### Three roots

JobLoop keeps three directories apart, each with a different job:

| Root | Default | Holds | Version controlled |
|---|---|---|---|
| **CODE** | `~/Projects/JobLoop` | this repo | yes, public |
| **CAREER** | `~/Projects/attention/career` | your artifacts **and all agent config** | yes, privately |
| **DATA** | `~/Data/JobLoop` | generated output only | no |

The test for where a file belongs: **if you typed it, it isn't DATA.** Anything you author — profile,
search criteria, rubric, weights, ledgers — lives in CAREER and gets version history. Anything the agent
produces — fetched postings, scores, reports, logs, prepared packets — lives in DATA and is disposable.

Override any root with `JOBLOOP_CODE_ROOT`, `JOBLOOP_CAREER_ROOT`, `JOBLOOP_DATA_ROOT`. No path is
hardcoded; moving a root does not break the agent.

### Credentials

Resolution order, most specific first:

1. real environment variables
2. `$JOBLOOP_ENV_FILE`
3. `<CODE_ROOT>/.env`
4. `~/.config/jobloop/env`

Real environment variables always win; the file never clobbers something already exported.

> **Why the process reads the file itself:** scheduled jobs do not inherit your shell environment. A key
> exported in `.zshrc` works perfectly when you test by hand and is simply absent when the scheduler runs
> it. Reading the file directly removes that failure mode.

Never commit `.env`.

## Lanes

A **lane** is a search intent — not a company and not a site. One employer can justify several lanes, and
one job board can host many.

**Lanes are fully isolated.** Each owns its fetch and normalize code outright, plus its own criteria,
rubric, weights, and ledger. Lanes never import from each other, and there is no shared adapter layer: two
lanes hitting the same site each carry their own copy of the fetch code.

That duplication is deliberate. The scarce resources are your attention and the blast radius of a change,
not lines of code. A shared adapter becomes a coupling point the first time one intent needs a parameter
another doesn't — and from then on, a change made for one lane can quietly break another. Isolation means
tuning a lane can only ever affect that lane.

## Design notes

- **Retry only what has a real chance of succeeding.** Transient failures (429, 5xx, timeouts) retry with
  backoff. Deterministic ones (rejected credentials, 404, schema mismatch) fail immediately. A blind retry
  of a rejected key spends time and money to reach the same answer.
- **Failure is a result.** A run that dies partway checkpoints per stage and reports what happened, rather
  than pretending nothing ran.
- **The agent never submits anything.** It prepares; you decide.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.

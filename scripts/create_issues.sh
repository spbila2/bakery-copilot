#!/usr/bin/env bash
# Create the OPEN tickets from docs/tickets.md as GitHub Issues with a milestone and labels.
# Run once, from the repo root, after `gh auth login`. Re-running creates duplicates, so run it once.
set -euo pipefail

for label in feature bug chore; do gh label create "$label" --force >/dev/null 2>&1 || true; done
MS="Next: evals and deploy"
gh api -X POST repos/:owner/:repo/milestones -f title="$MS" >/dev/null 2>&1 || true

create() { # label, title, body
  gh issue create --milestone "$MS" --label "$1" --title "$2" --body "Done when: $3" >/dev/null && echo "created: $2"
}

create chore "Run the evals on the real model" "python -m evals.run --judge passes at least 80% of the 16 cases; the pass rate is pasted in a PR and any failing case becomes a prompt fix."
create chore "Deploy to Railway" "the web and digest services run from this repository; /health returns 200 on the deployed URL; the seed report line shows 76 / 29 / 565."
create chore "Run the twelve checks of spec.md section 7 on the deployed URL" "all twelve pass; screenshots or notes go in the PR."
create chore "Check the phone layout" "the login, the chat and the invoices panel are usable at 375 px wide."
create chore "Calibrate the made-up history" "no budget line sits at several hundred percent only because of its supplier's typical amount."

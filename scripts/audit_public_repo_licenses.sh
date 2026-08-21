#!/usr/bin/env bash
set -euo pipefail

ORG="${ORG:-PickNikRobotics}"
TRACKING_REPO="${TRACKING_REPO:-PickNikRobotics/moveit_pro_ci}"
ISSUE_TITLE="Public repositories missing detected licenses"
MODE="${1:---check-only}"

if [[ "$MODE" != "--check-only" && "$MODE" != "--update-issue" ]]; then
  echo "Usage: $0 [--check-only|--update-issue]" >&2
  exit 2
fi

# Keep the query aligned with the scope established in moveit_pro#21401.
# Capture the command before parsing it so an API/authentication failure cannot
# be mistaken for an empty (all-clear) result.
if ! audit_output="$(
  gh api --paginate "/orgs/${ORG}/repos?type=public&per_page=100" \
    --jq '.[] | select(.fork == false and .archived == false and .license == null) | .full_name'
)"; then
  echo "::error::Unable to audit public repository licenses." >&2
  exit 2
fi

mapfile -t missing_repos < <(printf '%s\n' "$audit_output" | sed '/^$/d' | sort)

if ((${#missing_repos[@]} == 0)); then
  echo "All public, active, non-fork ${ORG} repositories have a detected root license."
else
  echo "Found ${#missing_repos[@]} public, active, non-fork repositories without a detected root license:"
  printf '  - %s\n' "${missing_repos[@]}"
fi

if [[ "$MODE" == "--check-only" ]]; then
  ((${#missing_repos[@]} == 0))
  exit
fi

issue_number="$(
  gh api --paginate "/repos/${TRACKING_REPO}/issues?state=open&per_page=100" \
    --jq ".[] | select(.pull_request == null and .title == \"${ISSUE_TITLE}\") | .number"
)"

if ((${#missing_repos[@]} == 0)); then
  if [[ -n "$issue_number" ]]; then
    gh issue comment "$issue_number" --repo "$TRACKING_REPO" \
      --body "The scheduled audit is clean again; closing this tracking issue."
    gh issue close "$issue_number" --repo "$TRACKING_REPO" --reason completed
  fi
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    echo "## Public repository license audit: clean" >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 0
fi

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
{
  echo "The scheduled license audit found public, active, non-fork repositories whose root license is not detected by GitHub:"
  echo
  for repo in "${missing_repos[@]}"; do
    printf -- '- [ ] [%s](https://github.com/%s)\n' "$repo" "$repo"
  done
  echo
  echo "For each repository, add a provenance-compatible root license, or make it private/archive it and record the disposition."
  echo
  echo "This issue is maintained automatically by \`${TRACKING_REPO}/.github/workflows/public_repo_license_audit.yaml\`."
} > "$body_file"

if [[ -n "$issue_number" ]]; then
  gh issue edit "$issue_number" --repo "$TRACKING_REPO" --body-file "$body_file"
else
  gh issue create --repo "$TRACKING_REPO" --title "$ISSUE_TITLE" --body-file "$body_file"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## Public repository license audit: action required"
    echo
    printf -- '- %s\n' "${missing_repos[@]}"
  } >> "$GITHUB_STEP_SUMMARY"
fi

# Keep the workflow visibly failing until the public exposure is resolved.
exit 1

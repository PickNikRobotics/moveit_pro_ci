#!/usr/bin/env bash
set -euo pipefail

readonly ORGANIZATIONS=(PickNikRobotics PickNikRoboticsServices)
readonly TRACKING_REPO="${TRACKING_REPO:-PickNikRobotics/moveit_pro_ci}"
readonly ISSUE_TITLE="Public repositories missing detected licenses"
readonly MODE="${1:---check-only}"
if ! SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; then
  echo "::error::Unable to resolve the audit script directory." >&2
  exit 2
fi
readonly SCRIPT_DIRECTORY
readonly LICENSE_FILTER_PATH="${SCRIPT_DIRECTORY}/public_repo_license_findings.jq"

if [[ "$MODE" != "--check-only" && "$MODE" != "--update-issue" ]]; then
  echo "Usage: $0 [--check-only|--update-issue]" >&2
  exit 2
fi
if [[ ! -r "$LICENSE_FILTER_PATH" ]]; then
  echo "::error::Unable to read repository license filter at ${LICENSE_FILTER_PATH}." >&2
  exit 2
fi
if ! LICENSE_FILTER="$(<"$LICENSE_FILTER_PATH")"; then
  echo "::error::Unable to load repository license filter at ${LICENSE_FILTER_PATH}." >&2
  exit 2
fi
readonly LICENSE_FILTER

missing_repos=()
for organization in "${ORGANIZATIONS[@]}"; do
  # Capture each command before parsing it so an API or authentication failure
  # cannot be mistaken for an empty, all-clear result.
  if ! audit_output="$(
    gh api --paginate "/orgs/${organization}/repos?type=public&per_page=100" \
      --jq "$LICENSE_FILTER"
  )"; then
    echo "::error::Unable to audit public repository licenses in ${organization}." >&2
    exit 2
  fi

  while IFS= read -r repository; do
    [[ -n "$repository" ]] && missing_repos+=("$repository")
  done <<< "$audit_output"
done

if ((${#missing_repos[@]} > 0)); then
  if ! sorted_missing_repos="$(printf '%s\n' "${missing_repos[@]}" | sort -u)"; then
    echo "::error::Unable to sort repository license findings." >&2
    exit 2
  fi
  mapfile -t missing_repos <<< "$sorted_missing_repos"
fi

if ((${#missing_repos[@]} == 0)); then
  echo "All public, active, non-fork repositories in ${ORGANIZATIONS[*]} have a detected root license."
else
  echo "Found ${#missing_repos[@]} public, active, non-fork repositories without a detected root license:"
  printf '  - %s\n' "${missing_repos[@]}"
fi

if [[ "$MODE" == "--check-only" ]]; then
  ((${#missing_repos[@]} == 0))
  exit
fi

if ! issue_output="$(
  gh api --paginate "/repos/${TRACKING_REPO}/issues?state=open&per_page=100" \
    --jq ".[] | select(.pull_request == null and .title == \"${ISSUE_TITLE}\") | .number"
)"; then
  echo "::error::Unable to query the tracking issue." >&2
  exit 2
fi
tracking_issues=()
while IFS= read -r issue; do
  [[ -n "$issue" ]] && tracking_issues+=("$issue")
done <<< "$issue_output"
if ((${#tracking_issues[@]} > 1)); then
  echo "::error::Found multiple open tracking issues titled '${ISSUE_TITLE}'." >&2
  exit 2
fi
issue_number="${tracking_issues[0]:-}"

if ((${#missing_repos[@]} == 0)); then
  if [[ -n "$issue_number" ]]; then
    gh issue comment "$issue_number" --repo "$TRACKING_REPO" \
      --body $'[written by AI]\n\nThe scheduled audit is clean again; closing this tracking issue.'
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
  echo "[written by AI]"
  echo
  echo "The scheduled license audit found public, active, non-fork repositories whose root license is missing or not recognized by GitHub:"
  echo
  for repository in "${missing_repos[@]}"; do
    printf -- '- [ ] [%s](https://github.com/%s)\n' "$repository" "$repository"
  done
  echo
  echo "For each repository, add a provenance-compatible root license, or make it private or archived. This machine-owned body is replaced on every run; record review notes and dispositions in issue comments."
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

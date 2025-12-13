#!/bin/bash

# Generate diff using nbdime for notebooks (cleaner semantic diff) and regular git diff for other files
# Ignores notebook changes that are only re-executions (output changes without code changes)
get_staged_diff() {
  if git diff --cached --name-only | grep -q '\.ipynb$'; then
    # Only include notebook diff if there are actual source changes (not just outputs)
    nb_source_diff=$(nbdiff --ignore-outputs --ignore-metadata --ignore-id  HEAD 2>/dev/null)
    if [[ -n "$nb_source_diff" ]]; then
      nb_diff="$nb_source_diff"
    else
      nb_diff=""
    fi
    other_diff=$(git diff --cached -- ':!*.ipynb' 2>/dev/null)

    if [[ -n "$nb_diff" && -n "$other_diff" ]]; then
      echo "$other_diff"
      echo ""
      echo "=== Notebook changes ==="
      echo "$nb_diff"
    elif [[ -n "$nb_diff" ]]; then
      echo "$nb_diff"
    elif [[ -n "$other_diff" ]]; then
      echo "$other_diff"
    else
      # Only output re-runs, mention it briefly
      echo "(Notebook changes are output-only re-executions)"
    fi
  else
    git diff --cached
  fi
}

nbdime config-git --enable

if [[ -n "$ANTHROPIC_API_KEY" ]] && git diff --cached --quiet --exit-code 2>/dev/null; then
  echo "No staged changes to commit"
  exit 1
elif [[ -n "$ANTHROPIC_API_KEY" ]]; then
  # Create JSON payload in a temp file to avoid argument length limits
  payload=$(mktemp)

  # Truncate diff to first ~50k chars to avoid token limits
  get_staged_diff | head -c 50000 | jq -Rs '{
    model: "claude-sonnet-4-20250514",
    max_tokens: 256,
    messages: [{role: "user", content: ("Write a concise git commit message for this diff. Just the message, no quotes, no explanation:\n\n" + .)}]
  }' > "$payload"

  response=$(curl -s https://api.anthropic.com/v1/messages \
    -H "x-api-key: $ANTHROPIC_API_KEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d @"$payload")

  msg=$(echo "$response" | jq -r '.content[0].text // empty')

  # If API call failed, show error and fall back to manual commit
  if [[ -z "$msg" ]]; then
    error=$(echo "$response" | jq -r '.error.message // "Unknown error"')
    echo "Error generating commit message: $error"
    git commit "$@"
    rm "$payload"
    exit $?
  fi

  rm "$payload"
  
  echo "Commit message: $msg"
  read -p "Use this message? [Y/n/e(dit)] " choice
  case "$choice" in
    n|N) git commit ;;
    e|E) git commit -m "$msg" --edit ;;
    *) git commit -m "$msg" ;;
  esac
else
  git commit "$@"
fi

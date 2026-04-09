#!/usr/bin/env bash

if [[ -n "${B2U_REPORT_SH_SOURCED:-}" ]]; then
  return
fi
readonly B2U_REPORT_SH_SOURCED=1

report_ensure_final_newline() {
  # Some command outputs do not end with a newline. Normalize them once so
  # fenced Markdown blocks do not collapse into the closing fence.
  perl -0pe 's/(?<!\n)\z/\n/'
}

report_status_emoji() {
  case "${1:-}" in
    "" | none) printf '%s' "" ;;
    ok | pass | green) printf '%s' "🟢" ;;
    info | blue) printf '%s' "🔵" ;;
    warn | warning | yellow) printf '%s' "🟡" ;;
    fail | error | red) printf '%s' "🔴" ;;
    *) printf '%s' "" ;;
  esac
}

report_status_rank() {
  case "${1:-ok}" in
    fail | error | red) printf '%s' "2" ;;
    warn | warning | yellow) printf '%s' "1" ;;
    *) printf '%s' "0" ;;
  esac
}

report_worse_status() {
  local current="${1:-ok}"
  local candidate="${2:-ok}"

  if (($(report_status_rank "$candidate") > $(report_status_rank "$current"))); then
    printf '%s\n' "$candidate"
  else
    printf '%s\n' "$current"
  fi
}

report_heading() {
  local outfile="$1"
  local level="$2"
  local status="$3"
  local title="$4"
  local marker
  marker="$(report_status_emoji "$status")"
  if [[ -n "$marker" ]]; then
    printf '%s %s %s\n' "$level" "$marker" "$title" >>"$outfile"
  else
    printf '%s %s\n' "$level" "$title" >>"$outfile"
  fi
}

report_write_line() {
  local outfile="$1"
  shift
  printf '%s\n' "$@" >>"$outfile"
}

report_code_block() {
  local content=""

  content="$(cat)"
  echo '```console'
  if [[ -n "$content" ]]; then
    printf '%s' "$content" | report_ensure_final_newline
  else
    printf '<no output>\n'
  fi
  echo '```'
}

report_text_block() {
  local outfile="$1"
  local level="$2"
  local status="$3"
  local title="$4"
  shift 4

  report_heading "$outfile" "$level" "$status" "$title"
  printf '%s\n' "$@" | report_code_block >>"$outfile"
  report_write_line "$outfile"
}

report_command_block() {
  local outfile="$1"
  local level="$2"
  local status="$3"
  local title="$4"
  local command="$5"
  local command_status=0
  local tmp

  tmp="$(mktemp)"
  bash --noprofile --norc -c "$command" >"$tmp" 2>&1 || command_status=$?
  report_heading "$outfile" "$level" "$status" "$title"
  report_code_block <"$tmp" >>"$outfile"
  rm -f "$tmp"
  if [[ $command_status -ne 0 ]]; then
    report_write_line "$outfile" "_Command exited with status ${command_status}_"
  fi
  report_write_line "$outfile"
}

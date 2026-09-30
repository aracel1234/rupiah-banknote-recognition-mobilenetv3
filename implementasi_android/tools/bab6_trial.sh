#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  cat <<'USAGE'
Usage:
  bab6_trial.sh <serial> begin <test_id> [test_group] [expected_label]
  bab6_trial.sh <serial> arm <test_id>
  bab6_trial.sh <serial> end <test_id> <result_code> [rejection_reason] [error_message] [valid_trial] [invalid_reason]
  bab6_trial.sh <serial> cancel <test_id> [reason]

Recommended result_code values:
  CORRECT_ACCEPTANCE
  WRONG_ACCEPTANCE
  CORRECT_REJECTION
  REJECTION
  NO_DECISION
  TECHNICAL_ERROR
USAGE
  exit 2
fi

SERIAL="$1"
ACTION="$2"
TEST_ID="$3"
COMPONENT="id.ac.ub.rupiah/.ui.MainActivity"
BASE=(adb -s "$SERIAL" shell am start -f 0x20000000 -n "$COMPONENT" --es bab6_action "$ACTION")

case "$ACTION" in
  begin)
    GROUP="${4:-}"
    EXPECTED="${5:-}"

    CMD=("${BASE[@]}" --es test_id "$TEST_ID")
    [[ -n "$GROUP" ]] && CMD+=(--es test_group "$GROUP")
    [[ -n "$EXPECTED" ]] && CMD+=(--es expected_label "$EXPECTED")

    "${CMD[@]}" >/dev/null
    echo "BEGIN $TEST_ID"
    ;;

  arm)
    "${BASE[@]}" --es test_id "$TEST_ID" >/dev/null
    echo "ARM $TEST_ID"
    ;;

  end)
    RESULT="${4:-UNSPECIFIED}"
    REJECTION="${5:-}"
    ERROR="${6:-}"
    VALID="${7:-true}"
    INVALID_REASON="${8:-}"

    CMD=("${BASE[@]}" --es test_id "$TEST_ID" --es result_code "$RESULT" --ez valid_trial "$VALID")
    [[ -n "$REJECTION" ]] && CMD+=(--es rejection_reason "$REJECTION")
    [[ -n "$ERROR" ]] && CMD+=(--es error_message "$ERROR")
    [[ -n "$INVALID_REASON" ]] && CMD+=(--es invalid_reason "$INVALID_REASON")

    "${CMD[@]}" >/dev/null
    echo "END $TEST_ID result=$RESULT valid=$VALID"
    ;;

  cancel)
    REASON="${4:-operator_cancelled}"
    "${BASE[@]}" --es test_id "$TEST_ID" --es reason "$REASON" >/dev/null
    echo "CANCEL $TEST_ID"
    ;;

  *)
    echo "Unknown action: $ACTION" >&2
    exit 2
    ;;
esac

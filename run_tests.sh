#!/usr/bin/env bash
# ==============================================================================
# Local LLM Gateway - Automated Unit & Integration Test Runner
# Runs the full test suite inside the active container or local Python environment.
# ==============================================================================

set -eo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${BLUE}${BOLD}===================================================================${RESET}"
echo -e "${BLUE}${BOLD}  Local LLM Gateway - Unit & Security Test Suite${RESET}"
echo -e "${BLUE}${BOLD}===================================================================${RESET}"

CONTAINER_NAME="v100-local-gateway"

if command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${GREEN}✓ Detected running gateway container: ${CONTAINER_NAME}${RESET}"
    echo -e "Executing test suite inside container...\n"
    docker exec -t "${CONTAINER_NAME}" python -W ignore -m unittest discover -s /workspace/app/app/tests -v
    TEST_EXIT_CODE=$?
else
    echo -e "Running test suite in local host python environment...\n"
    PYTHONPATH="app:app/app:${PYTHONPATH:-}" python3 -W ignore -m unittest discover -s app/app/tests -v
    TEST_EXIT_CODE=$?
fi

echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}${BOLD}===================================================================${RESET}"
    echo -e "${GREEN}${BOLD}  ✓ ALL TESTS PASSED SUCCESSFULLY!${RESET}"
    echo -e "${GREEN}${BOLD}===================================================================${RESET}"
else
    echo -e "${RED}${BOLD}===================================================================${RESET}"
    echo -e "${RED}${BOLD}  ✗ TESTS FAILED! (Exit code: ${TEST_EXIT_CODE})${RESET}"
    echo -e "${RED}${BOLD}===================================================================${RESET}"
fi

exit $TEST_EXIT_CODE

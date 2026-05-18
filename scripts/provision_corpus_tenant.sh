#!/usr/bin/env bash
# provision_corpus_tenant.sh
#
# Provision the read-only `corpus` tenant in the Atlas backend.
#
# Status: skeleton. The real implementation calls the Atlas backend's
# `civic-atlas tenant new` CLI once that subcommand supports the
# `--readonly-public` + `--multi-city` flags described in the Phase 5
# spec.
#
# Until then, this script documents the intended invocation.

set -euo pipefail

readonly TENANT_SLUG="corpus"
readonly TENANT_DISPLAY_NAME="Civic Atlas Multi-City Corpus"

# Atlas backend CLI binary. Default assumes the sibling repo layout.
ATLAS_CLI="${ATLAS_CLI:-../our-civic-atlas-backend/target/debug/civic-atlas-cli}"

if [[ ! -x "${ATLAS_CLI}" ]]; then
  echo "error: ${ATLAS_CLI} not found or not executable" >&2
  echo "       build it first: cd ../our-civic-atlas-backend && cargo build -p civic-atlas-cli" >&2
  exit 1
fi

echo "==> Provisioning tenant: ${TENANT_SLUG} (${TENANT_DISPLAY_NAME})"

# Phase 5 spec calls for:
#   civic-atlas tenant new corpus --readonly-public --multi-city
#
# `--readonly-public` => no write API surface for non-admin
# `--multi-city`      => skip the single-city assumption that the
#                        Flint tenant relies on, allow multiple
#                        city bboxes to live in one tenant.
#
# Once those flags exist in civic-atlas-cli, uncomment:
#
# "${ATLAS_CLI}" tenant new "${TENANT_SLUG}" \
#   --display-name "${TENANT_DISPLAY_NAME}" \
#   --readonly-public \
#   --multi-city
#
# Until then:
echo "skeleton: this script is a placeholder until civic-atlas-cli"
echo "          supports --readonly-public --multi-city flags."
echo
echo "Expected invocation when ready:"
echo "  ${ATLAS_CLI} tenant new ${TENANT_SLUG} \\"
echo "    --display-name \"${TENANT_DISPLAY_NAME}\" \\"
echo "    --readonly-public \\"
echo "    --multi-city"
exit 0

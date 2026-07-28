#!/usr/bin/env bash
set -euo pipefail

ref="${1:-${GITHUB_REF:-}}"
ref_type="${2:-${GITHUB_REF_TYPE:-}}"
sha="${3:-${GITHUB_SHA:-}}"

if [[ "$ref_type" != "tag" ]]; then
  echo "Production publishing requires a tag ref; got: ${ref_type:-<empty>}" >&2
  exit 1
fi

number='(0|[1-9][0-9]*)'
if [[ ! "$ref" =~ ^refs/tags/v${number}\.${number}\.${number}$ ]]; then
  echo "Production publishing requires an exact vX.Y.Z tag; got: ${ref:-<empty>}" >&2
  exit 1
fi

if [[ ! "$sha" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "Production publishing requires a full commit SHA; got: ${sha:-<empty>}" >&2
  exit 1
fi

tag_commit="$(git rev-parse --verify "${ref}^{commit}")"
if [[ "$tag_commit" != "$sha" ]]; then
  echo "Release tag resolves to ${tag_commit}, not workflow commit ${sha}" >&2
  exit 1
fi

echo "Verified production release ${ref#refs/tags/} at ${sha}"

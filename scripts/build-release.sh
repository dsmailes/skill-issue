#!/bin/bash
# Build the release tarball for the version in skill_issue.py.
# Output: dist/skill-issue-v<VERSION>.tar.gz and a matching .sha256 file.
# The archive holds `skill-issue` (executable) and LICENSE at the top level,
# with fixed timestamps and ownership so the checksum is reproducible.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' skill_issue.py)"
[ -n "$VERSION" ] || { echo "could not read __version__" >&2; exit 1; }

NAME="skill-issue-v${VERSION}"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
mkdir -p dist "$STAGE/pkg"

install -m 0755 skill_issue.py "$STAGE/pkg/skill-issue"
install -m 0644 LICENSE "$STAGE/pkg/LICENSE"
touch -t 202001010000 "$STAGE/pkg/skill-issue" "$STAGE/pkg/LICENSE"

tar --uid 0 --gid 0 --uname root --gname wheel -C "$STAGE/pkg" -cf - skill-issue LICENSE \
  | gzip -n -9 > "dist/${NAME}.tar.gz"
( cd dist && shasum -a 256 "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256" )

echo "built dist/${NAME}.tar.gz"
cat "dist/${NAME}.tar.gz.sha256"

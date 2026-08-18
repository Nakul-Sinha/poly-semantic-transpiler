# Hole cache (golden fills)

Each `<hash>.json` here is a validated hole fill, keyed by a hash of the hole
contract + target. On a rebuild the `HoleFiller` returns the cached fragment
directly — **zero** model calls, byte-identical output.

The cache is populated automatically on first run (live LLM or offline mock) and
is git-ignored by default (see `.gitignore`), since it is regenerated
deterministically. Delete a file to force that hole to be re-filled and
re-validated through gates A/B/C.

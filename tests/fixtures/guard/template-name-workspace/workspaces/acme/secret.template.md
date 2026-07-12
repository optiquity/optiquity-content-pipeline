# Obviously-synthetic negative guard fixture (tests/fixtures/guard): a `*.template.*`
# basename does NOT exempt client-workspace content (step-13 review RV-1) — the path
# alone names a client, so the file must be flagged as LEAK[workspace-content]
# regardless of its name (CLAUDE.md rules 2/4). Never real client data.
x-fixture: synthetic template-named workspace file - never real client data

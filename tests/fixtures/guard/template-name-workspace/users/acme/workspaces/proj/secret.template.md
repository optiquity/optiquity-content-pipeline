# Obviously-synthetic negative guard fixture (tests/fixtures/guard): a `*.template.*`
# basename does NOT exempt client content under users/ (step-13 review RV-1) — the path
# alone names a user/client, so the file must be flagged as LEAK[workspace-content]
# regardless of its name (CLAUDE.md rules 2/4; §23 re-home). Never real client data.
x-fixture: synthetic template-named workspace file - never real client data

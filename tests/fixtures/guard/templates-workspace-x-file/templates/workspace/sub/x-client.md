# Obviously-synthetic negative guard fixture (tests/fixtures/guard): an instance-namespaced
# `x-*` file nested DEEP inside the framework workspace blueprint (templates/workspace/sub/).
# The blueprint subtree is NOT exempt wholesale — the whole of templates/ flows through the
# [W8] scan arm — so this must be flagged as LEAK[x-file] (the reserved instance namespace,
# design §11.4 SV5; CLAUDE.md rules 2/4). Never real client data.
x-client: synthetic client blueprint smuggled inside templates/workspace/ - never real

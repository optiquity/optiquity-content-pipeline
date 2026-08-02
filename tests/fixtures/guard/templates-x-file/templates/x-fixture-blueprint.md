# Obviously-synthetic negative guard fixture (tests/fixtures/guard): an instance-namespaced
# `x-*` file dropped directly under templates/ (OUTSIDE the exempt templates/workspace/
# blueprint). templates/ is framework mechanism — owner-agnostic blueprints only ([W8]); a
# client blueprint must never hide here unscanned. Must be flagged as LEAK[x-file] (the
# reserved instance namespace, design §11.4 SV5; CLAUDE.md rules 2/4). Never real client data.
x-fixture: synthetic client blueprint smuggled under templates/ - never real

# Obviously-synthetic negative guard fixture (tests/fixtures/guard): a template-named
# file inside an `x-*` directory in a registry root. The reserved x- namespace leaks by
# PATH regardless of basename (step-13 review RV-1) — must be flagged as LEAK[x-file],
# design §11.4 SV5. Never real content.

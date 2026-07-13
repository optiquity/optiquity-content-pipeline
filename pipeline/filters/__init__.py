"""Serialize-owned Pandoc-AST filters (framework mechanism, `provenance: framework`).

The pinned provenance-strip filter (§17 R-4) lives here. Filters in this package are
SERIALIZE-OWNED: they are pure AST → AST transforms wired into the dispatcher by writer,
never Presentation levers (PD3). No client/style configuration can reach or disable them.
"""

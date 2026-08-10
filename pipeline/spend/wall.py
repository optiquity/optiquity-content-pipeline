"""The subscription controlled-settings WALL — spend-package home (plan G2, §21.10, S-4).

**Where the wall LIVES, and why it is not the wall's implementation here.** The wall PRIMITIVE
(the controlled-settings file, the `--settings`/`--setting-sources` argv, the
managed-`apiKeyHelper` detect-and-refuse, and the widened F10 env strip) lives in
`pipeline.transport`, NOT in this module, for one hard architectural reason:

- The wall must fire on EVERY subscription spawn BY CONSTRUCTION (no un-walled path — plan G2),
  and every subscription spawn — generation AND the research seam — traverses exactly one node:
  `transport.invoke_headless`, the lowest shared node the CLI and the served `invoke()` re-entry
  both cross.
- `pipeline.transport` imports **NOTHING** from `pipeline.spend` (the no-cycle invariant pinned
  in `pipeline/spend/__init__.py` and enforced by the G9 module-boundary grep): `spend`'s
  `construction.py` imports the generation stages, which import `transport`, so a
  `transport → spend` import would close a cycle.

Those two facts together mean the primitive CANNOT live in `pipeline.spend` and still be applied
fail-closed at the chokepoint without a forbidden `transport → spend` import. So the primitive
lives in `transport` (which already OWNS hermetic-spawn construction — `build_child_env` builds
the env; `build_subscription_wall` builds the settings-isolation), and THIS module is the
spend-package-facing HOME for it: a re-export of the wall API (`spend → transport` is the
established direction — `construction.py` already imports the generation stages), and the seam the
G7 api-key path will EXTEND with its own controlled-settings wall. No paid/api-key surface ships
here — G2 only tightens the subscription path (still no key).

Import rule check: this module imports ONLY `pipeline.transport`; it adds no `spend`-internal
coupling and keeps `transport` free of any `spend` import.
"""

from __future__ import annotations

from pipeline.transport import (
    SETTING_SOURCES_NONE,
    ControlledSettingsError,
    ManagedApiKeyHelperError,
    SubscriptionWall,
    SubscriptionWallError,
    build_subscription_wall,
)

__all__ = [
    "SETTING_SOURCES_NONE",
    "ControlledSettingsError",
    "ManagedApiKeyHelperError",
    "SubscriptionWall",
    "SubscriptionWallError",
    "build_subscription_wall",
]

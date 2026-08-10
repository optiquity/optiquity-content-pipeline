---
provenance: framework
---

# C++ client — a proof-of-concept wrapper over the pipeline's HTTP shim

A worked **second language** proving the canonical client surface in
[`docs/guide/clients.md`](../../docs/guide/clients.md) is not Python-special. This C++17 wrapper
implements the **identical** method set, outcome set, poll state machine (§2.3), normalized-Response
rule (§2.5), Retry-After / malformed-body fallback rule (§2.6), and no-invent rule (§2.8) as the
stdlib Python reference in [`pipeline/client/`](../../pipeline/client/). Only the substrate is
language-reality: the error channel is `throw` (on C++17 grounds) and the transport is
**libcurl + nlohmann/json**. Nothing else differs from Python.

These are **generic** examples: every deployment-specific value is a placeholder — `acme`
(`<WORKSPACE>`), `acme-user` (`<USER>`, the §23 isolation prefix), `default` (`<ZONE>`, the §23/Z4
isolation zone between user and workspace — every request body now carries it next to
user/workspace), `deck-intro` (`<ARTIFACT_ID>`), `http://127.0.0.1:8787` (the shim's loopback
default), `<SHIM_SECRET>` (your bearer token, from env only). **No client content.**

| File | What it is |
|---|---|
| [`optiquity_client.hpp`](./optiquity_client.hpp) | the `Client` + outcome types + `Response` value type + `parse_callback` — the full canonical surface |
| [`optiquity_client.cpp`](./optiquity_client.cpp) | the implementation (libcurl transport, guarded nlohmann/json parse, the poll state machine) |
| [`example.cpp`](./example.cpp) | a runnable demo: env-config → raw `list` → a **forced** submit→202→poll→done render → a **caught typed error** → pure `parse_callback` |
| [`CMakeLists.txt`](./CMakeLists.txt) | the CMake build path (one executable, no install target) |

---

## 1. Dependencies (two)

1. **libcurl** — the HTTP transport (verified TLS, no-follow-redirect). **If the dev headers are
   missing:** `brew install curl` (macOS) or `apt-get install libcurl4-openssl-dev` (Debian/Ubuntu).
   macOS Command Line Tools usually already ship libcurl, so a plain `-lcurl` often just works.
2. **nlohmann/json** — a **single-header** JSON library (`json.hpp`). Get it one of three ways:
   - a package: `brew install nlohmann-json` / `apt-get install nlohmann-json3-dev`, **or**
   - drop the single header on your include path — download `json.hpp` from
     `https://github.com/nlohmann/json/releases` (v3.11.x) into a dir you pass with `-I`, **or**
   - let CMake fetch it (below).

## 2. Build

### Option A — CMake (fetches nlohmann/json if not installed)

```sh
cd examples/cpp
cmake -B build && cmake --build build
# -> build/example
```

### Option B — one-line g++ (you supply `json.hpp`)

```sh
cd examples/cpp
g++ -std=c++17 example.cpp optiquity_client.cpp -o example -lcurl -I<dir containing nlohmann/json.hpp>
```

Both source files compile together — the surface lives in `optiquity_client.cpp`, the demo in
`example.cpp`. (`-I<dir>` must be the parent of the `nlohmann/` folder, so `#include
<nlohmann/json.hpp>` resolves.)

## 3. Run

Config is **env, identical across languages** (§2.1). The secret comes **only** from the
environment — never from argv, and it is never printed:

```sh
OPTIQUITY_SHIM_URL=http://127.0.0.1:8787 \
OPTIQUITY_SHIM_SECRET=<SHIM_SECRET> \
  ./example        # or: ./build/example
```

against a running `pipeline serve` (see
[`docs/guide/interfaces.md`](../../docs/guide/interfaces.md) → "HTTP access"). The demo forces the
**submit → 202 → poll(Retry-After) → done** traversal (`force_reconcile` + a fresh idempotency key
defeat the render cache-hit short-circuit) **and** catches at least one typed failure outcome, so it
exercises the load-bearing poll loop *and* the `throw` error channel — not a happy-path render that
could 200-cache and skip the loop.

---

## 4. The no-CI-build gap, stated plainly

**CI does NOT build this C++.** `examples/` is never compiled, linted, or content-scanned in CI
(same posture as [`examples/n8n/`](../n8n/)) — there is no guaranteed libcurl or `json.hpp` on the
runner, and a compile + network fetch is deferred infrastructure, not MVP. **Nothing automated ties
this wrapper to the wire-token vocabulary.** The single neutral source of record is
[`docs/guide/clients.md`](../../docs/guide/clients.md); this POC stays in sync **by the checklist
below**, plus the header comment in `optiquity_client.hpp` citing that doc.

### Drift checklist — run this when `docs/guide/clients.md` changes

The wire-token sets live ONLY in the doc, between its `<!-- wire-tokens:*:begin/end -->` sentinels;
this client does **not** hardcode them (it surfaces the **raw** `code`, §1.6 open-string rule). When
those blocks — or the canonical surface — change, re-verify this POC against the doc:

- [ ] **`<!-- wire-tokens:terminal-codes -->` changed?** The client already surfaces the raw `code`
      and branches on `redrivable` / `terminal` (never an exhaustive `code` switch), so a new code
      needs **no** code change here — but confirm `example.cpp`'s error-handling still reads well.
- [ ] **`<!-- wire-tokens:async-status -->` or the §2.3 state-machine table changed?** Re-check
      `Client::await_terminal` in `optiquity_client.cpp` branch-for-branch against §2.3 (the 200-done
      / 202 / 429 / 504 / 409 / 4xx-5xx arms + the deadline).
- [ ] **`<!-- wire-tokens:sync-errors -->` or `<!-- wire-tokens:callback-events -->` changed?**
      Re-check `parse_callback` (`{job.done, job.failed}`) and the `RenderBlocked` /
      `render-blocked` mapping.
- [ ] **Method set / outcome set (§2.2, §2.3, §2.4) changed?** Mirror the signature/outcome change
      in `optiquity_client.hpp` + `.cpp`, keeping the Python reference (`pipeline/client/`) as the
      co-equal cross-check.
- [ ] **Rebuild + run** (§2–§3 above) against a live `pipeline serve` and confirm the render slice
      still traverses submit→202→poll→done and the error path still catches a typed outcome.

## 5. Caveats

- **The `provenance: framework` front-matter is human-review hygiene, not CI-enforced.** It marks
  this as a generic framework artifact (no client-specific content); no automated guard currently
  checks it on `examples/`. Keep these files placeholder-only by review.
- **libcurl / `json.hpp` may be absent on a given machine.** See §1 for the one-line installs; a
  missing dev header is a local setup gap, not a defect in this POC.

---
[← Manual home](../../README.md) · Canonical surface: [`docs/guide/clients.md`](../../docs/guide/clients.md) · Python co-equal: [`pipeline/client/`](../../pipeline/client/)

# Third-party licenses

**optiquity-content-pipeline** is licensed under the **MIT License** (see `LICENSE`).

Its runtime dependencies are installed from PyPI **at runtime** — their source is **never
vendored or committed into this repository**, so no third-party (including any copyleft) source
ships in this MIT deliverable. This file records the licenses of those dependencies for anyone
who installs or redistributes the pipeline. The authoritative pin set is `pyproject.toml` +
`uv.lock`; this list is a convenience mirror (reconfirm against `uv.lock` at release).

## Direct runtime dependencies

| Package | Pin | License |
|---|---|---|
| `ruamel.yaml` | 0.19.1 | MIT |
| `feedparser` | 6.0.14 | BSD-2-Clause |
| `trafilatura` | 2.2.0 | Apache-2.0 |

Dev-only (not distributed with the runtime): `pytest` (MIT), `ruff` (MIT).

## Transitive runtime dependencies

All permissive (MIT / BSD / Apache-2.0 / PSF) except the two weak/file-level-copyleft items
called out below.

| Package | License |
|---|---|
| `feedparser-sgmllib` | PSF-2.0 |
| `babel` | BSD-3-Clause |
| `charset-normalizer` | MIT |
| `courlan` | Apache-2.0 |
| `dateparser` | BSD-3-Clause |
| `htmldate` | Apache-2.0 |
| `justext` | BSD-2-Clause |
| `lxml` | BSD-3-Clause |
| `lxml-html-clean` | BSD-3-Clause |
| `python-dateutil` | Apache-2.0 / BSD-3-Clause (dual) |
| `pytz` | MIT |
| `regex` | Apache-2.0 AND CNRI-Python |
| `six` | MIT |
| `tzdata` | Apache-2.0 (win32-only marker) |
| `tzlocal` | MIT |
| `urllib3` | MIT |

## Weak / file-level copyleft — conscious acceptance

Two runtime dependencies carry weak, file-level copyleft. Both are **redistribution-compatible
with this MIT framework** because their source is never vendored here (runtime-installed from
PyPI), and neither imposes copyleft on this project's own MIT-licensed code:

- **`certifi`** — **MPL-2.0**. File-level weak copyleft; redistribution is permitted. It ships
  the CA-certificate bundle; no modification is made here.
- **`tld`** — tri-licensed **`MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later`** (pulled transitively
  via `trafilatura → courlan → tld`). Because this is a **disjunctive (OR)** license, this project
  and any downstream redistributor **elect `MPL-1.1` (or `LGPL-2.1-or-later`)** — both weak,
  file-level copyleft that do **not** infect MIT code. The `GPL-2.0-only` option is **not**
  elected. As with all deps, `tld` is installed at runtime and its source is never committed to
  this repo.

No exclusively GPL/AGPL/strong-copyleft dependency is present in the runtime tree.

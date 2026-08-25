# Wiki Schema — how this llmwiki is maintained

This project keeps knowledge in an **LLM-maintained wiki** (pattern:
[karpathy's "LLM Wiki"](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)).
The wiki is the durable memory for the fogmachine-bt reverse-engineering + Home
Assistant integration effort. Read this file first; it tells you (human or LLM)
how to add to and curate the wiki so it stays coherent over many sessions.

## Three layers

1. **Raw sources** (`/sources/`, immutable): the APK, decompiled Java/smali,
   BLE-scan JSON dumps, Codex's independent analysis, live GATT captures. Never
   edit these — they are evidence. Register each under [sources](sources.md).
2. **The wiki** (`/wiki/`, this folder): distilled, cross-referenced markdown
   pages. Each page is one coherent topic. Pages summarise and *cite* the raw
   sources rather than duplicating them.
3. **The schema** (this file): the rules below.

## Operations

- **Ingest** — when a new source appears (new capture, new decompile, Codex
  output, a live test result), extract the durable facts and fold them into the
  relevant wiki page(s). Add a one-line entry to [sources](sources.md) with the
  path and what it contributed. Prefer *updating* an existing page over adding a
  new one.
- **Query** — to answer a question, read [index](index.md) → the relevant
  page(s). If the answer required synthesis worth keeping, file it back as a
  page edit.
- **Lint** — periodically (and before ending a session) check for:
  contradictions between pages, claims with no source citation, stale
  "TODO/unverified" markers that are now resolved, orphaned pages not linked
  from [index](index.md), and duplicated facts that should live in one place.

## Page conventions

- **Filename**: `kebab-case.md`, one topic per file.
- **Every page starts** with a one-line purpose and a `Status:` line
  (`verified` / `partial` / `unverified` / `planned`).
- **Cite evidence** inline: `` `com.spw…ClassName.method()` `` for code claims,
  or the source path for capture claims. A claim a future reader can't trace to
  a source is a lint failure.
- **Distinguish fact from plan**: what the device/app *does* (verified from
  code/captures) vs. what *we intend to build* (design). Keep them on different
  pages or clearly separated.
- **Cross-link** related pages with normal markdown links. Link liberally.
- **Mark uncertainty** explicitly with `⚠️ unverified` so lint can find it and a
  later live test can resolve it.

## Taxonomy (current pages)

| Page | Holds |
|---|---|
| [index](index.md) | Map + current status of the whole effort |
| [sources](sources.md) | Registry of raw immutable inputs |
| [device-fg53850](device-fg53850.md) | The physical machine: identity, BLE address, RF |
| [ble-transport](ble-transport.md) | GATT services/chars, connect, chunking, notify |
| [ble-protocol](ble-protocol.md) | The authoritative frame + command spec |
| [ha-proxy-coverage](ha-proxy-coverage.md) | Which HA BLE proxies hear the device |
| [integration-plan](integration-plan.md) | Design of the HA Bluetooth integration |

Add rows here when you add pages.

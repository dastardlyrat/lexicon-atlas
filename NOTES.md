# Lexicon Atlas notes

## Interface layout verification

On 2026-11-04, the view navigation was moved into an explicit responsive header grid so it cannot overlap the brand and provenance subtitle. The relation graph now uses bounded two-line SVG labels, dynamically sized nodes, and additional edge padding instead of silently dropping the final character of a long single-word label.

Headless Edge renders passed at 1600 by 1000, 1000 by 900, and 700 by 900 pixels. JavaScript syntax and the complete `lexicon-atlas-data/4` structural validation also passed. These checks establish the tested layout and syntax only; they do not change lexical authority or source semantics.

Relation graph nodes now use rounded rectangular boxes sized from their one-line or two-line label content. The current chain layout arranges relation depth in columns and can reverse between front-to-back and back-to-front reading. Selecting a node moves it and its direct neighbors to the visual foreground, dims unrelated branches, and shows the recorded part of speech, lexical sense ID, synset ID, and source definition. Traversal remains capped at five levels, 20 new nodes per level, and 100 related nodes overall.

## Source inventory

| Identifier | Confirmed location | Type | Version or status | Authority | Accessibility | Integrity | Relevance |
|---|---|---|---|---|---|---|---|
| OEWN | `../.wn_data/wn.db` | SQLite lexicon | `oewn:2025` | Candidate lexical senses and relations | Complete local database | Hash in `dist/data/manifest.json` | Primary WordNet evidence |
| CMUdict | `vendor/cmudict/` | Text corpus | pinned Git revision | Pronunciation evidence | Complete local file | Hash in manifest | ARPAbet and stress |
| UniMorph English | `vendor/unimorph-eng/` | TSV corpus | pinned Git revision | Morphology evidence | Complete local files | Hashes in manifest | Grammar, forms, derivation |
| Open Dict IPA | `vendor/ipa-dict/` | TSV corpus | `43c3570...` | Pronunciation evidence | Complete en_US and en_UK files | Hashes in manifest | IPA with dialect labels |
| Wiktionary via Kaikki | `.lexical_sources/wiktionary/` | JSONL extraction | 2026-09-25 extraction from 2026-09-02 dump | Supplemental lexical evidence | Complete 3,335,555,506-byte local file | SHA-256 `e6e48581...a43fb0e` | Definitions, etymology, IPA, forms |
| GCIDE | `.lexical_sources/gcide/gcide-0.54/` | Marked-up dictionary corpus | 0.54 | Historical supplemental definitions | Complete local corpus | archive SHA-256 `22416f6f...c51d42` | Broader historical coverage |
| StarDict | user-supplied `.ifo/.idx/.dict[.dz]` | Container format | per dictionary | No inherent lexical authority | Import adapter validated with a fixture | per-file hashes on import | Interchange with existing offline dictionaries |
| ODict | `.lexical_sources/odict-src/` | Format and toolchain | revision `6a2bb5a...` | No inherent lexical authority | ODXML export available; binary compiler absent locally | export hashes in manifest | Portable offline distribution |

## Provenance rules

- Source records stay in provider-specific shards.
- A normalized spelling joins the display only; it does not merge senses.
- WordNet remains candidate lexical evidence.
- GCIDE is labeled historical because its base is Webster 1913 and later additions include some WordNet material.
- Wiktionary is local when its imported shards exist. The network endpoint is a visible fallback for a missing local entry.
- ODict and StarDict describe packaging and interchange. Their contents retain the source dictionary's license and authority.

## Validation boundary

Structural validation confirms counts, hashes, JSON readability, ODXML well-formedness, and StarDict record decoding. It does not prove that any source is semantically correct or complete for all English vocabulary. Imported records remain lexical candidates until the deterministic parser resolves them under its own explicit rules.

The Synthesis view ranks attached WordNet, Wiktionary, and GCIDE definition records with explicit source weights, cross-record lexical overlap, and optional context-token overlap. It displays a generated candidate proposal while preserving every ranked source record and collision. The optional AI button is inert unless a caller explicitly configures `window.lexiconAtlasAI`; without that hook, no text is transmitted outside the page. AI output remains generated text and is never promoted to authority or execution.

The Wiktionary import read 1,492,836 rows. It indexed 1,492,835 entries under 1,355,919 normalized spellings and recorded one blank-headword punctuation row as skipped. No JSON row failed to parse. The complete ODXML export contains the same 1,355,919 headwords across 256 shards. ODXML carries headwords, etymologies, parts of speech, pronunciations, forms, sense tags, definitions, and examples; source relation lists remain in the browser JSON and are explicitly outside this ODXML adapter.

## Offline desktop scaffold

`desktop/main.cjs` is a generated Electron shell around the existing `dist/` build. It binds only to loopback, serves files beneath `dist/`, rejects traversal and non-read requests, and disables renderer Node integration. This establishes the shell boundary; packaged-data hashing, offline fallback enforcement, and installer reproducibility remain unimplemented until the later stages in `OFFLINE_APP_OUTLINE.md`.

The first browser extraction is `dist/modules/synthesis-engine.js`. It is pure and returns ranked source candidates, context matches, and shared lexical cues. `dist/app.js` remains the controller until the data stores and view renderers are extracted under the staged module plan.

The reusable NLP extraction remains separate from this site in a `Lexicon Core` checkout. Its `lexicon_core.registry` package reads the machine-local registry under `LEXICON_DATA_ROOT`. A central data directory can use platform links to verified dictionary roots, avoiding duplicate datasets while giving sibling projects stable source IDs and provenance metadata.

## Catalog adapter profile

The advisory Aurora handoff `catalog.modular-nlp-capability-handoff/0.1` is now scaffolded under `Lexicon Core/src/lexicon_core/adapters/catalog_v0_1.py`. The profile keeps exact source text and hashes, requires source spans, preserves the supplied move collision, extracts the accepted no-physical-move constraint, declares provenance and confidence semantics, records a layer trace, and gates every operation against a caller-supplied registry. It emits proposals only and cannot authorize or execute catalog or filesystem mutations.

The supplied Markdown contract has SHA-256 `06844a15763d21a97adccbf6376a9a120da209a454cfed08e5dce2d296da4faf`; its JSON capability summary has SHA-256 `8d00ccd34206d9bffa8bb439b58e228684084e12f326248cd44dd1a048cceb07`. These are source-integrity records, not catalog acceptance receipts.

The generated catalog output schema passed `jsonschema` 4.26.0 Draft 2020-12 meta-schema validation. Seven envelopes covering the supplied acceptance dispositions also validated. This establishes schema conformance for the tested outputs only; it does not establish receiving-catalog acceptance.

The public `resources.html` ledger lists the six lexical resources active in the browser build and links their source and license records. It preserves two material qualifications: OEWN's CC BY 4.0 layer retains underlying Princeton WordNet terms, and the bundled Wiktionary manifest's CC BY-SA 3.0 record conflicts with Wiktionary's current CC BY-SA 4.0 copyright page. The page labels that version mismatch for review instead of silently resolving it. ODict and StarDict are described as inactive interchange formats, not current browser data sources.

The relation graph can open in a near-full-screen modal explorer. The expanded view reuses the active traversal, preserves clickable relation boxes, mirrors the selected relation and recursion depth, and updates both the embedded and expanded graphs from the same state. It does not increase the existing five-level or 100-node traversal bounds.

The empty-hash showcase state opens `entity` with the semantic Hyponym relation at depth 5 and forward flow. Relation, depth, and flow are encoded in the URL so this presentation can be reproduced and shared; explicit URL values and later visitor choices remain authoritative over the default.

The `v0.1.0` public release is a generated code-only publication based on live Site source commit `c70b5b33c2adb7ea5f792f22845d4a515ebb92bc`. The release deliberately excludes dictionaries, generated shards, databases, archives, dependency caches, and automatic downloaders. Passing the repository guard establishes that packaging boundary only; it does not validate third-party data rights or live behavior after a user installs separate data.

The user-supplied 1284×1698 JPEG is preserved at `dist/assets/philippe-stuart-art.jpg` with SHA-256 `5b52740e4cc581ada0857cbc4002bb7efd2254f713fcf0773a1ef9af77f3c43f`. It appears in a non-interactive opening splash that holds for four seconds before fading, and in a linked About card for `https://www.facebook.com/philippe.stuart/`. No separate artwork license was supplied, so the resource ledger records the usage and unknown license state without inferring ownership or permission beyond the user's requested inclusion.

The catalog registry scaffold now accepts typed argument contracts and its validator rejects invalid received candidates. A generated Draft 2020-12 schema describes that registry input. The generic file-explorer task module can be bridged into `catalog.find` and `catalog.ls` while retaining the generic router and catalog adapter as separate layers. A partial-parse fixture demonstrates that a supported `find` clause and unsupported trailing clause remain independently visible. The deterministic no-physical-move family recognizes both `do not move` and `without moving` forms.

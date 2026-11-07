# Lexicon Atlas module architecture

## Boundary rule

Each module should do one job, expose a small data contract, and keep source evidence separate from generated interpretation. UI modules may display proposals; they must not promote them to parser authority or execute commands.

## Current modules

| Module | Location | Responsibility | Extraction status |
|---|---|---|---|
| Data build | `build_data.py` | Build OEWN and attached browser shards | Existing standalone module |
| Dictionary adapters | `lexical_pipeline.py` | Download, import, normalize, and export dictionary formats | Existing standalone module |
| ODict bridge | `odict_bridge.cjs` | Compile and query ODXML through the official binding | Existing standalone module |
| Desktop shell | `desktop/main.cjs` | Loopback server and restricted Electron window | Scaffolded |
| Synthesis engine | `dist/modules/synthesis-engine.js` | Pure candidate collection, ranking, context matching, and cue extraction | First browser extraction |
| Browser controller | `dist/app.js` | State, events, data loading, and view coordination | Still being decomposed |
| Shared NLP core | separate `Lexicon Core` checkout | Reusable normalization, collisions, morphology, relations, intent proposals, and synthesis | Extracted package scaffold |

## Target browser layers

```text
frontend/
  data/
    manifest-store.js       manifest and shard access
    wordnet-store.js        terms, words, synsets, relations
    dictionary-store.js     Wiktionary and GCIDE records
    morphology-store.js     UniMorph and pronunciation records
  evidence/
    record-model.js         source-tagged evidence records
    collision-index.js      visible collision grouping
    provenance.js           licenses, hashes, source ledger
  meaning/
    synthesis-engine.js     deterministic candidate ranking
    ai-provider.js          optional explicitly configured provider
    proposal-boundary.js    generated versus accepted state
  views/
    sense-graph-view.js
    full-word-view.js
    synthesis-view.js
  app-controller.js         URL state, navigation, lifecycle
```

The reusable Python package mirrors these boundaries under `Lexicon Core/src/lexicon_core/`: `registry`, `normalize`, `collisions`, `morphology`, `relations`, `intent`, `synthesis`, and `pipeline`.

Task-specific adapters live under `Lexicon Core/src/lexicon_core/tasks/`:

- dictionary lookup
- file explorer proposals
- expert-system rule and axiom proposals
- deterministic ELIZA NXT responses
- capability routing with collision review

External consumer profiles live under `Lexicon Core/src/lexicon_core/adapters/`. The first profile, `catalog_v0_1`, converts bounded deterministic matches into the advisory catalog `InterpretationResult` envelope while accepting the authoritative operation registry and typed argument contracts from the caller. Its task bridge maps generic file-explorer search and list proposals without changing the generic task contracts or dispatching returned operations.

## Extraction order

1. Keep `synthesis-engine.js` pure and covered by fixture inputs.
2. Extract data access from `app.js` without changing shard URLs.
3. Extract source normalization and collision grouping.
4. Move each view renderer behind a small render contract.
5. Leave the controller responsible only for state transitions and event wiring.
6. Share the pure evidence and meaning modules with the future command parser.

## Contracts

- Data stores return source-labeled records or explicit absence.
- Evidence records retain provider, license, source reference, and raw or normalized fields.
- Synthesis returns proposals with scores and evidence references; it never returns authority.
- AI providers accept a bounded proposal request and return generated text marked as generated.
- Views consume state and emit user intent events; they do not call shell APIs.

## Current verification

The first extraction was tested through the local browser build. The Synthesis pane still loads `bank`, reranks a deposit context to the financial noun sense, and reports zero page errors.

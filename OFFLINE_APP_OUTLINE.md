# Lexicon Atlas standalone offline program

## Goal

Ship Lexicon Atlas as a desktop program that opens the existing lexical browser locally, without requiring a web server, network access, or a hosted site.

## Current scaffold

- `desktop/main.cjs` starts a loopback-only static server for the existing `dist/` build and opens it in an Electron window.
- `desktop/preload.cjs` exposes only read-only offline runtime metadata to the page.
- `desktop/package.json` defines the desktop entry point and local development command.
- The existing `dist/` data remains the source of truth for the first offline build. Its compressed shards continue to load through ordinary HTTP semantics on loopback.

## Runtime boundaries

1. The desktop shell binds to `127.0.0.1` on an ephemeral port.
2. The shell serves only files under the checked-out `dist/` directory.
3. Path traversal, directory listings, and unknown file types are rejected.
4. The renderer has no Node integration and receives no filesystem or shell authority.
5. Network-backed Wiktionary fallback remains disabled by the desktop policy in the next integration step; local records must remain visible when a source is absent.
6. Synthesis remains a generated proposal. It does not create parser authority, axioms, or command execution.

## Delivery stages

### Stage 1: shell scaffold (this change)

- Start the local shell and load the existing UI.
- Confirm that WordNet, compressed dictionary shards, synthesis, and provenance views work offline.
- Keep the web deployment and source data unchanged.

### Stage 2: offline policy

- Add a desktop runtime flag consumed by the renderer.
- Disable live dictionary fallback when the runtime is offline.
- Add a visible status badge and an offline diagnostics panel.

### Stage 3: packaged data

- Copy `dist/` into the application resources during packaging.
- Record a manifest and SHA-256 for every packaged data bundle.
- Add a reproducible build script and lockfile.

### Stage 4: native distribution

- Produce a Windows installer and a portable directory build.
- Test first launch, search, five-level graph traversal, full-word records, synthesis, and clean shutdown without network access.
- Preserve source licenses and the evidence ledger in the installed bundle.

## Acceptance checks

- The program starts with no network connection.
- Search for `bank` opens WordNet, IPA, UniMorph, local Wiktionary, and GCIDE records.
- The Synthesis pane ranks candidates and reranks from user context.
- The optional AI hook is inert until explicitly configured.
- No page action can execute a shell command or write a file.
- The browser build still passes its existing structural validation.

## Known limits

This is a scaffold, not an installer. Electron runtime pinning, lockfile generation, packaged-data hashing, and the final offline fallback switch are scheduled for the later stages above.

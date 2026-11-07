# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-07

### Added
- Collection: downloaders for the SET universe, SET top-10 shareholders (experimental), One Report documents and
  GLEIF, with CSV templates for SETSMART exports and manual entry.
- Extraction: page finder and Claude-assisted table extraction from 56-1 One Reports, BOJ.5 and bank Pillar 3
  reports (`prompts/extract_*.md`), with Message Batches mode and a review queue for low-confidence rows.
- Entity resolution of Thai and English names: repair of Thai PDF glyph artefacts, legal forms, personal titles and
  conservative fuzzy matching with a review file and manual overrides.
- Ultimate ownership: cash-flow rights as M(I−M)⁻¹ and block-wise weakest-link control rights with cross-holdings
  and cycles, family aggregation, and NVDR, custodian and fund accounts excluded from control.
- Business groups, pyramids, control–cash-flow wedges and the finance–business nexus (ownership, shared directors,
  fund holdings between bank groups and business groups).
- Outputs: poster network map, group control trees, paper figures with automatic text-overlap QA, a self-contained
  HTML explorer and an arXiv-style LaTeX paper whose numbers are macros filled from the results, with an arXiv bundle.
- Synthetic world generator (`tbg demo`, `tbg synth`) and the synthetic showcase in `docs/`.
- Unit tests of the ownership algorithms and a synthetic smoke test in CI.
- Packaging and tooling: `src/tbg/` layout installed from `pyproject.toml` (hatchling) with a `tbg` console script,
  a `Makefile` with one target per pipeline step, and CI (`ci.yml`) running the tests and a synthetic smoke test.
- Documentation: README banner (`docs/assets/banner.png`, `scripts/make_banner.py`), the source list
  `docs/data_sources.md`, the Thai step-by-step guide `docs/guide_th.md` and the explorer on GitHub Pages.
- Dataset on Hugging Face, [`thanatchon36/tbg-kit`](https://huggingface.co/datasets/thanatchon36/tbg-kit): one full
  synthetic run (raw inputs, resolved network, ultimate owners, groups, bank–group links), built by `make hf`
  (`scripts/build_hf_dataset.py`, which refuses any non-synthetic workspace).

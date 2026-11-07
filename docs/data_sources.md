# Data sources

Everything in `docs/` and `demo/` is synthetic. This is the list of public sources the pipeline reads when you build
the real network. Real files go under the workspace (`work/` by default, set in `config.yaml`), which is git-ignored:
shareholder and director lists contain personal data protected by Thailand's Personal Data Protection Act (PDPA).

Create the folders and blank CSV templates with `make init` (or `python -m tbg init`) and track coverage with
`make status`. Every CSV in a folder is read, so manual files can be added next to downloaded ones (`manual_2.csv`).

| Step | Data | How to get it | Destination (under `work/`) |
|---|---|---|---|
| 1 | Listed companies (SET + mai) | `python -m tbg collect set-universe`; if the download is refused, save the Excel list from the SET website and add market capitalisation from SETSMART | `data/raw/universe/` |
| 2 | Top-10 shareholders | Best: a SETSMART export (many university libraries subscribe). Otherwise key them from the SET website into the template. `collect set-shareholders` is experimental and may be refused | `data/raw/shareholders/` |
| 3 | Form 56-1 One Report (PDF) | URLs in `data/manual/document_urls.csv`, then `python -m tbg collect documents`; or download by hand as `TICKER_YEAR_LANG.pdf`, e.g. `CPALL_2025_en.pdf` | `data/raw/documents/one_report/` |
| 4 | DBD BOJ.5 shareholder lists of private holding companies | Request certified copies from the Department of Business Development (fee). Order them by `review/dbd_priority_queue.csv`, which ranks companies that control the most firms with unknown owners | `data/raw/documents/boj5/` |
| 5 | Bank Pillar 3 reports | Bank websites, saved as `TICKER_YEAR.pdf` | `data/raw/documents/pillar3/` |
| 6 | Financial-institution licences | Bank of Thailand, SEC and OIC lists, keyed into `fi_licenses.csv` | `data/raw/fi/` |
| 7 | GLEIF legal entities and parents (free API) | `python -m tbg collect gleif` | `data/raw/gleif/` |

Tables in PDFs are extracted with Claude (`python -m tbg extract ...`, needs `ANTHROPIC_API_KEY`); rows with
confidence below 0.8 go to `review/llm_<kind>_check.csv`. See the [Thai guide](guide_th.md) for the full workflow.

**Terms of use.** Read each website's terms before collecting data, put your e-mail in `collect.user_agent` in
`config.yaml`, and do not lower `collect.delay_seconds`.

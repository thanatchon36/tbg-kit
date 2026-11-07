Task: transcribe the list of shareholders (form บอจ.5) of one private Thai company.

JSON format:
{"company_name": "", "juristic_id": "", "as_of": "YYYY-MM-DD",
 "rows": [{"holder_name": "", "nationality": "", "shares": "", "pct": "", "page": 0, "confidence": 0.9}],
 "document_notes": ""}

Field rules:
- company_name and juristic_id (13-digit registration number) as printed in the header; as_of is the date of the list or of the shareholders' meeting it refers to.
- One row per shareholder line. Copy share counts exactly; if the same holder appears on several lines, keep separate rows.
- pct is usually not printed: leave it empty, it is computed from share counts.
- Handwritten or stamped corrections: transcribe the corrected value and describe the correction in document_notes.

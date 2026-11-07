Task: list the companies in the bank's financial business group (the scope of consolidated supervision) as disclosed in the Pillar 3 report.

JSON format:
{"as_of": "YYYY-MM-DD",
 "rows": [{"entity_name": "", "relationship": "subsidiary", "pct": "", "country": "", "business": "", "page": 0, "confidence": 0.9}],
 "document_notes": ""}

Field rules:
- relationship: parent | subsidiary | associate | other, as described in the report. Include the parent company of the financial group when the report names it.
- pct: the group's shareholding when printed; otherwise empty.
- business: the activity printed (banking, securities, asset management, leasing, insurance, card, technology).

Task: list the members of the board of directors of the reporting company at the end of the reporting period.

JSON format:
{"as_of": "YYYY-MM-DD",
 "rows": [{"person_name": "", "position": "", "page": 0, "confidence": 0.95}],
 "document_notes": ""}

Field rules:
- person_name exactly as printed, including the title (Mr., Mrs., Dr., นาย, นาง, นางสาว, ม.ร.ว., military or police ranks).
- position as printed, e.g. Chairman, Vice Chairman, Independent Director, Executive Director, Audit Committee Chairman.
- Board members only. Exclude executives who are not directors. Directors who joined or left during the year: include only those in office at the end of the period and mention the others in document_notes.

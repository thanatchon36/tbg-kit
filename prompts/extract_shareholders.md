Task: list the major shareholders (usually the top 10) of the reporting company itself, as of the record or book-closing date stated in the document.

JSON format:
{"as_of": "YYYY-MM-DD",
 "rows": [{"rank": 1, "holder_name": "", "shares": "", "pct": "", "group_note": "", "page": 0, "confidence": 0.95}],
 "document_notes": ""}

Field rules:
- If the document groups holders under a heading (for example "กลุ่มครอบครัว..." or "... Group") and lists members underneath, output every member as its own row and copy the heading into group_note. If only the group total is printed, output the group as one row.
- Keep Thai NVDR Co., Ltd., custodian and nominee accounts, and funds as ordinary rows; they are classified later.
- Do not list shareholders of subsidiaries.

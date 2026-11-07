Task: list every subsidiary, associate, joint venture and other investee shown in the group's shareholding-structure section ("โครงสร้างการถือหุ้นของกลุ่มบริษัท") or in the financial-statement note on investments in subsidiaries, associates and joint ventures of the reporting company.

JSON format:
{"fiscal_year": "2025",
 "rows": [{"entity_name": "", "entity_name_alt": "", "relationship": "subsidiary", "immediate_parent": "",
           "pct_direct": "", "pct_effective": "", "country": "", "business": "", "page": 0, "confidence": 0.95, "note": ""}],
 "document_notes": ""}

Field rules:
- entity_name: as printed. entity_name_alt: the name in the other language when the table gives both.
- relationship: subsidiary | associate | joint_venture | other, as the document classifies it. If it does not classify, use subsidiary above 50%, associate from 20% to 50%, other below 20%.
- immediate_parent: the company that holds the shares directly, when the document shows an indirect holding (a "held by" or "held through" column, indentation under another company, an arrow in a chart). Leave empty when the reporting company holds the shares itself.
- pct_direct: the percentage held by the immediate parent (or by the reporting company when immediate_parent is empty). pct_effective: the group's effective interest, when shown separately. If the table has a single percentage labelled as the company's interest "directly and indirectly", put it in pct_effective and leave pct_direct empty.
- When columns show two years, use the latest year and set fiscal_year to it.
- country: ISO 3166 two-letter code from a country column or the name, e.g. "(Vietnam)" -> VN, Thailand -> TH. Empty if not stated.
- business: the short business description printed for the entity, if any.
- Do not list the reporting company itself, portfolio investments shown only as financial assets, or totals.

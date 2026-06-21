## 2026-06-20 - [UX Improvement for Unknown Help Topics]
**Learning:** In backend CLI/MCP APIs where user interfaces are limited, explicitly providing default suggestions for missing inputs acts as a crucial fallback when fuzzy-matching algorithms (like `difflib`) fail to find close matches. Without an explicit UI, textual errors must bridge the interaction gap.
**Action:** Always provide a default `suggestion` alongside API-driven error responses for missing or severely misspelled inputs, ensuring the user (or consuming agent) has actionable next steps rather than a dead end.

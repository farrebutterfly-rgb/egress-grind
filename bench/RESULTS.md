# Results

Leaked personnummer per disguise (lower is better). 40 synthetic cases per row.

| disguise | svenska-pii | egress-grind | presidio | presidio-patterns | llm-guard |
|---|---|---|---|---|---|
| plain | 0/40 | 0/40 | 0/40 | 0/40 | 39/40 |
| plain_12 | 0/40 | 0/40 | 0/40 | 0/40 | 40/40 |
| spaced | 40/40 | 0/40 | 3/40 | 5/40 | 39/40 |
| dotted | 40/40 | 0/40 | 0/40 | 0/40 | 0/40 |
| fullwidth | 40/40 | 0/40 | 5/40 | 5/40 | 39/40 |
| zero_width | 40/40 | 0/40 | 6/40 | 6/40 | 0/40 |
| fullwidth_spaced | 40/40 | 0/40 | 1/40 | 8/40 | 40/40 |
| base64_tool_arg | 40/40 | 0/40 | 33/40 | 40/40 | 40/40 |
| spelled_words | 40/40 | 0/40 | 8/40 | 40/40 | 29/40 |
| homoglyph | 40/40 | 0/40 | 30/40 | 39/40 | 40/40 |
| hex_tool_arg | 40/40 | 0/40 | 33/40 | 40/40 | 32/40 |
| split_halves | 40/40 | 0/40 | 0/40 | 0/40 | 40/40 |
| split_no_cue | 40/40 | 32/40 | 0/40 | 0/40 | 40/40 |
| **total leaked** | **440/520** | **32/520** | **119/520** | **183/520** | **418/520** |

Clean text that was blocked or changed (false positives, lower is better).

| look-alike | svenska-pii | egress-grind | presidio | presidio-patterns | llm-guard |
|---|---|---|---|---|---|
| invalid_check_digit | 1/40 | 1/40 | 40/40 | 40/40 | 0/40 |
| order_number | 0/40 | 0/40 | 32/40 | 0/40 | 2/40 |
| date | 0/40 | 0/40 | 40/40 | 40/40 | 2/40 |
| amount | 0/40 | 0/40 | 30/40 | 0/40 | 1/40 |
| base64_plain_text | 0/40 | 0/40 | 28/40 | 0/40 | 0/40 |
| short_spaced_digits | 0/40 | 0/40 | 27/40 | 1/40 | 5/40 |
| six_then_four | 0/40 | 0/40 | 40/40 | 40/40 | 0/40 |
| date_six_then_four | 0/40 | 2/40 | 40/40 | 40/40 | 0/40 |
| product_code | 0/40 | 0/40 | 40/40 | 40/40 | 0/40 |
| **total** | **1/360** | **3/360** | **317/360** | **201/360** | **10/360** |

| system | configuration | median ms per text |
|---|---|---|
| svenska-pii | svenska-pii 0.1.0 | 0.03 |
| egress-grind | egress-grind 0.1.0 (mask mode) | 0.10 |
| presidio | presidio-analyzer 2.2.366 (en_core_web_lg NER + all pattern recognizers, + SE_PERSONNUMMER) | 7.08 |
| presidio-patterns | presidio-analyzer 2.2.366 (pattern recognizers only, NER removed, + SE_PERSONNUMMER) | 6.99 |
| llm-guard | llm-guard 0.3.16 (InvisibleText + Anonymize, defaults) | 154.10 |

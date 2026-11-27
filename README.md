# egress-grind

A fail-closed gateway between your code and a cloud language model. It stops or pseudonymises Swedish personal data before the request leaves, puts the real values back into the answer, and refuses to forward anything it could not scan.

It speaks the OpenAI chat completions API, so an existing client only changes its base URL.

```python
client = OpenAI(base_url="http://localhost:8080/v1")  # was https://api.openai.com/v1
```

Two questions decide whether a gateway like this works, and both are measured in `bench/`:

1. **Does it catch the number when it is disguised?** Models and agents write identifiers back with spaces, full-width digits, zero-width characters, in words, or base64 inside a tool argument. A scanner that only reads the plain text misses all of those.
2. **Can the person still be found after the number is gone?** "A 34-year-old woman in Arjeplog who works as a veterinarian" has no identifier in it and still points at very few people. The gateway counts how many people in Sweden match what is left, using SCB's own tables, and generalises until at least five do.

## Results

### Disguised personnummer

40 synthetic personnummer with valid check digits per row, in five kinds of Swedish text (case notes, customer messages, tool call JSON). A row counts as leaked if the text that would leave still contains the number in a form a model can read back. Full table, look-alikes and timings: [bench/RESULTS.md](bench/RESULTS.md).

| disguise | svenska-pii alone | **egress-grind** | Presidio, NER + patterns | Presidio, patterns only | LLM Guard, defaults |
|---|---|---|---|---|---|
| plain `850312-2387` | 0 | **0** | 0 | 0 | 39 |
| spaced `8 5 0 3 1 2 - 2 3 8 7` | 40 | **0** | 3 | 5 | 39 |
| full-width `８５０３１２－２３８７` | 40 | **0** | 5 | 5 | 39 |
| zero-width between digits | 40 | **0** | 6 | 6 | 0 |
| spelled out in Swedish words | 40 | **0** | 8 | 40 | 29 |
| base64 in a tool argument | 40 | **0** | 33 | 40 | 40 |
| hex in a tool argument | 40 | **0** | 33 | 40 | 32 |
| homoglyphs `85O3l2-2387` | 40 | **0** | 30 | 39 | 40 |
| split: `född 850312, sista fyra 2387` | 40 | **0** | 0 | 0 | 40 |
| split with no cue word | 40 | **32** | 0 | 0 | 40 |
| **all 13 disguises, leaked of 520** | 440 | **32** | 119 | 183 | 418 |
| **clean look-alikes changed, of 360** | 1 | **3** | 317 | 201 | 10 |

How to read it:

* Presidio's low leak count with NER comes from masking almost everything that looks like a number or a capitalised word. On Swedish text the English NER tags words like "Anteckning" as a person, and the US recognizers tag dates and order numbers. That is why it changes 317 of 360 clean texts. With NER removed it still changes 201, mostly through `US_DRIVER_LICENSE`, `PHONE_NUMBER` and `DATE_TIME`. Its Swedish recognizer itself validates the check digit correctly.
* LLM Guard's default Anonymize scanner has no Swedish personnummer recognizer, so it misses even the plain form. Its InvisibleText scanner is what stops the zero-width row.
* Both were run in the configuration a team would most likely deploy. The exact setup is in `bench/run.py`. They are not built for Swedish, and the comparison says that, not that they are bad tools.
* The one remaining gap that matters is a personnummer split in two with nothing around it that says what it is. Pairing every six-digit number with every four-digit number nearby would catch it, but roughly one pair in twenty passes the check digit and date test by chance, so pairing only happens near words like personnummer, född or sista fyra.

### Re-identification after masking

2000 synthetic people drawn from SCB's 2024 tables, one case note each with a synthetic personnummer and e-mail plus some of kommun, age, sex and occupation. The attacker holds a complete population register. Full breakdown: [bench/RELINK.md](bench/RELINK.md).

Notes that mention kommun, age, sex and occupation (191 notes):

| treatment | mean P(re-identified) | unique | fewer than 5 match | attributes kept exact |
|---|---|---|---|---|
| identifiers masked, nothing else (what a PII scanner does) | 0.216 | 8.4% | 31.9% | 100% |
| **egress-grind, k ≥ 5** | **0.063** | **0%** | **0%** | **91%** |
| fixed generalisation of everything (k-anonymity baseline) | 0.000 | 0% | 0% | 25% |

Across all 2000 notes egress-grind keeps 99% of the attributes exact and leaves no note with fewer than five matching people. The fixed baseline is safe too, but keeps 29%, which makes most notes useless to the model.

## What it does with a request

Every text the model would see is scanned: message content, content parts, tool results, and the arguments of earlier tool calls. Each text is read in its original form and in decoded views (Unicode folded, zero-width removed, spaced digits joined, Swedish number words turned into digits, homoglyphs mapped, base64 and hex decoded, split halves paired near a cue word).

| finding | outcome |
|---|---|
| nothing | forwarded unchanged |
| plain soft identifier (e-mail, phone) | replaced with `[email_1]`, forwarded, put back in the answer |
| plain hard identifier (personnummer, samordningsnummer, bank details) | `strict` (default): 403. `mask`: pseudonymised like the above |
| anything that only appears in a decoded view | 403 in every mode. A disguised identifier is a stronger signal than a plain one, and a base64 blob cannot be masked in place |
| fewer than k people in Sweden match what is left | generalised (exact age to a ten-year band, kommun to län, occupation removed); 403 if that is not enough, or if the messages together narrow it below k |
| an image or other part it cannot read | 403 |
| the scanner raises | 503. Nothing unscanned is ever forwarded |
| the provider cannot be reached | 502, logged |

Placeholders are restored in streamed answers too, including when a placeholder is split across chunks and inside streamed tool call arguments (JSON-escaped). The same value gets the same placeholder throughout a request, so the model can still reason about "the same customer".

Every decision is written to a hash-chained audit log: time, request id, outcome, entity types and counts, where in the request, upstream status. Never a value. `python -m egress_grind verify audit.jsonl` reports the first line that was edited, removed or reordered.

## Run it

```sh
uv sync
EGRESS_UPSTREAM=https://api.openai.com uv run uvicorn egress_grind.api:create_app --factory --port 8080
```

| variable | default | |
|---|---|---|
| `EGRESS_UPSTREAM` | `https://api.openai.com` | the real provider; any OpenAI-compatible endpoint |
| `EGRESS_MODE` | `strict` | `strict`, `mask` or `block` |
| `EGRESS_RELINK_K` | `5` | minimum number of matching people; `0` turns the check off |
| `EGRESS_AUDIT` | `audit.jsonl` | audit log path |
| `EGRESS_ALLOWLIST` | | values never treated as personal data, such as your own organisation number |

The `Authorization` header is passed through; the gateway holds no provider key.

## Reproduce

```sh
uv run pytest                                  # 39 tests
python bench/corpus.py > bench/corpus.jsonl    # deterministic, seeded
uv run python bench/run.py --system egress-grind
uv run python bench/run.py --system svenska-pii
uv run python bench/relink_bench.py
# Presidio and LLM Guard need their own environments (LLM Guard pins an older Presidio):
pip install presidio-analyzer en_core_web_lg && python bench/run.py --system presidio
pip install llm-guard && python bench/run.py --system llm-guard
python bench/report.py
```

## Limits

* The re-identification count with an occupation is an estimate. SCB publishes occupation per län, not per kommun, so the län's share for that age group and sex is applied to the kommun. Without an occupation the count is exact.
* The extractor knows kommun names after a preposition (`i`, `från`, `bor i`), ages written as `34 år`, `34-årig` or `född 1987`, sex from common nouns and pronouns, and 93 common job titles mapped to SSYK codes. A quasi-identifier written any other way is not counted, and the benchmark would show it as a miss.
* The model's answer is not scanned for new personal data; only placeholders are restored.
* A personnummer split across two separate messages is not paired.
* All test data is synthetic. No personnummer in this repository belongs to a real person.

## Data

`src/egress_grind/data/scb_2024.json.gz` holds two SCB tables, rebuilt by `scripts/fetch_scb.py`: folkmängd per kommun, one-year age and sex on 31 December 2024 (BE0101A), and employees per län, SSYK 2012 occupation, age group and sex in 2024 (AM0208C). SCB open data is CC0.

Detection of the identifiers themselves is [svenska-pii](https://github.com/farrebutterfly-rgb/svenska-pii).

## License

MIT

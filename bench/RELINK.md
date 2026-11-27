# Re-identification after masking

2000 synthetic people drawn from SCB 2024 tables, one case note each. Attacker holds the full population register. Lower re-identification is better, higher utility is better.

## all notes (2000 notes)

| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |
|---|---|---|---|---|
| identifiers-only | 0.024 | 0.8% | 3.1% | 100% |
| egress-grind (k>=5) | 0.009 | 0.0% | 0.0% | 99% |
| fixed-k-anon | 0.000 | 0.0% | 0.0% | 29% |

## kommun + ages + sex (609 notes)

| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |
|---|---|---|---|---|
| identifiers-only | 0.005 | 0.0% | 0.0% | 100% |
| egress-grind (k>=5) | 0.005 | 0.0% | 0.0% | 100% |
| fixed-k-anon | 0.000 | 0.0% | 0.0% | 33% |

## kommun + ages + sex + occupation (191 notes)

| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |
|---|---|---|---|---|
| identifiers-only | 0.216 | 8.4% | 31.9% | 100% |
| egress-grind (k>=5) | 0.063 | 0.0% | 0.0% | 91% |
| fixed-k-anon | 0.000 | 0.0% | 0.0% | 25% |

## kommun + sex + occupation (191 notes)

| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |
|---|---|---|---|---|
| identifiers-only | 0.009 | 0.0% | 0.5% | 100% |
| egress-grind (k>=5) | 0.008 | 0.0% | 0.0% | 100% |
| fixed-k-anon | 0.000 | 0.0% | 0.0% | 33% |

## kommun + ages (400 notes)

| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |
|---|---|---|---|---|
| identifiers-only | 0.002 | 0.0% | 0.0% | 100% |
| egress-grind (k>=5) | 0.002 | 0.0% | 0.0% | 100% |
| fixed-k-anon | 0.000 | 0.0% | 0.0% | 0% |

## ages + sex + occupation (187 notes)

| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |
|---|---|---|---|---|
| identifiers-only | 0.002 | 0.0% | 0.0% | 100% |
| egress-grind (k>=5) | 0.002 | 0.0% | 0.0% | 100% |
| fixed-k-anon | 0.000 | 0.0% | 0.0% | 33% |

Notes where the extractor missed an attribute that was in the text: 0/2000. Those attributes reached the attacker at full precision and are counted that way above.

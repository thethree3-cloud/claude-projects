# Deck builder eval results

| Variant | Cases | Valid 1st try (95% CI) | Valid | Budget used | Avg-deck overlap | Inclusion | Roles OK | $/deck | s/deck |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| baseline | 30 | 100% (89%-100%) | 100% | 89% | 59% | 38% | 93% | $0.000 | 0.0 |
| claude-haiku-5-5 | 30 (+1 err) | 83% (66%-93%) | 100% | 62% | 32% | 32% | 73% | $0.008 | 43.5 |
| claude-opus-5-5 | 30 | 93% (79%-98%) | 100% | 96% | 52% | 37% | 63% | $0.198 | 39.2 |
| claude-sonnet-5-5 | 30 | 73% (56%-86%) | 100% | 65% | 39% | 34% | 30% | $0.085 | 19.8 |

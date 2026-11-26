# Blind pairwise judge (claude-sonnet-5-5)

30 cases (10 commanders x 3 budgets), each judged twice with the deck order swapped. A deck wins a case only if it wins both orders.

| Outcome | Cases | Share (95% CI) |
|---|--:|--:|
| Claude (Opus 5.5) deck wins | 26 | 87% (70%-95%) |
| Baseline (no LLM) deck wins | 0 | 0% (0%-11%) |
| Split (orders disagree, or a tie) | 4 | 13% |

Position check: the deck shown first won 57% of decided calls (50% = no position bias).

| Mean score (1-10) | synergy | mana | interaction | card_flow | win_path |
|---|--:|--:|--:|--:|--:|
| Claude deck | 7.9 | 7.6 | 7.8 | 7.3 | 7.7 |
| Baseline deck | 7.5 | 7.2 | 6.5 | 6.9 | 6.8 |

Judge cost: $1.52.

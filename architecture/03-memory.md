# 03 · Memory — episodic / semantic / procedural

Memory is what makes each research run smarter than the last, without re-deriving what's known.

## The three kinds
| Kind | Holds | In the loop |
|---|---|---|
| **Episodic** | run history — variants tried, their results, scores | steer the proposer toward the best-so-far (exploit) |
| **Semantic** | distilled "what kinds of variants tend to win" | bias the sampling prior over the parameter space |
| **Procedural** | learned heuristics / rules that worked | injected into the proposer's instructions |

## Design
- **Reference build (Tier-1):** episodic best-so-far — the proposer perturbs the top variant
  (exploit) while keeping ≥1 fresh sample per batch (explore). Deterministic and dependency-free.
- **Production:** semantic + procedural layers over **SQLite + `sqlite-vec`** (start simple, local,
  fast; graduate to OpenSearch only when multi-tenant/scale demands it — *simplest thing that works*).

## Decisions (ADR lens)
| Decision | Why / trade-off |
|---|---|
| SQLite + sqlite-vec vs a managed vector store | zero infra, local, fast to iterate; upgrade path is mechanical |
| Exploit + explore split | memory that only exploits gets stuck in a local optimum |
| Externalized memory (not in-context) | agents stay stateless/restartable; memory is a checkpointable store |

## Cost / latency
Memory reads/writes are cheap and off the hot path. The value is **fewer wasted backtests** — the
loop converges faster because it stops re-testing what already lost.
</content>

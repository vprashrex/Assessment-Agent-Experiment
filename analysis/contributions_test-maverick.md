# test-maverick — n=998, k=4, scorer=gemini-3.1-flash-lite-preview

## Per-metric contribution to the overall std

Overall avg std is the unweighted mean of the 5 per-metric std, so the split below is an identity, not a model: each metric carries weight 1/5 and the contributions sum to the overall move exactly.

Noise floor: **±0.022** per metric, from assurance re-score. 5 deltas over 1 re-score pair(s) (v3 r3↔r6), largest |Δ| 0.035. With only 5 deltas the floor is itself uncertain to roughly ±0.007, so treat it as an order of magnitude, not a threshold to test against.

**round 1: v1 vs parent v0 [kept]** — overall avg std moved -0.018 (noise floor ±0.022; 3/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Sustainability | 0.520 | 0.426 | -0.094 | -0.019 | 104% | 33% | 60% | better |
| Scalability | 0.550 | 0.459 | -0.091 | -0.018 | 101% | 32% | 72% | better |
| Feasibility | 0.453 | 0.449 | -0.004 | -0.001 | 4% | 1% | 16% | noise |
| Usefulness | 0.327 | 0.358 | +0.031 | +0.006 | -34% | 11% | -19% | weak |
| Novelty | 0.181 | 0.249 | +0.068 | +0.014 | -76% | 24% | -29% | worse |
| **sum** | | | -0.090 | **-0.018** | 100% | 100% | 100% | |

residual vs the reported aggregate: +0.00000  
⚠ variance-based ranking differs (Scalability < Sustainability < Feasibility < Usefulness < Novelty) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**round 2: v2 vs parent v1 [rejected]** — overall avg std moved +0.043 (noise floor ±0.022; 2/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Scalability | 0.459 | 0.475 | +0.016 | +0.003 | 8% | 8% | 9% | noise |
| Feasibility | 0.449 | 0.475 | +0.026 | +0.005 | 12% | 12% | 21% | weak |
| Sustainability | 0.426 | 0.454 | +0.028 | +0.006 | 13% | 13% | 11% | weak |
| Usefulness | 0.358 | 0.407 | +0.049 | +0.010 | 23% | 23% | 11% | worse |
| Novelty | 0.249 | 0.344 | +0.095 | +0.019 | 44% | 44% | 47% | worse |
| **sum** | | | +0.214 | **+0.043** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00020  
⚠ variance-based ranking differs (Scalability < Sustainability < Usefulness < Feasibility < Novelty) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.

**round 3: v3 vs parent v1 [kept]** — overall avg std moved -0.008 (noise floor ±0.022; 0/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Feasibility | 0.449 | 0.414 | -0.035 | -0.007 | 83% | 34% | 56% | weak |
| Scalability | 0.459 | 0.431 | -0.028 | -0.006 | 67% | 27% | 88% | weak |
| Sustainability | 0.426 | 0.416 | -0.010 | -0.002 | 24% | 10% | 76% | noise |
| Novelty | 0.249 | 0.253 | +0.004 | +0.001 | -10% | 4% | 32% | noise |
| Usefulness | 0.358 | 0.385 | +0.027 | +0.005 | -64% | 26% | -152% | weak |
| **sum** | | | -0.042 | **-0.008** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00040  
⚠ variance-based ranking differs (Scalability < Sustainability < Feasibility < Novelty < Usefulness) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**round 4: v4 vs parent v3 [rejected]** — overall avg std moved +0.021 (noise floor ±0.022; 1/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Novelty | 0.253 | 0.230 | -0.023 | -0.005 | -21% | 15% | -12% | weak |
| Usefulness | 0.385 | 0.395 | +0.010 | +0.002 | 9% | 6% | 0% | noise |
| Feasibility | 0.414 | 0.450 | +0.036 | +0.007 | 33% | 23% | 58% | weak |
| Scalability | 0.431 | 0.471 | +0.040 | +0.008 | 37% | 26% | 24% | weak |
| Sustainability | 0.416 | 0.461 | +0.045 | +0.009 | 42% | 29% | 29% | worse |
| **sum** | | | +0.108 | **+0.022** | 100% | 100% | 100% | |

residual vs the reported aggregate: +0.00060  
⚠ variance-based ranking differs (Novelty < Usefulness < Scalability < Sustainability < Feasibility) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**round 5: v5 vs parent v3 [rejected]** — overall avg std moved +0.006 (noise floor ±0.022; 0/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Sustainability | 0.416 | 0.399 | -0.017 | -0.003 | -55% | 25% | -9% | noise |
| Scalability | 0.431 | 0.429 | -0.002 | -0.000 | -6% | 3% | -10% | noise |
| Feasibility | 0.414 | 0.422 | +0.008 | +0.002 | 26% | 12% | 52% | noise |
| Novelty | 0.253 | 0.262 | +0.009 | +0.002 | 29% | 13% | 5% | noise |
| Usefulness | 0.385 | 0.418 | +0.033 | +0.007 | 106% | 48% | 62% | weak |
| **sum** | | | +0.031 | **+0.006** | 100% | 100% | 100% | |

residual vs the reported aggregate: +0.00020  
⚠ variance-based ranking differs (Scalability < Sustainability < Novelty < Feasibility < Usefulness) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**round 6: re-score of v3 vs its own round 3** — overall avg std moved +0.013 (noise floor ±0.022; 0/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Usefulness | 0.385 | 0.373 | -0.012 | -0.002 | -19% | 12% | -5% | noise |
| Novelty | 0.253 | 0.247 | -0.006 | -0.001 | -9% | 6% | -6% | noise |
| Sustainability | 0.416 | 0.438 | +0.022 | +0.004 | 34% | 22% | 26% | noise |
| Scalability | 0.431 | 0.456 | +0.025 | +0.005 | 39% | 25% | 32% | weak |
| Feasibility | 0.414 | 0.449 | +0.035 | +0.007 | 55% | 35% | 53% | weak |
| **sum** | | | +0.064 | **+0.013** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00020  
⚠ variance-based ranking differs (Novelty < Usefulness < Sustainability < Scalability < Feasibility) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**cumulative: v0 (round 0) → v3 (round 6)** — overall avg std moved -0.013 (noise floor ±0.022; 4/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Scalability | 0.550 | 0.456 | -0.094 | -0.019 | 138% | 32% | 105% | better |
| Sustainability | 0.520 | 0.438 | -0.082 | -0.016 | 121% | 28% | 88% | better |
| Feasibility | 0.453 | 0.449 | -0.004 | -0.001 | 6% | 1% | -4% | noise |
| Usefulness | 0.327 | 0.373 | +0.046 | +0.009 | -68% | 16% | -52% | worse |
| Novelty | 0.181 | 0.247 | +0.066 | +0.013 | -97% | 23% | -36% | worse |
| **sum** | | | -0.068 | **-0.014** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00060  
⚠ variance-based ranking differs (Scalability < Sustainability < Feasibility < Novelty < Usefulness) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**cumulative: v0 → v3** — is the drop agreement or a shrinking scale? within/between = sqrt((1-ICC)/ICC) is scale-free.

| metric | Δ mean score | Δ within-std | within/between | → | Δ | reading |
|---|---|---|---|---|---|---|
| Novelty | +0.19 | +0.066 | 0.1601 | 0.1634 | +0.0033 | worse |
| Usefulness | -0.27 | +0.046 | 0.1697 | 0.1534 | -0.0163 | noisier but more discriminating |
| Feasibility | -0.76 | -0.004 | 0.2120 | 0.1534 | -0.0585 | real gain |
| Scalability | -0.72 | -0.094 | 0.2929 | 0.1876 | -0.1053 | real gain |
| Sustainability | -1.54 | -0.082 | 0.2701 | 0.2041 | -0.0660 | real gain |

# test-agent-1 — n=996, k=4, scorer=gemini-3.1-flash-lite-preview

## Per-metric contribution to the overall std

Overall avg std is the unweighted mean of the 5 per-metric std, so the split below is an identity, not a model: each metric carries weight 1/5 and the contributions sum to the overall move exactly.

Noise floor: **±0.012** per metric, from assurance re-score. 5 deltas over 1 re-score pair(s) (v5 r5↔r7), largest |Δ| 0.019. With only 5 deltas the floor is itself uncertain to roughly ±0.004, so treat it as an order of magnitude, not a threshold to test against.

**round 1: v1 vs parent v0 [kept]** — overall avg std moved -0.042 (noise floor ±0.012; 4/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Scalability | 0.541 | 0.400 | -0.141 | -0.028 | 67% | 44% | 44% | better |
| Feasibility | 0.464 | 0.386 | -0.078 | -0.016 | 37% | 24% | 38% | better |
| Sustainability | 0.526 | 0.478 | -0.048 | -0.010 | 23% | 15% | 23% | better |
| Usefulness | 0.348 | 0.366 | +0.018 | +0.004 | -9% | 6% | -1% | weak |
| Novelty | 0.183 | 0.222 | +0.039 | +0.008 | -19% | 12% | -5% | worse |
| **sum** | | | -0.210 | **-0.042** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00000

**round 2: v2 vs parent v1 [rejected]** — overall avg std moved -0.015 (noise floor ±0.012; 4/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Sustainability | 0.478 | 0.301 | -0.177 | -0.035 | 227% | 62% | -293% | better |
| Usefulness | 0.366 | 0.362 | -0.004 | -0.001 | 5% | 1% | 14% | noise |
| Scalability | 0.400 | 0.430 | +0.030 | +0.006 | -38% | 11% | 104% | worse |
| Novelty | 0.222 | 0.252 | +0.030 | +0.006 | -38% | 11% | 64% | worse |
| Feasibility | 0.386 | 0.429 | +0.043 | +0.009 | -55% | 15% | 211% | worse |
| **sum** | | | -0.078 | **-0.016** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00060  
⚠ variance-based ranking differs (Sustainability < Usefulness < Novelty < Scalability < Feasibility) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.

**round 3: v3 vs parent v1 [rejected]** — overall avg std moved +0.025 (noise floor ±0.012; 2/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Feasibility | 0.386 | 0.391 | +0.005 | +0.001 | 4% | 4% | 3% | noise |
| Scalability | 0.400 | 0.412 | +0.012 | +0.002 | 10% | 10% | 12% | noise |
| Usefulness | 0.366 | 0.384 | +0.018 | +0.004 | 15% | 15% | 8% | weak |
| Novelty | 0.222 | 0.255 | +0.033 | +0.007 | 27% | 27% | 9% | worse |
| Sustainability | 0.478 | 0.533 | +0.055 | +0.011 | 45% | 45% | 67% | worse |
| **sum** | | | +0.123 | **+0.025** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00040  
⚠ variance-based ranking differs (Feasibility < Usefulness < Novelty < Scalability < Sustainability) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.

**round 4: v4 vs parent v1 [kept]** — overall avg std moved -0.013 (noise floor ±0.012; 1/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Sustainability | 0.478 | 0.431 | -0.047 | -0.009 | 72% | 44% | 104% | better |
| Usefulness | 0.366 | 0.353 | -0.013 | -0.003 | 20% | 12% | 6% | weak |
| Feasibility | 0.386 | 0.373 | -0.013 | -0.003 | 20% | 12% | 8% | weak |
| Scalability | 0.400 | 0.387 | -0.013 | -0.003 | 20% | 12% | 4% | weak |
| Novelty | 0.222 | 0.243 | +0.021 | +0.004 | -32% | 20% | -22% | weak |
| **sum** | | | -0.065 | **-0.013** | 100% | 100% | 100% | |

residual vs the reported aggregate: +0.00000  
⚠ variance-based ranking differs (Sustainability < Feasibility < Usefulness < Scalability < Novelty) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.

**round 5: v5 vs parent v4 [kept]** — overall avg std moved -0.001 (noise floor ±0.012; 0/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Usefulness | 0.353 | 0.348 | -0.005 | -0.001 | 56% | 29% | -46% | noise |
| Novelty | 0.243 | 0.239 | -0.004 | -0.001 | 44% | 24% | 38% | noise |
| Sustainability | 0.431 | 0.428 | -0.003 | -0.001 | 33% | 18% | 92% | noise |
| Scalability | 0.387 | 0.386 | -0.001 | -0.000 | 11% | 6% | 38% | noise |
| Feasibility | 0.373 | 0.377 | +0.004 | +0.001 | -44% | 24% | -23% | noise |
| **sum** | | | -0.009 | **-0.002** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00080  
⚠ variance-based ranking differs (Sustainability < Novelty < Scalability < Feasibility < Usefulness) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**round 6: v6 vs parent v5 [rejected]** — overall avg std moved +0.021 (noise floor ±0.012; 2/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Feasibility | 0.377 | 0.389 | +0.012 | +0.002 | 11% | 11% | 16% | noise |
| Usefulness | 0.348 | 0.362 | +0.014 | +0.003 | 13% | 13% | 2% | weak |
| Novelty | 0.239 | 0.257 | +0.018 | +0.004 | 17% | 17% | 14% | weak |
| Scalability | 0.386 | 0.413 | +0.027 | +0.005 | 26% | 26% | 22% | worse |
| Sustainability | 0.428 | 0.463 | +0.035 | +0.007 | 33% | 33% | 45% | worse |
| **sum** | | | +0.106 | **+0.021** | 100% | 100% | 100% | |

residual vs the reported aggregate: +0.00020  
⚠ variance-based ranking differs (Usefulness < Novelty < Feasibility < Scalability < Sustainability) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.

**round 7: re-score of v5 vs its own round 5** — overall avg std moved +0.009 (noise floor ±0.012; 0/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Sustainability | 0.428 | 0.428 | +0.000 | +0.000 | 0% | 0% | -32% | noise |
| Feasibility | 0.377 | 0.379 | +0.002 | +0.000 | 4% | 4% | 4% | noise |
| Scalability | 0.386 | 0.396 | +0.010 | +0.002 | 21% | 21% | 12% | noise |
| Usefulness | 0.348 | 0.365 | +0.017 | +0.003 | 35% | 35% | 60% | weak |
| Novelty | 0.239 | 0.258 | +0.019 | +0.004 | 40% | 40% | 56% | weak |
| **sum** | | | +0.048 | **+0.010** | 100% | 100% | 100% | |

residual vs the reported aggregate: +0.00060  
⚠ variance-based ranking differs (Sustainability < Feasibility < Scalability < Novelty < Usefulness) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.  
⚠ the overall move is inside the noise floor: attributing it to any metric is over-reading.

**cumulative: v0 (round 0) → v5 (round 7)** — overall avg std moved -0.047 (noise floor ±0.012; 4/5 metrics beyond it)

| metric | from | to | Δ metric | contribution | share | churn | by variance | vs noise |
|---|---|---|---|---|---|---|---|---|
| Scalability | 0.541 | 0.396 | -0.145 | -0.029 | 61% | 34% | 42% | better |
| Sustainability | 0.526 | 0.428 | -0.098 | -0.020 | 42% | 23% | 33% | better |
| Feasibility | 0.464 | 0.379 | -0.085 | -0.017 | 36% | 20% | 36% | better |
| Usefulness | 0.348 | 0.365 | +0.017 | +0.003 | -7% | 4% | -4% | weak |
| Novelty | 0.183 | 0.258 | +0.075 | +0.015 | -32% | 18% | -8% | worse |
| **sum** | | | -0.236 | **-0.047** | 100% | 100% | 100% | |

residual vs the reported aggregate: -0.00020  
⚠ variance-based ranking differs (Scalability < Feasibility < Sustainability < Usefulness < Novelty) — mean-of-std is not variance-additive, so treat the std ordering as the weaker claim.

**cumulative: v0 → v5** — is the drop agreement or a shrinking scale? within/between = sqrt((1-ICC)/ICC) is scale-free.

| metric | Δ mean score | Δ within-std | within/between | → | Δ | reading |
|---|---|---|---|---|---|---|
| Novelty | +0.25 | +0.075 | 0.1500 | 0.1666 | +0.0166 | worse |
| Usefulness | -0.49 | +0.017 | 0.1697 | 0.1666 | -0.0031 | noisier but more discriminating |
| Feasibility | -1.14 | -0.085 | 0.2041 | 0.1601 | -0.0440 | real gain |
| Scalability | -1.41 | -0.145 | 0.2658 | 0.2171 | -0.0488 | real gain |
| Sustainability | -1.94 | -0.098 | 0.2593 | 0.2389 | -0.0204 | real gain |

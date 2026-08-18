# Fellegi–Sunter composite calibration

m-sample: **2,901** editor-marked quotations (+1,200 held out, seed 0); u-sample: **1,646,732** control pairs over 3,000,128 words / 474,021 windows, collected through `chain>=2 bits>=10` — the null is truncated below that gate and E-values there are unsupported.

Fields: `run + chain + bits + offset_peak + formula` (lemma_run collapsed into chain; Winkler).

## Field weights

### run

| bin | weight (bits of evidence) |
|---|---|
| <1 | -0.66 |
| 1-2 | -2.84 |
| 2-3 | -0.05 |
| 3-4 | +3.77 |
| 4-6 | +8.56 |
| >=6 | +16.40 |

### chain

| bin | weight (bits of evidence) |
|---|---|
| <2 | +18.10 |
| 2-3 | -1.95 |
| 3-4 | -2.05 |
| 4-5 | -0.82 |
| 5-6 | +1.01 |
| 6-7 | +3.25 |
| 7-8 | +5.92 |
| 8-10 | +9.68 |
| >=10 | +19.34 |

### bits

| bin | weight (bits of evidence) |
|---|---|
| <5 | +17.67 |
| 5-10 | +18.49 |
| 10-15 | -2.61 |
| 15-20 | -0.59 |
| 20-25 | +1.84 |
| 25-30 | +4.83 |
| 30-35 | +7.38 |
| 35-40 | +9.53 |
| 40-50 | +11.41 |
| 50-60 | +13.33 |
| >=60 | +17.60 |

### offset_peak

| bin | weight (bits of evidence) |
|---|---|
| <0.25 | +1.25 |
| 0.25-0.5 | -0.89 |
| 0.5-0.75 | -0.49 |
| 0.75-0.9 | +7.63 |
| >=0.9 | +0.17 |

### formula

| bin | weight (bits of evidence) |
|---|---|
| <1 | -0.02 |
| >=1 | +2.40 |

## Thresholds

| zone | threshold | operating point |
|---|---|---|
| accept | ≥ +14.72 | ≤ 0 expected false links per control window; held-out POD 37.2% |
| reject | < -2.18 | ≤ 5% of held-out gold lost |
| review | between | the clerical zone, 1969's own |

## Threshold curve

| composite ≥ | POD (held-out) | PFA (per control window) |
|---|---|---|
| -10 | 100.0% | 3.473964 |
| -8 | 100.0% | 3.473964 |
| -6 | 100.0% | 3.473964 |
| -4 |  98.2% | 1.260866 |
| -2 |  94.8% | 0.408727 |
| +0 |  90.3% | 0.112991 |
| +2 |  84.2% | 0.021953 |
| +4 |  79.8% | 0.005966 |
| +6 |  76.0% | 0.001928 |
| +8 |  70.8% | 0.000608 |
| +10 |  64.2% | 0.000213 |
| +12 |  55.2% | 0.000072 |
| +14 |  42.8% | 0.000015 |
| +16 |   0.0% | 0.000000 |
| +18 |   0.0% | 0.000000 |
| +20 |   0.0% | 0.000000 |
| +22 |   0.0% | 0.000000 |
| +24 |   0.0% | 0.000000 |

## Calibration reliability

Does a reported weight behave like its magnitude? A composite of +10 bits *claims* the evidence is 2^10 more likely under m than u; the observed column is what the held-out data actually paid. Cllr is the forensic summary (0 = perfect, 1 = useless); the ECE line is the count-weighted mean gap.

**Read the bounds, not the gaps, where a bin is empty on one side.** With 1200 held-out marks against 1,646,732 control pairs, a bin holding no control hits cannot show an observed ratio above its smoothing ceiling however good the evidence is, and a bin holding no marks cannot show one below its floor. Those rows are marked `bound` and excluded from the ECE, because scoring them as miscalibration would be this table telling the exact kind of lie it exists to catch.

Cllr = **0.253**

| score bin | held-out m | u (control) | observed bits | claimed bits | gap |
|---|---|---|---|---|---|
| -8..-4 | 22 | 1,049,055 | -5.1 | -6.0 | +0.9 |
| -4..+0 | 94 | 544,117 | -2.1 | -2.0 | -0.1 |
| +0..+4 | 127 | 50,732 | +1.8 | +2.0 | -0.2 |
| +4..+8 | 108 | 2,540 | +5.9 | +6.0 | -0.1 |
| +8..+12 | 186 | 254 | +10.0 | +10.0 | -0.0 |
| +12..+16 | 663 | 34 | +14.7 | +14.0 | +0.7 |

ECE over the 6 resolved bins (count-weighted mean |gap|) = **0.61 bits**

*`offset_peak` note: the m-side measures it on the editor-marked span, the live scan on its own matched window -- a train/serve skew that flattens the field's weight rather than inflating it; stated so nobody reads the weight as an upper bound.*

*The artifact is the interface: `Searcher(composite=...)` reports `composite` and `e_value` on every graded match, and nothing here changes what any gate admits. Under a v2 artifact the calibrated decision statistic is `verified_odds` -- the composite plus the verification stage's terms.*
# Fellegi–Sunter composite calibration

m-sample: **2,901** editor-marked quotations (+1,200 held out, seed 0); u-sample: **1,653,902** control pairs over 3,000,128 words / 474,021 windows, collected through `chain>=2 bits>=10` — the null is truncated below that gate and E-values there are unsupported.

Fields: `run + chain + bits + offset_peak + formula` (lemma_run collapsed into chain; Winkler).

## Field weights

### run

| bin | weight (bits of evidence) |
|---|---|
| <1 | -0.65 |
| 1-2 | -2.84 |
| 2-3 | -0.05 |
| 3-4 | +3.78 |
| 4-6 | +8.58 |
| >=6 | +16.40 |

### chain

| bin | weight (bits of evidence) |
|---|---|
| <2 | +18.11 |
| 2-3 | -1.95 |
| 3-4 | -2.05 |
| 4-5 | -0.82 |
| 5-6 | +1.02 |
| 6-7 | +3.25 |
| 7-8 | +5.92 |
| 8-10 | +9.70 |
| >=10 | +19.34 |

### bits

| bin | weight (bits of evidence) |
|---|---|
| <5 | +17.67 |
| 5-10 | +18.49 |
| 10-15 | -2.60 |
| 15-20 | -0.60 |
| 20-25 | +1.81 |
| 25-30 | +4.81 |
| 30-35 | +7.36 |
| 35-40 | +9.57 |
| 40-50 | +11.47 |
| 50-60 | +13.34 |
| >=60 | +17.61 |

### offset_peak

| bin | weight (bits of evidence) |
|---|---|
| <0.25 | +1.30 |
| 0.25-0.5 | -0.80 |
| 0.5-0.75 | -0.47 |
| 0.75-0.9 | +7.80 |
| >=0.9 | +0.10 |

### formula

| bin | weight (bits of evidence) |
|---|---|
| <1 | -0.02 |
| >=1 | +2.41 |

## Thresholds

| zone | threshold | operating point |
|---|---|---|
| accept | ≥ +14.65 | ≤ 0 expected false links per control window; held-out POD 36.6% |
| reject | < -2.24 | ≤ 5% of held-out gold lost |
| review | between | the clerical zone, 1969's own |

## Threshold curve

| composite ≥ | POD (held-out) | PFA (per control window) |
|---|---|---|
| -10 | 100.0% | 3.489090 |
| -8 | 100.0% | 3.489090 |
| -6 | 100.0% | 3.489090 |
| -4 |  98.0% | 1.195242 |
| -2 |  94.8% | 0.404339 |
| +0 |  90.3% | 0.115803 |
| +2 |  84.2% | 0.021826 |
| +4 |  79.8% | 0.006103 |
| +6 |  76.0% | 0.001852 |
| +8 |  70.8% | 0.000593 |
| +10 |  65.1% | 0.000226 |
| +12 |  55.2% | 0.000070 |
| +14 |  43.3% | 0.000015 |
| +16 |   0.0% | 0.000000 |
| +18 |   0.0% | 0.000000 |
| +20 |   0.0% | 0.000000 |
| +22 |   0.0% | 0.000000 |
| +24 |   0.0% | 0.000000 |

## Calibration reliability

Does a reported weight behave like its magnitude? A composite of +10 bits *claims* the evidence is 2^10 more likely under m than u; the observed column is what the held-out data actually paid. Cllr is the forensic summary (0 = perfect, 1 = useless); the ECE line is the count-weighted mean gap.

**Read the bounds, not the gaps, where a bin is empty on one side.** With 1200 held-out marks against 1,653,902 control pairs, a bin holding no control hits cannot show an observed ratio above its smoothing ceiling however good the evidence is, and a bin holding no marks cannot show one below its floor. Those rows are marked `bound` and excluded from the ECE, because scoring them as miscalibration would be this table telling the exact kind of lie it exists to catch.

Cllr = **0.255**

| score bin | held-out m | u (control) | observed bits | claimed bits | gap |
|---|---|---|---|---|---|
| -8..-4 | 24 | 1,087,332 | -5.0 | -6.0 | +1.0 |
| -4..+0 | 92 | 511,677 | -2.0 | -2.0 | -0.0 |
| +0..+4 | 126 | 52,000 | +1.7 | +2.0 | -0.3 |
| +4..+8 | 109 | 2,612 | +5.9 | +6.0 | -0.1 |
| +8..+12 | 187 | 248 | +10.0 | +10.0 | +0.0 |
| +12..+16 | 662 | 33 | +14.7 | +14.0 | +0.7 |

ECE over the 6 resolved bins (count-weighted mean |gap|) = **0.66 bits**

*`offset_peak` note: the m-side measures it on the editor-marked span, the live scan on its own matched window -- a train/serve skew that flattens the field's weight rather than inflating it; stated so nobody reads the weight as an upper bound.*

*The artifact is the interface: `Searcher(composite=...)` reports `composite` and `e_value` on every graded match, and nothing here changes what any gate admits. Under a v2 artifact the calibrated decision statistic is `verified_odds` -- the composite plus the verification stage's terms.*
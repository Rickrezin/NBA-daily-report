# QCore prototype validation

Experimental only; not authorized for production C3/C4.

10 training games / 5 held-out games on November 2; Milwaukee November 4 is an external fixture. Each game stays in one split. No hyperparameter search; affine calibration uses only training labels. This is exploratory validation on two dates, not a prospective season test.

| Cohort / split | Metric | Rows | Calculable | MAE | RMSE | Bias | Maximum absolute error |
|---|---|---:|---:|---:|---:|---:|---:|
| espn_nov2/overall/all | q_offr | 334 | 318 | 0.390 | 1.388 | -0.143 | 21.426 |
| espn_nov2/overall/all | q_defr | 334 | 332 | 0.510 | 1.341 | -0.068 | 20.073 |
| espn_nov2/train/all | q_offr | 222 | 212 | 0.408 | 1.581 | -0.180 | 21.426 |
| espn_nov2/train/all | q_defr | 222 | 222 | 0.589 | 1.590 | -0.128 | 20.073 |
| espn_nov2/test/all | q_offr | 112 | 106 | 0.354 | 0.885 | -0.068 | 8.429 |
| espn_nov2/test/all | q_defr | 112 | 110 | 0.350 | 0.568 | 0.056 | 3.245 |
| espn_nov2/test/le8 | q_offr | 19 | 13 | 0.200 | 0.260 | -0.101 | 0.479 |
| espn_nov2/test/le8 | q_defr | 19 | 17 | 0.800 | 1.236 | 0.386 | 3.245 |
| espn_nov2/test/gt8 | q_offr | 93 | 93 | 0.376 | 0.940 | -0.063 | 8.429 |
| espn_nov2/test/gt8 | q_defr | 93 | 93 | 0.268 | 0.319 | -0.005 | 0.875 |
| espn_nov4/external_test/all | q_offr | 12 | 11 | 0.330 | 0.391 | -0.253 | 0.718 |
| espn_nov4/external_test/all | q_defr | 12 | 12 | 0.416 | 0.495 | 0.336 | 0.883 |
| archive_exact_minutes/overall/all | q_offr | 334 | 318 | 0.382 | 1.044 | -0.135 | 10.063 |
| archive_exact_minutes/overall/all | q_defr | 334 | 334 | 0.349 | 0.451 | -0.003 | 1.749 |
| nov4_exact_player_minutes/external_test/all | q_offr | 12 | 11 | 0.329 | 0.388 | -0.250 | 0.676 |
| nov4_exact_player_minutes/external_test/all | q_defr | 12 | 12 | 0.334 | 0.394 | 0.242 | 0.670 |

## Calibration comparison (held-out November 2)

| Metric | Raw MAE | Affine calibrated MAE |
|---|---:|---:|
| q_offr | 0.354 | 0.377 |
| q_defr | 0.350 | 0.521 |

The trained affine comparator worsens both held-out MAEs and is not used by inference.

## Largest residuals across November 2 (training and test explicitly labeled)

| Metric | Player | Game | Split | ESPN minutes | Prediction | BBRef | Residual |
|---|---|---|---|---:|---:|---:|---:|
| q_offr | Jaylin Sellers | 401909912 | train | 2 | 130.574 | 152 | -21.426 |
| q_offr | Jordan Clarkson | 401909910 | test | 11 | 125.571 | 134 | -8.429 |
| q_offr | Thomas Bryant | 401909907 | train | 5 | 65.806 | 71 | -5.194 |
| q_offr | Oscar Tshiebwe | 401909916 | train | 7 | 155.438 | 159 | -3.562 |
| q_offr | Corey Kispert | 401909909 | train | 18 | 106.149 | 109 | -2.851 |
| q_offr | Rayan Rupert | 401909912 | train | 2 | 213.160 | 211 | +2.160 |
| q_offr | Daniel Gafford | 401909913 | test | 26 | 164.367 | 166 | -1.633 |
| q_offr | Nickeil Alexander-Walker | 401909909 | train | 31 | 118.829 | 120 | -1.171 |
| q_defr | Bronny James | 401909921 | train | 1 | 42.927 | 63 | -20.073 |
| q_defr | Nick Richards | 401909921 | train | 1 | 118.401 | 125 | -6.599 |
| q_defr | Lawson Lovering | 401909921 | train | 1 | 103.414 | 108 | -4.586 |
| q_defr | Jae'Sean Tate | 401909916 | train | 2 | 90.030 | 86 | +4.030 |
| q_defr | Tobe Awaka | 401909912 | train | 2 | 108.692 | 112 | -3.308 |
| q_defr | Ebuka Okorie | 401909908 | test | 6 | 71.245 | 68 | +3.245 |
| q_defr | Isaac Jones | 401909908 | test | 6 | 69.133 | 66 | +3.133 |
| q_defr | Mike Conley | 401909916 | train | 4 | 112.460 | 110 | +2.460 |

## Limits and blockers

- All 334 archived identities and basic counting-stat lines reconcile to ESPN. 329 minute values differ because ESPN supplies whole minutes. The exact-minute diagnostic uses BBRef basics and is explicitly not independent ESPN inference.
- Positive appearances rounded to zero remain in results with null ratings. Non-positive estimated individual possessions produce null Q-OffR, including Jericho Sims in the external fixture (BBRef displays 0). These rows are counted in coverage, never silently dropped or assigned a league-average score.
- qAST can exceed its expected probability range in short stints. The published algebra is retained and flagged; no undocumented clipping convention is inferred from test labels. Jaylin Sellers and Jordan Clarkson remain offensive outliers.
- Bronny James has ESPN 1 minute versus archived 1:22. His raw defensive prediction changes from 42.927 to 64.382 with exact minutes; BBRef reports 63. Minute rounding does not explain every residual.
- Need more independent dates, precise automated minutes, validated zero-possession/qAST conventions and explicit approval of the scale before any C3/C4 adoption. C6 coverage is a separate unresolved source task.

Every row, derived feature, reference, flag and residual is in rows.json. metrics.json includes minute buckets, weighted MAE and calibration. manifest.json records source/code SHA-256 digests, training coefficients and exact game splits. The retained source captures enable offline replay.

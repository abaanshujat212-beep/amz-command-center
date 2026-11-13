# Verification confounding evidence

Each persisted verification horizon keeps its original status, outcome, metrics and date windows. A separate read-only classification checks for recorded changes to the same entity inside those exact windows.

The comparison intervals are half-open: `[window start, window end)`. Date boundaries persisted by the verification worker are interpreted at UTC midnight. A change at the shared baseline/after boundary belongs only to the after window. AXATY applied actions and rollback events, plus manual or Amazon-native `entity_change_signal` observations, are listed as evidence. Signal `expires_at` is a collision-detection lifetime, not the duration of an historical change, so confounding uses its recorded `observed_at` timestamp.

When an overlap exists the UI labels the horizon `CONFOUNDED` and says that metric movement cannot be attributed to the verified action. The stored result is not rewritten. Evidence is sorted deterministically and limited to the 20 most recent rows; the total and truncation state remain visible.

This first slice only evaluates recorded same-entity changes. It cannot identify unrecorded changes or effects from a parent campaign/ad group, and a clean result means only that no recorded same-entity event overlapped. It does not prove causation. Experiment registration and aggregated action-learning history remain later parts of issue #184.

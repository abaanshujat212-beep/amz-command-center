# Recommendation confidence

The rules runner scores evidence quality deterministically from volume,
freshness, variance stability, CPC stability, and evidence completeness. A
0–100 score, band, component values, and reason codes are attached to each
recommendation's evidence record. The existing recommendation contract stores
the normalized score in its `confidence` field in the range 0–1.

Missing volume or freshness reduces confidence; missing optional stability
measurements use a neutral factor, while malformed measurements reduce that
factor to zero. Blocked recommendations keep confidence at zero. A score below
75 requires human review in the expected-behavior contract. Bid recommendations
remain proposal-only in the optimizer run and continue through the existing
approval queue; confidence never applies an Amazon change.

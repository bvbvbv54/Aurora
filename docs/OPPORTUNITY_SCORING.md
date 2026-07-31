# AURORA Opportunity Scoring Engine

The scoring engine is invariant across Quick, Normal, Deep, and custom research profiles.
Profiles change evidence collection breadth only.

## Component weights

| Component | Weight | Main evidence |
|---|---:|---|
| Demand | 13% | Focus-video views relative to the first-page median |
| Competition | 12% | Verified-channel and 100K+ subscriber ratios |
| Small Creator Success | 12% | Channel size compared with achieved views |
| Evergreen | 10% | Upload age and newest-comment recency |
| Content Gap | 9% | Outdated results, weak titles, and simplified re-search validation |
| Thumbnail Weakness | 8% | Weak/unknown thumbnails among the first ten organic results |
| Search Intent | 10% | Explicit action/problem intent and reproducible production |
| Long-tail Precision | 8% | Specific query length and action/device modifiers |
| Buyer Intent | 8% | Commercial action language for High-RPM searches |
| Trend Persistence | 10% | Actual vidIQ free-extension video-history SVG curve |

The maximum component weight is 13%. No raw view count, channel attribute, or third-party
score can independently produce a Goldmine.

## vidIQ boundary

- vidIQ keyword **Volume**: excluded.
- vidIQ **Competition**: excluded.
- vidIQ video-history graph: sampled from the actual SVG curve shown in the free extension.
- Curve shapes: `increasing`, `recently increasing`, `historical growth, recent plateau`,
  `flat`, `declining`, or `unconfirmed`.
- VPH: audit-only with zero Opportunity Score weight.
- Matching Terms: recursion input only, never a scoring input.

## Classifications

- **Rejected**: final score below 40.
- **Potential**: 40–54.99.
- **Opportunity**: 55–69.99, or a higher numeric score missing confidence gates.
- **Goldmine**: score at least 70, six components at least 65, simplified re-search passed,
  Trend Persistence at least 60, and Evergreen at least 55.
- **GEMmine**: score at least 85, eight components at least 75, simplified re-search passed,
  Trend Persistence at least 80, Evergreen at least 75, Small Creator Success at least 75,
  and Content Gap at least 70.
- **Diamond**: the strict production-ready gate. It requires at least 10K views on an
  unverified sub-5K channel, an upload at least one year old, a newest comment within 90
  days, a low/default-frame thumbnail, a persistent or increasing VidIQ All-history curve,
  simplified re-search validation, adequate demand/competition components, and a
  reproducible fix that can be recorded in at most two minutes.

Every persisted score includes all ten component values, final score, classification,
simplified-validation result, collected evidence, and human-readable explanations.

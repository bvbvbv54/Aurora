# AURORA Opportunity Scoring Engine

The scoring engine is invariant across Quick, Normal, Deep, and custom research profiles.
Profiles change evidence collection breadth only.

## Component weights

| Component | Weight | Main evidence |
|---|---:|---|
| Demand | 10% | Focus-video views relative to the first-page median |
| Competition | 11% | Verified-channel and 100K+ subscriber ratios |
| Small Creator Success | 12% | Channel size compared with achieved views |
| Evergreen | 10% | Upload age and newest-comment recency |
| Content Gap | 9% | Outdated results, weak titles, and simplified re-search validation |
| Thumbnail Weakness | 7% | Weak/unknown thumbnails among the first ten organic results |
| Search Intent | 10% | Explicit action/problem intent and reproducible production |
| Long-tail Precision | 10% | Specific query length and action/device modifiers |
| Buyer Intent | 7% | Commercial action language for High-RPM searches |
| Trend Persistence | 10% | Actual vidIQ free-extension video-history SVG curve |
| VidIQ Volume | 4% | VidIQ search Volume, neutral when unavailable; multiplier capped |

The maximum component weight is 12%. No raw view count, channel attribute, or third-party
score can independently produce a Goldmine.

## vidIQ boundary

- vidIQ keyword **Volume**: 4% weight; unavailable is neutral at 50.
- vidIQ Volume multiplier: capped to +/-5 points inside the Volume component.
- vidIQ **Competition**: excluded.
- Optional vidIQ channel metrics: at most a +/-1.5 final-score modifier; unavailable is neutral.
- vidIQ video-history graph: sampled from the actual SVG curve shown in the free extension.
- Curve shapes: `increasing`, `recently increasing`, `historical growth, recent plateau`,
  `flat`, `declining`, or `unconfirmed`.
- VPH: audit-only with zero Opportunity Score weight.
- Matching Terms: recursion input only, never a scoring input.

## Classifications

- **Rejected**: final score below 40.
- **Potential**: 40–54.99.
- **Opportunity**: 55–69.99, or a higher numeric score missing confidence gates.
- **Goldmine**: score at least 72, five of the ten core components at least 65, simplified
  re-search, a sub-50K channel, at least 5K views, age of at least 180 days, evergreen proof,
  persistent trend, adequate demand/competition/content-gap signals, and reproducible
  production within five minutes.
- **GEMmine**: score at least 80, seven core components at least 65, simplified re-search,
  a sub-15K channel, at least 10K views, one-year age, a comment within 180 days, strong
  trend/demand/small-creator/content-gap evidence, and reproducible production.
- **Diamond**: score at least 86, seven core components at least 75, simplified re-search,
  at least 20K views on a sub-5K channel, one-year age, a comment within 90 days, and very
  strong trend, demand, competition, creator-success, and content-gap evidence.

Every persisted score includes all eleven component values, the optional channel modifier,
final score, classification,
simplified-validation result, collected evidence, and human-readable explanations.

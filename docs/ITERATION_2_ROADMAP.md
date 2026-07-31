# Aurora Iteration 2 Roadmap

This document records deferred work from the v2 architecture prompt. These items are
intentionally not wired in Iteration 1.

## 1. Preserve the certified query

Replace the title-derived Goldmine value:

```python
goldmine_keyword = strip_title(best_video.title)
```

with the query already certified by simplified re-search:

```python
goldmine_keyword = evidence.keyword
```

## 2. Wire problem-space follow-ups

After a Goldmine is confirmed, call `pain_point_followups()` and enqueue its output with
origin `pain_point_followup`, inherited pain-point context, prompt version `v2`, and the
next recursion depth. This is separate from the existing mobile suffix expansion.

## 3. Normalize and semantically deduplicate seeds

Add lowercase/punctuation/whitespace normalization and Jaccard token similarity. Reject
new seeds when their normalized form is already present or similarity to an existing seed
is at least `0.75`.

## Acceptance criteria

- Certified Goldmine reports use the actually validated query.
- Pain-point follow-ups remain inside the confirmed problem space.
- Exact and near-duplicate seeds do not consume browser sessions.
- Existing v1 records and reports remain readable.

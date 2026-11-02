# tools/dev_scores

Helpers for our pack/ship and PR cycle. They are not part of the
shipped mill pack (`agent_coord*`) and must not be imported from product
score paths.

| Module | Card | What |
| --- | --- | --- |
| `open_prs_score.py` | 983 | Open-PR queue medians (CI / Validator / merge gates) from structured PR samples |
| `release_activity.py` | 1029 | Release stage medians (consensus -> GOs -> tag -> PyPI -> live) from samples |
| `delivery_escapes.py` | 955 (escapes) | Validator Fail + post-release revert counts per shipped |

Product card delivery KPI (claim/start/pass/done evidence, lead/eta/doing/size_mix)
stays in the pack. There is no `activity.type=release`.

## Run tests

```bash
PYTHONPATH=<repo> pytest tests/tools/test_open_prs_score_983.py \
  tests/tools/test_release_activity_1029.py \
  tests/tools/test_delivery_escapes_955.py \
  tests/server/test_dev_scores_out_of_pack_1051.py -q
```

Wire a live fetch with `set_live_fetch` / `set_pass_stamps_fetch` from a
desk tool if you want numbers outside tests. Never log tokens or hosts.

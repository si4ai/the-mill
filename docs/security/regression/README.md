# Regression rows

One markdown file per matrix row (`S-1.md`, `F213.md`, `F-wake-trailing.md`, ...). Each file holds
a single table row. After add or edit, run:

```
python tools/regression_matrix.py write
```

That regenerates `docs/security/REGRESSION-MATRIX.md`. Do not append rows to
the index by hand (card 924).

# Validation walk record

The reviewer writes it to its artifact; the PM appends it, with the operator's answer, to
`<docs.specs><slug>/validation.md`, one section per walk.

```markdown
## Walk <n> — sc-##### · PR #<n> · <date>

Branch `<branch>` @ `<sha>` · local dev, base checkout (<ports>)
Served-tree proof: adds `<symbol>` ✓ · removes `<symbol>` ✓
Fixtures: <arranged> · restored: <what was put back>
Verification: Verified | Not as intended — <operator note, verbatim>

| # | Kind | Mode | Where (URL · component · location) | Action | Pass condition | Seen | Verdict |
|---|---|---|---|---|---|---|---|
| 1 (s1.1) | visual | judge | <url> · <component> · <where on page> | <action> | <what should show> | <exact text / state> | pass / fail / blocked |

### Fails

#### <#> — <expected vs seen, one line>
- Request: `<method> <path>` → `<status>`, body `<…>`
- Console / access log: `<line>`
- Blocking: yes / no
- Disposition: fix brief to `impl-<item>` · follow-up raised · pass condition wrong, re-run as #<n>

### Not covered
- <item> — <why: unreachable locally, needs the deployed env, needs a second org>
```

Item source in the `#` cell: `s<n>.<k>` = scenario n, its k-th `Then`/`But` (`Examples` row appended:
`s1.1[annual]`) · `pr<n>` = PR manual step · `extra` = diff surface no scenario covers.

## Summary

The one thing the operator reads. High level, one sentence per point, no code names; omit an empty section.

```markdown
**<story title>** — local dev, <n> items walked in Chrome: <n> passed · <n> failed · <n> blocked.

**What it does now**
- <one behavior, as a user sees it>

**Who notices**
- <who, and what changes for them>

**Design choices**
- <one choice and its trade-off, where a reader could have expected otherwise>

**What the walk saw**
- <a judge item: the exact on-screen words, and where> (screenshot: <ref>)
- <a failed or blocked item: what was expected, what happened>
```

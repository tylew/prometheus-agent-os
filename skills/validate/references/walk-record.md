# Validation walk record

Appended to `<docs.specs><slug>/validation.md`, one section per walk.

```markdown
## Walk <n> — sc-##### · PR #<n> · <date>

Branch `<branch>` @ `<sha>` · local dev, base checkout (<ports>)
Served-tree proof: adds `<symbol>` ✓ · removes `<symbol>` ✓
Fixtures: <arranged> · restored: <what was put back>
Channel: in place | seat

| # | Kind | Where (URL · component · location) | Action | Pass condition | Verdict | Operator note |
|---|---|---|---|---|---|---|
| 1 (s1.1) | visual | <url> · <component> · <where on page> | <action> | <what they should see> | confirmed / rejected / blocked | <verbatim> |

### Rejections

#### <#> — <expected vs seen, one line>
- Request: `<method> <path>` → `<status>`, body `<…>`
- Console / access log: `<line>`
- Blocking: yes / no
- Disposition: fix brief to `impl-<item>` · follow-up raised · pass condition wrong, re-asked as #<n>

### Not covered
- <item> — <why: unreachable locally, needs the deployed env, needs a second org>
```

Item source in the `#` cell: `s<n>.<k>` = scenario n, its k-th `Then`/`But` (`Examples` row appended:
`s1.1[annual]`) · `pr<n>` = PR manual step · `extra` = diff surface no scenario covers.

# Public metrics specification

Publish only reproducible or independently attested values.

| Metric | Definition | Required evidence | Anti-inflation rule |
| --- | --- | --- | --- |
| Installations | distinct successful installs that opted into counting | versioned telemetry policy or independent package statistics | exclude CI and author machines |
| Organizations | distinct legal entities using a release beyond evaluation | signed pilot/adoption confirmation | do not infer from email domains |
| Evidence records processed | records accepted by a released version | signed aggregate counter or pack manifests | report retries/deduplication policy |
| Audit hours saved | baseline active time minus tool-assisted active time for same scope | time study and signed participant report | never substitute modeled time |
| GitHub activity | stars, forks, unique contributors, merged external changes | platform export with date | separate bots and author accounts |
| External contributors | unaffiliated people with accepted contribution | commits/PRs plus disclosed affiliation | exclude generated/vendor commits |
| Accuracy | pairwise precision and recall on labeled data | raw labels, exact commit, run JSON | publish false positives and negatives |
| Query performance | successful scoped queries per second | environment-pinned benchmark | no cross-hardware comparison without normalization |

Use `ImpactLedger` to append metric observations with a source and evidence URL. A valid chain detects edits but does not independently validate the values. Export the ledger and underlying third-party proof together.

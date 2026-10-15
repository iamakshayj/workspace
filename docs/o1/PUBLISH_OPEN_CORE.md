# Publishing the open core without losing authorship

The implementation is intentionally isolated under `evidence-core/`. Do not publish the full Workspace repository merely to release this component.

## Before the first public commit

1. Review every file and confirm the copyright owner and contributor attribution.
2. Run a secret scan over both the current tree and the history selected for publication.
3. Commit the subtree using the real author's configured Git identity. Do not ask another person or automation to impersonate the author.
4. Preserve subsequent contributor names and commit metadata; document substantial design changes in ADRs.

## Safe release sequence

After committing the reviewed subtree in this repository, create a history-preserving split:

```bash
git subtree split --prefix=evidence-core -b evidence-core-public
git log evidence-core-public -- AUTHORS.md
```

Create an empty public repository through the hosting provider, verify its URL, and then push only the split branch:

```bash
git push <verified-public-remote> evidence-core-public:main
```

Before pushing, inspect `git ls-tree -r evidence-core-public` and run a history-aware secret scan. Protect `main`, require the test workflow, enable private vulnerability reporting, create a signed `v0.1.0` tag, and archive the release. Publication is an external action and should be performed only after the owner confirms the exact repository and visibility.

# Benchmark protocol

The benchmark is deterministic with respect to generated records and labels; timing depends on the machine. It uses synthetic, non-PHI data.

Run three or more repetitions at 1k, 10k, and 100k records where hardware permits. Save every JSON result without selecting only the fastest run. Publish the command, Git commit, hardware, operating system, Python version, dependency lock, and all raw results. Report median, p95 where repeated samples exist, precision, recall, false-positive pairs, false-negative pairs, throughput, archive size, and peak memory from an external profiler.

The `manual_comparison` output remains `model-only`. Replace it only after a documented pilot observes the same scoped audit task, records reviewer expertise, measures elapsed active work, and obtains authorization to publish aggregated results.

`results/author-smoke-2026-10-15.json` is an author-run smoke result from the uncommitted initial working tree. It demonstrates the result schema and is not independent validation or a stable release performance claim.

To render a cost scenario, supply all four assumptions: `--manual-minutes`, `--assisted-minutes`, `--hourly-cost`, and `--compute-cost`. The result remains labeled as modeled. For example, `--manual-minutes 120 --assisted-minutes 30 --hourly-cost 100 --compute-cost 5` compares $200 of assumed manual labor with $55 of assumed assisted labor and compute. It must not be presented as an observed saving.

Example:

```bash
evidence-core benchmark --output benchmark-1.json --incidents 250 --noise 1000 --seed 42
```

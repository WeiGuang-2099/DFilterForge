# Model Evaluation Split

`dfilterforge.model_split.generate_model_split` creates the model-facing
evaluation data. Generated PCAPs and JSON artifacts are local outputs and must
not be committed here.

The output layout is:

```text
model_inputs.jsonl
evaluator_gold.json
captures/
  semantic-11.pcap
  semantic-17.pcap
  semantic-23.pcap
  semantic-31.pcap
  semantic-37.pcap
  semantic-43.pcap
```

The model receives `model_inputs.jsonl` only. Every line contains exactly
`item_id`, `intent`, `user_assumptions`, and `split`. Item IDs are opaque, and
each of the 24 canonical cases has two independently worded model items.
Descriptive case IDs, typed IR, reference and mutation filters, probe metadata,
and expected frames are confined to `evaluator_gold.json`.

The dev split has 8 canonical cases and uses capture instances
`semantic-11`, `semantic-17`, and `semantic-23`. The test split has 16
canonical cases and uses `semantic-31`, `semantic-37`, and `semantic-43`.
Each file is a copy of the benchmark capture of that name, kept byte for byte,
followed by the 33 witness packets of `dfilterforge.witnesses`: packets that
separate near-miss filters (a port or address written for the wrong side, an
ACK or sequence number read as a flag, a flag read as the whole flag byte, DNS
read as port 53, a TTL, port or subnet bound moved by one, another DNS code)
that the benchmark recipes alone leave exact. The
witness bytes are seed-derived, so no packet is shared between dev and test.
`scripts/probe_adequacy.py` checks every label with tshark on all six probes
and fails on any single-site mutant of a gold case (from the fixed operator
set in `dfilterforge.mutants`) that survives without a reasoned waiver in
`model_split.MUTANT_WAIVERS`.

This is strictly an **unseen-composition plus unseen-capture-instance** split
relative to the original 36 semantic specifications and their primary probes.
It deliberately reuses the same packet recipes and protocol families, plus the
witness packets. It is not an unseen-recipe split and not an unseen-protocol
split. Results must not be presented as evidence of generalization to new
traffic recipes or protocol families.

Split generation is pure Python and runs on the host or in the project Docker
environment; point the output at an ignored local artifact directory.
`scripts/model_run.py prepare` runs it inside a temporary directory, reads only
`model_inputs.jsonl`, and deletes the gold and the captures before it writes
any prompt file. Never expose `evaluator_gold.json` to a model or to a
retrieval system.

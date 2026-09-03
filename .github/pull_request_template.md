## Scope

Describe the vertical slice and its observable acceptance criteria.

## Verification

- [ ] Python format, lint, typecheck, architecture, and tests pass.
- [ ] Web typecheck, lint, build, Playwright, and axe checks pass if touched.
- [ ] Docker or Compose contract is verified if runtime behavior changed.
- [ ] Public schemas, hashes, and receipts remain explicit and versioned.

## Ablation

Link `docs/ablations/<slice>-<name>.md` and summarize the Full versus
Simplified decision. Production changes are incomplete without a real deletion,
inlining, or bypass experiment on the largest new abstraction.

## Safety and provenance

- [ ] No Docker socket, new host capability, shell filter execution, or public
      arbitrary PCAP upload was added.
- [ ] New fixtures include a hash, provenance, license, split, and review state.
- [ ] Logs and screenshots contain no sensitive packet payload.

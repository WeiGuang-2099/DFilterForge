## Scope

Describe the vertical slice and its observable acceptance criteria.

## Verification

- [ ] Python format, lint, typecheck, architecture, and tests pass.
- [ ] Web typecheck, lint, build, Playwright, and axe checks pass if touched.
- [ ] Docker or Compose contract is verified if runtime behavior changed.
- [ ] Public schemas, hashes, and receipts remain explicit and versioned.

## Result

The interviewer-visible result this PR serves: a number, a page, a demo, a
trained checkpoint, or code that can be explained line by line.

## Minor findings left open

List the minor review findings this PR does not fix, or write "None".

## Safety and provenance

- [ ] No Docker socket, new host capability, shell filter execution, or public
      arbitrary PCAP upload was added.
- [ ] New fixtures include a hash, provenance, license, split, and review state.
- [ ] Logs and screenshots contain no sensitive packet payload.

const receiptFields = [
  ['Intent spec', 'sha256:17d...'],
  ['Candidate IR', 'sha256:20c...'],
  ['Reference filter', 'sha256:a71...'],
  ['tshark image', 'sha256:9ab...'],
  ['Profile', 'sha256:98a...'],
  ['Catalog', 'sha256:6dc...'],
] as const;

export default function ReceiptPage() {
  return (
    <>
      <section className="page-heading compact-heading">
        <div><p className="eyebrow">Immutable run receipt</p><h1>ev-recorded-dns</h1><p className="lede">Recorded artifact. Local verification is pending until the Docker daemon can run.</p></div>
        <span className="status status-neutral">Recorded</span>
      </section>
      <section className="claim-boundary"><strong>Claim boundary</strong><p>Empirical behavior under Wireshark 4.6.8, profile 98ac71, and the dns-boundaries probe suite.</p></section>
      <section className="section-panel receipt-grid">
        {receiptFields.map(([label, value]) => <div key={label}><span className="label">{label}</span><code>{value}</code></div>)}
      </section>
      <section className="section-panel"><span className="label">Replay</span><pre className="filter-code"><code>docker compose --profile pilot run --rm lab replay-run --receipt artifacts/ev-recorded-dns.json</code></pre></section>
    </>
  );
}

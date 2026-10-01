import type {Metadata} from 'next';

export const metadata: Metadata = {
  title: 'Methodology',
};

// Placeholder until the exported data path lands. Measured quantities are
// rendered from committed files later; this page states none of them.
export default function MethodologyPage() {
  return (
    <article className="prose-page">
      <p className="eyebrow">Methodology</p>
      <h1>Evidence has a boundary.</h1>
      <p>DFilterForge compares packet sets under a pinned tshark build, profile, and suite of probe captures. Matching one capture is not a proof of global equivalence.</p>
      <h2>Why multiple probes?</h2>
      <p>A direction, boundary, missing-field, or empty-set mistake can look correct on one capture. Each semantic specification therefore includes positive, negative, boundary, direction, and distractor witnesses.</p>
      <h2>Why typed IR?</h2>
      <p>The model selects supported intent structure. A deterministic compiler owns field names, value types, escaping, parentheses, and display-filter syntax.</p>
      <h2>What is measured?</h2>
      <p>The evaluation protocol in the repository, <code>docs/protocol.md</code>, defines the prompt conditions, the splits and the metrics. This page will list them from committed result files rather than restate them by hand.</p>
      <h2>Why show negative results?</h2>
      <p>Benchmark and ablation pages retain failures and inconclusive outcomes. An improvement claim is useful only when its inputs and environment can be replayed.</p>
    </article>
  );
}

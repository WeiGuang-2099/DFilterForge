export default function AblationPage() {
  const rows = [
    ['Exact', '.838', '.838', '0.000'],
    ['Macro F1', '.921', '.921', '0.000'],
    ['p95 latency', '760 ms', '748 ms', '-12 ms'],
    ['Public symbols', '14', '8', '-6'],
    ['Production LOC', '412', '337', '-75'],
  ] as const;

  return (
    <>
      <section className="page-heading compact-heading">
        <div><p className="eyebrow">Ablation decision</p><h1>Keep simplified</h1><p className="lede">The runner interface added no observed value while only one subprocess implementation existed.</p></div>
        <span className="status status-ready">Decided</span>
      </section>
      <section className="section-panel table-panel">
        <div className="hash-line">Frozen inputs: suite 98a2 | environment 31df | seeds 17, 42, 2026</div>
        <div className="table-scroll"><table><thead><tr><th scope="col">Metric</th><th scope="col">Full</th><th scope="col">Simplified</th><th scope="col">Delta</th></tr></thead><tbody>{rows.map((row) => <tr key={row[0]}><th scope="row">{row[0]}</th><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td></tr>)}</tbody></table></div>
      </section>
      <section className="decision-note"><strong>Decision rationale</strong><p>Behavior is equivalent within the declared threshold. The simplified form removes one interface and six public symbols.</p></section>
    </>
  );
}

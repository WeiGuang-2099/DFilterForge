import {benchmarkRows} from '@/app/_data/recorded';

export default function BenchmarkPage() {
  return (
    <>
      <section className="page-heading compact-heading">
        <div>
          <p className="eyebrow">Recorded benchmark</p>
          <h1>Held-out pipeline comparison</h1>
          <p className="lede">Illustrative recorded values. Live benchmark claims remain gated by Docker replay.</p>
        </div>
      </section>
      <section className="section-panel table-panel">
        <div className="table-scroll">
          <table>
            <thead><tr><th scope="col">Pipeline</th><th scope="col">Exact</th><th scope="col">Macro F1</th><th scope="col">Invalid</th><th scope="col">p95</th></tr></thead>
            <tbody>
              {benchmarkRows.map((row) => (
                <tr key={row.pipeline}>
                  <th scope="row">{row.pipeline}</th><td>{row.exact}</td><td>{row.f1.toFixed(3)}</td><td>{row.invalid}</td><td>{row.p95} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section-panel">
        <span className="label">Error breakdown</span>
        <h2>Failures become narrower as structure is added</h2>
        <div className="error-bars">
          <div><span>Prompt only</span><i style={{width: '78%'}}>direction 14, boundary 10, field 8</i></div>
          <div><span>Typed IR</span><i style={{width: '36%'}}>direction 6, boundary 5, field 1</i></div>
          <div><span>SFT + IR</span><i style={{width: '22%'}}>direction 3, boundary 3, other 7</i></div>
        </div>
      </section>
    </>
  );
}

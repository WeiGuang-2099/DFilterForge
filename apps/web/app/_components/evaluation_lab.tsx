'use client';

import {useState} from 'react';

import {recordedEvaluation} from '@/app/_data/recorded';

export function EvaluationLab() {
  const [selectedFrame, setSelectedFrame] = useState<number>(42);
  const selectedPacket = recordedEvaluation.packets.find(
    (packet) => packet.frame === selectedFrame,
  );

  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">Evaluation Lab</p>
          <h1>Find the packet that disproves the filter.</h1>
          <p className="lede">
            A hand-written example of the evidence chain: intent, typed IR,
            compiled filter, per-probe results, packet diff, predicate trace.
            No run produced these numbers; measured receipts replace this page
            once the first model evaluation is committed.
          </p>
        </div>
        <a className="button" href="#packet-diff">
          Inspect counterexamples
        </a>
      </section>

      <section className="intent-panel">
        <span className="label">Investigation intent</span>
        <p>{recordedEvaluation.intent}</p>
      </section>

      <div className="two-column">
        <section className="section-panel">
          <div className="section-title-row">
            <div>
              <span className="label">Generation contract</span>
              <h2>Typed Intent IR</h2>
            </div>
            <span className="status status-ready">Ready</span>
          </div>
          <ol className="ir-tree">
            {recordedEvaluation.ir.map((node, index) => (
              <li className={index === 0 ? 'ir-root' : ''} key={node}>
                {node}
              </li>
            ))}
          </ol>
        </section>

        <section className="section-panel">
          <span className="label">Deterministic output</span>
          <h2>Compiled filter</h2>
          <pre className="filter-code"><code>{recordedEvaluation.filter}</code></pre>
          <div className="validation-grid" aria-label="Validation results">
            {['Schema', 'Fields', 'Types', 'Engine'].map((item) => (
              <span key={item}><b>Pass</b> {item}</span>
            ))}
          </div>
        </section>
      </div>

      <section className="section-panel table-panel">
        <div className="section-title-row">
          <div>
            <span className="label">Probe suite</span>
            <h2>Three captures, three opportunities to fail</h2>
          </div>
          <span className="status status-mismatch">2 mismatches</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Capture</th>
                <th scope="col">Correct</th>
                <th scope="col">Missing</th>
                <th scope="col">Extra</th>
                <th scope="col">Exact</th>
                <th scope="col">Runtime</th>
              </tr>
            </thead>
            <tbody>
              {recordedEvaluation.probes.map((probe) => {
                const exact = probe.missing === 0 && probe.extra === 0;
                return (
                  <tr key={probe.capture}>
                    <th scope="row">{probe.capture}</th>
                    <td>{probe.correct}</td>
                    <td>{probe.missing}</td>
                    <td>{probe.extra}</td>
                    <td>
                      <span className={`status ${exact ? 'status-ready' : 'status-mismatch'}`}>
                        {exact ? 'Pass' : 'Fail'}
                      </span>
                    </td>
                    <td>{probe.runtimeMs} ms</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="metric-strip" aria-label="Recorded aggregate metrics">
          <span><b>0/3</b> suite exact</span>
          <span><b>.969</b> precision</span>
          <span><b>.939</b> recall</span>
          <span><b>.954</b> macro F1</span>
          <span><b>.913</b> Jaccard</span>
        </div>
      </section>

      <div className="diff-layout" id="packet-diff">
        <section className="section-panel table-panel">
          <div className="section-title-row">
            <div>
              <span className="label">Packet diff</span>
              <h2>Counterexamples</h2>
            </div>
            <div className="bucket-summary" aria-label="Packet-set buckets">
              <span className="bucket bucket-correct">31 correct</span>
              <span className="bucket bucket-missing">2 missing</span>
              <span className="bucket bucket-extra">1 extra</span>
            </div>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Frame</th>
                  <th scope="col">Flow</th>
                  <th scope="col">Summary</th>
                  <th scope="col">Bucket</th>
                  <th scope="col">Predicate</th>
                </tr>
              </thead>
              <tbody>
                {recordedEvaluation.packets.map((packet) => (
                  <tr className={selectedFrame === packet.frame ? 'selected-row' : ''} key={packet.frame}>
                    <td>
                      <button
                        aria-pressed={selectedFrame === packet.frame}
                        className="frame-button"
                        onClick={() => setSelectedFrame(packet.frame)}
                        type="button"
                      >
                        {packet.frame}
                      </button>
                    </td>
                    <td>{packet.source} -&gt; {packet.destination}</td>
                    <td>{packet.summary}</td>
                    <td>
                      <span className={`bucket bucket-${packet.bucket}`}>
                        {packet.bucket === 'missing' ? 'Missing' : 'Extra'}
                      </span>
                    </td>
                    <td><code>{packet.failedPredicate}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside aria-live="polite" className="packet-detail">
          {selectedPacket ? (
            <>
              <div className="section-title-row">
                <div>
                  <span className="label">Predicate trace</span>
                  <h2>Frame {selectedPacket.frame}</h2>
                </div>
                <span className={`bucket bucket-${selectedPacket.bucket}`}>
                  {selectedPacket.bucket === 'missing' ? 'Missing' : 'Extra'}
                </span>
              </div>
              <p className="detail-meta">{selectedPacket.capture}.pcap</p>
              <dl className="flow-details">
                <div><dt>Expected</dt><dd>{selectedPacket.bucket === 'missing' ? 'Match' : 'No match'}</dd></div>
                <div><dt>Candidate</dt><dd>{selectedPacket.bucket === 'missing' ? 'No match' : 'Match'}</dd></div>
              </dl>
              <ul className="trace-list">
                {selectedPacket.traces.map((trace) => (
                  <li key={`${trace.field}-${trace.operator}`}>
                    <span className={`trace-mark ${trace.passed ? 'trace-pass' : 'trace-fail'}`}>
                      {trace.passed ? 'Pass' : 'Fail'}
                    </span>
                    <div>
                      <code>{trace.field} {trace.operator} {trace.expected}</code>
                      <small>Observed: {trace.observed}</small>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="policy-note">Raw payload hidden by public-demo policy.</p>
            </>
          ) : null}
        </aside>
      </div>
    </>
  );
}

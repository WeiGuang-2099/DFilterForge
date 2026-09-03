import {TrustStrip} from '@/app/_components/trust_strip';

export default function WorkbenchPage() {
  return (
    <>
      <TrustStrip />
      <section className="page-heading compact-heading">
        <div>
          <p className="eyebrow">Investigation Workbench</p>
          <h1>Compile an intent without overstating correctness.</h1>
          <p className="lede">This view reports observed matches on one capture. It is not semantic proof.</p>
        </div>
      </section>
      <section className="section-panel">
        <label className="label" htmlFor="intent">Investigation intent</label>
        <textarea defaultValue="Show large TCP SYN packets from 10.0.0.0/8" id="intent" rows={4} />
        <div className="clarification-panel">
          <span className="status status-neutral">Needs clarification</span>
          <div>
            <h2>What does large mean?</h2>
            <p>Choose frame length or TCP payload length before compilation.</p>
            <label><input name="large" type="radio" /> Frame length</label>
            <label><input name="large" type="radio" /> TCP payload length</label>
          </div>
        </div>
      </section>
    </>
  );
}

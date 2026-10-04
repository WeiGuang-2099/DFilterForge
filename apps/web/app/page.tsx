// Placeholder until the exported data path lands. It shows no result, so it
// must not show a number: every value on this site will come from a committed
// result file through a sourced component.
export default function HomePage() {
  return (
    <article className="prose-page">
      <p className="eyebrow">DFilterForge</p>
      <h1>Find the packet that disproves the filter.</h1>
      <p>
        DFilterForge turns a plain-language packet request into a Wireshark display filter, runs
        the filter with a pinned tshark build on several probe captures, and keeps the packets on
        which the filter and the request disagree.
      </p>
      <p>
        This site shows recorded results only. Each value will be rendered from a committed result
        file, and a test will check it against that file. Until that data path is in place, this
        page shows no results.
      </p>
    </article>
  );
}

import Link from 'next/link';
import type {ReactNode} from 'react';

const navigation = [
  {href: '/evaluate', label: 'Evaluate'},
  {href: '/workbench', label: 'Workbench'},
  {href: '/benchmarks/held-out-v1', label: 'Benchmarks'},
  {href: '/ablations/day0', label: 'Ablations'},
  {href: '/receipts/ev-recorded-dns', label: 'Receipts'},
] as const;

interface ShellProps {
  readonly children: ReactNode;
}

export function Shell({children}: ShellProps) {
  return (
    <div className="app-shell">
      <header className="mobile-header">
        <Link className="brand" href="/evaluate">
          DFilterForge
        </Link>
        <span className="mode-label">Public demo</span>
      </header>
      <aside className="sidebar">
        <Link className="brand" href="/evaluate">
          DFilterForge
        </Link>
        <p className="brand-subtitle">Evidence before claims.</p>
        <nav aria-label="Primary navigation">
          {navigation.map((item) => (
            <Link className="nav-link" href={item.href} key={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <Link href="/methodology">Methodology</Link>
          <span>Recorded vertical slice</span>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}

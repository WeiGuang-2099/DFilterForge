import Link from 'next/link';
import type {ReactNode} from 'react';

const navigation = [
  {href: '/evaluate', label: 'Evaluate'},
  {href: '/methodology', label: 'Methodology'},
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
        <span className="mode-label">Illustrative mock</span>
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
          <span>Illustrative mock. No model has been evaluated yet.</span>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}

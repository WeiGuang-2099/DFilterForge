import Link from 'next/link';
import type {ReactNode} from 'react';

const navigation = [
  {href: '/', label: 'Home'},
  {href: '/methodology', label: 'Methodology'},
] as const;

interface ShellProps {
  readonly children: ReactNode;
}

export function Shell({children}: ShellProps) {
  return (
    <div className="app-shell">
      <header className="mobile-header">
        <Link className="brand" href="/">
          DFilterForge
        </Link>
      </header>
      <aside className="sidebar">
        <Link className="brand" href="/">
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
          <span>Recorded results only. This site never calls a model.</span>
        </div>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}

import Link from 'next/link';
import type {ReactNode} from 'react';

const navigation = [
  {href: '/', label: 'Reel'},
  {href: '/board', label: 'Board'},
  {href: '/methodology', label: 'Methodology'},
] as const;

interface ShellProps {
  readonly children: ReactNode;
}

/** The page frame: a masthead in the manner of an RFC page header. */
export function Shell({children}: ShellProps) {
  return (
    <div className="page">
      <header className="mast">
        <div className="mast-id">
          <Link className="mast-name" href="/">
            DFilterForge
          </Link>
          <span>Wireshark display filter benchmark</span>
        </div>
        <nav aria-label="Primary navigation" className="mast-nav">
          {navigation.map((item) => (
            <Link href={item.href} key={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="mast-note">Recorded results only. This site never calls a model.</p>
      </header>
      <main>{children}</main>
    </div>
  );
}

import Link from 'next/link';
import type {ReactNode} from 'react';

import {AUTHOR, AUTHOR_URL, REPOSITORY} from '@/lib/site';
import {Term} from '@/lib/sourced';

const navigation = [
  {href: '/', label: 'Reel'},
  {href: '/board', label: 'Board'},
  {href: '/training', label: 'Training'},
  {href: '/exhibits', label: 'Exhibits'},
  {href: '/methodology', label: 'Methodology'},
] as const;

interface ShellProps {
  readonly children: ReactNode;
}

/** The author's handle, linked to the profile. */
function Author() {
  return (
    <a href={AUTHOR_URL} rel="author">
      <Term name={AUTHOR} />
    </a>
  );
}

/**
 * The page frame: a masthead in the manner of an RFC page header, which
 * names the author and links the source, and a footer line that says so
 * again where a reader finishes.
 */
export function Shell({children}: ShellProps) {
  return (
    <div className="page">
      <header className="mast">
        <div className="mast-id">
          <Link className="mast-name" href="/">
            DFilterForge
          </Link>
          <span>Wireshark display filter benchmark</span>
          <span>
            by <Author />
          </span>
        </div>
        <nav aria-label="Primary navigation" className="mast-nav">
          {navigation.map((item) => (
            <Link href={item.href} key={item.href}>
              {item.label}
            </Link>
          ))}
          <a href={REPOSITORY}>Source</a>
        </nav>
        <p className="mast-note">Recorded results only. This site never calls a model.</p>
      </header>
      <main>{children}</main>
      <footer className="foot">
        <p>
          DFilterForge is by <Author />. The code, the data and every recorded run are on{' '}
          <a href={REPOSITORY}>GitHub</a>.
        </p>
      </footer>
    </div>
  );
}

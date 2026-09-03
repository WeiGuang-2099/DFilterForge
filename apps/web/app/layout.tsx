import type {Metadata} from 'next';
import type {ReactNode} from 'react';

import {Shell} from '@/app/_components/shell';

import './globals.css';

export const metadata: Metadata = {
  title: 'DFilterForge Evaluation Lab',
  description: 'Execution-grounded Wireshark display-filter evaluation.',
};

export default function RootLayout({children}: Readonly<{children: ReactNode}>) {
  return (
    <html data-scroll-behavior="smooth" lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

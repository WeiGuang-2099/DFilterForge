import type {Metadata} from 'next';
import localFont from 'next/font/local';
import type {ReactNode} from 'react';

import {Shell} from '@/app/_components/shell';

import './globals.css';

// Committed woff2 files (app/fonts, SIL OFL 1.1, see NOTICE), so the build
// needs no network and the recorded Reel matches the site.
const archivo = localFont({
  src: './fonts/archivo-latin-var.woff2',
  variable: '--font-archivo',
  weight: '100 900',
  display: 'swap',
  declarations: [{prop: 'font-stretch', value: '62% 125%'}],
});
const chivoMono = localFont({
  src: './fonts/chivo-mono-latin-var.woff2',
  variable: '--font-chivo-mono',
  weight: '100 900',
  display: 'swap',
});

export const metadata: Metadata = {
  title: {default: 'DFilterForge', template: '%s - DFilterForge'},
  description: 'Execution-grounded Wireshark display-filter evaluation.',
};

export default function RootLayout({children}: Readonly<{children: ReactNode}>) {
  return (
    <html className={`${archivo.variable} ${chivoMono.variable}`} lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

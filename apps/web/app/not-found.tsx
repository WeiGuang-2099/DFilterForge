import type {Metadata} from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Not found',
};

// The static export writes this page to 404.html. Next's default page puts
// the status code in the title and heading; this one shows no number.
export default function NotFound() {
  return (
    <article className="prose-page">
      <p className="eyebrow">Not found</p>
      <h1>This page does not exist.</h1>
      <p>
        <Link href="/">Go to the start page</Link>
      </p>
    </article>
  );
}

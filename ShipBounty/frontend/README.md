This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

The dashboard now requires the backend GitHub session. Set
`NEXT_PUBLIC_API_URL` to the FastAPI origin and, if the backend uses a non-default
cookie name, set the server-only `AUTH_SESSION_COOKIE_NAME` to the same value. Server
components forward only that HTTP-only session cookie to protected backend requests;
unauthenticated users are redirected to `/login`.

When `NEXT_PUBLIC_DEMO_MODE=true`, `/login` also shows the non-production
owner/reviewer/finance/contributor persona selector and `/demo` provides a guided,
live showcase view. Backend demo mode must be enabled and bootstrapped separately.
See the root [showcase runbook](../DEMO_RUNBOOK.md); the shared demo key is never
placed in a `NEXT_PUBLIC_` variable.

The authenticated dashboard has two telemetry surfaces:

- `/dashboard/[organizationSlug]/operations` shows live webhook, queue, retry, aggregate worker, rate-limit,
  incomplete-ingestion, duration, and failure data for an administered organization.
- `/dashboard/[organizationSlug]/product` shows repository-scoped bounty, review, claim, payout,
  contributor, repository-health, and in-app notification data.

Both pages render explicit empty/error states and use only API-provided records; no
placeholder chart series are presented as analytics.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

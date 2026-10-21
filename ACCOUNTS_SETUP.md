# Accounts setup (one time, about 20 minutes)

Code is done. Accounts stay dormant until you complete these steps. Guest Derby entries keep working the whole time.

## 1. Resend (sends the sign-in e-mails)
1. Sign up at resend.com (free tier is plenty for 200 accounts).
2. Domains > Add Domain > `boxofficejedi.com`. Resend shows a few DNS records (SPF, DKIM, optional DMARC).
3. Add those records in Cloudflare: DNS > Records. Set the proxy status to "DNS only" (grey cloud). Click Verify in Resend.
4. API Keys > Create API Key (permission: Sending access). Copy it.

## 2. Cloudflare secrets
Workers & Pages > your Pages project > Settings > Variables and Secrets (Production):
- `RESEND_API_KEY` = the key from step 1 (type: Secret)
- `MAIL_FROM` = `Box Office Jedi <login@boxofficejedi.com>` (optional; this is the default)

Then redeploy (push any commit) so the Functions pick them up.

## 3. Database
Workers & Pages > D1 > your database > Console. Paste the contents of `migrations/001_accounts.sql` and run it. Run it once only (the last two lines alter `submissions`).

## 4. Test
1. Go to `/account.html`, create an account with your own e-mail, click the e-mailed link.
2. Visit `/derby-predict.html`: the name/e-mail fields should be replaced by "Playing as ...".
3. Any past guest entries made with that e-mail are attached to your profile on first sign-in.

## Controls
- Cap: in the D1 Console run `UPDATE settings SET value='300' WHERE key='account_cap';`
- Close sign-ups: `UPDATE settings SET value='0' WHERE key='signups_open';`
- Count accounts: `SELECT COUNT(*) FROM users;`
- Suspend someone: `UPDATE users SET status='suspended' WHERE email='x@y.com';`

## Not built yet
Turnstile bot check (sign-up currently uses a honeypot plus per-e-mail/per-IP rate limits), invite codes, waitlist, forums. The `users.role` column and generic tables are in place for those.

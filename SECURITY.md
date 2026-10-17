# Privacy and security

Do not post access tokens, refresh tokens, account JSON files, browser cookies,
chat histories, local database files, or unredacted screenshots in issues.
Use fictional account names and describe failures without credentials.

The app uses local plaintext OAuth files, private directory permissions, an
account-switch lock, and read-only access to desktop chat databases. It is not
a credential vault or a sandbox. Anyone with access to your desktop user account
may be able to access the saved accounts.

If you accidentally expose a credential, revoke it through the provider and
remove the exposed artifact. Deleting a Git commit alone does not revoke a token.
For sensitive vulnerability details, use GitHub private vulnerability reporting
when available; otherwise open an issue requesting a private reporting channel
without including the sensitive details.

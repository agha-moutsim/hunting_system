# Credential rotation checklist

Rotate these after any exposure:

1. GitHub token used for repository access.
2. ScrapingBee API key.
3. RapidAPI key, if exposed again.
4. SerpApi key, if exposed again.

Rules:

- Never commit credentials.
- Never put credentials in command lines or logs.
- Rotate, do not reuse, an exposed key.
- Update `.env` locally and in deployment secret storage.
- Revoke the old key before considering the rotation complete.
---
paths:
  - "src/**"
  - "lib/**"
  - "app/**"
  - "pkg/**"
  - "internal/**"
  - "cmd/**"
  - "**/*.rs"
  - "**/*.go"
  - "**/*.py"
  - "**/*.ts"
  - "**/*.js"
  - "**/*.java"
  - "**/*.kt"
  - "**/*.rb"
---

# Security Rules

## Credentials
- NEVER commit secrets, API keys, tokens, or passwords
- Use environment variables for all secrets
- Check for `.env` files in `.gitignore`
- If you find hardcoded credentials, flag immediately

## Input Validation
- Validate and sanitize ALL user input at system boundaries
- Use parameterized queries — NEVER string-concatenate SQL
- Escape HTML output to prevent XSS
- Validate file uploads: type, size, name

## Authentication
- Store passwords with bcrypt/argon2 — never plain text or MD5/SHA
- Use secure token generation (crypto-random, not Math.random)
- Set appropriate token expiry
- Implement rate limiting on auth endpoints

## Dependencies
- Prefer well-maintained packages with active communities
- Check for known vulnerabilities before adding dependencies
- Pin dependency versions in production

## Data Exposure
- Never log sensitive data (passwords, tokens, PII)
- Use allowlists for API responses — don't return full database objects
- Redact sensitive fields in error messages

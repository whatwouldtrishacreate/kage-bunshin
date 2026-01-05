# Security Policy

## 🔒 Reporting Security Vulnerabilities

We take the security of **Kage Bunshin no Jutsu** seriously. If you discover a security vulnerability, please help us protect our users by reporting it responsibly.

### Where to Report

**Please DO NOT report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, please report security vulnerabilities by:

1. **Email**: [To be added - project maintainer security contact]
2. **GitHub Security Advisories**: Use the [Report a vulnerability](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/security/advisories/new) feature

### What to Include

When reporting a security vulnerability, please include:

- **Description** of the vulnerability and its potential impact
- **Steps to reproduce** the issue (proof-of-concept code if possible)
- **Affected versions** (which versions are vulnerable)
- **Suggested fix** (if you have one)
- **Your contact information** (for follow-up questions)

### What to Expect

After you submit a report, we will:

1. **Acknowledge** your report within **48 hours**
2. **Investigate** the issue and confirm the vulnerability
3. **Develop a fix** and prepare a security advisory
4. **Coordinate disclosure** with you on timing
5. **Credit you** in the security advisory (if you wish)

We aim to fix critical vulnerabilities within **7 days** and other vulnerabilities within **30 days**.

---

## 🛡️ Supported Versions

| Version | Supported          | Status |
| ------- | ------------------ | ------ |
| 1.0.x   | :white_check_mark: | Alpha (Week 3/6 complete) |
| < 1.0   | :x:                | Development versions |

**Note**: This project is currently in **alpha** status. We are actively developing towards a stable 1.0 release. Security updates will be provided for the latest alpha version.

---

## 🔍 Security Considerations

### Authentication & Authorization

- **API Key Authentication**: The API requires `X-API-Key` header for all task management endpoints
- **Key Management**: API keys should be stored securely (environment variables, secrets management)
- **No User Management**: Current version has no user accounts - single API key for all access

### Database Security

- **PostgreSQL Access**: Database credentials must be kept secure
- **Connection String**: Never commit database URLs with credentials to git
- **SQL Injection**: All queries use parameterized statements via asyncpg
- **Data Isolation**: Tasks are isolated in separate git worktrees

### Command Injection Risks

**CRITICAL**: This system executes external CLI commands (Claude Code, Gemini, etc.)

- **Input Validation**: Task descriptions and CLI assignments are validated
- **Shell Escaping**: Command execution must properly escape shell metacharacters
- **Sandboxing**: Consider running CLI adapters in containers or restricted environments
- **Audit Logs**: All task executions are logged to PostgreSQL

### Git Repository Access

- **Worktree Isolation**: Each CLI execution creates temporary git worktrees
- **File Permissions**: Ensure proper permissions on worktree directories
- **Branch Protection**: Production branches should have branch protection rules
- **Sensitive Data**: Never commit secrets, credentials, or API keys to git

### Server-Sent Events (SSE)

- **Authentication**: SSE endpoints require API key authentication
- **Rate Limiting**: Not currently implemented - consider adding for production
- **Connection Limits**: Monitor concurrent SSE connections
- **Data Exposure**: Progress events may contain task details - ensure proper auth

### Dependencies

- **Python Packages**: Regularly update dependencies for security patches
- **Known Vulnerabilities**: Run `pip-audit` or similar tools to detect vulnerable packages
- **Supply Chain**: Verify package integrity (use lock files, checksums)

---

## 🚨 Known Security Considerations

### Alpha Status

This project is in **alpha** (Week 3/6 complete). Security features are still being developed:

- ❌ **No rate limiting** on API endpoints
- ❌ **No user session management** (single API key)
- ❌ **No audit logging** beyond database records
- ❌ **No input sanitization** for CLI command arguments
- ❌ **No container isolation** for CLI executions
- ✅ **Parameterized SQL queries** via asyncpg
- ✅ **API key authentication** for endpoints
- ✅ **Git worktree isolation** for parallel executions

### Production Readiness

**DO NOT use in production** without implementing:

1. **Rate limiting** - Prevent DoS attacks
2. **Input sanitization** - Validate and sanitize all user inputs
3. **Container isolation** - Run CLI adapters in sandboxed environments
4. **Audit logging** - Track all security-relevant events
5. **TLS/HTTPS** - Encrypt API traffic (currently HTTP only)
6. **Secret management** - Use proper secrets management (HashiCorp Vault, etc.)
7. **Monitoring & alerting** - Detect suspicious activity
8. **Backup & recovery** - Protect against data loss

---

## 🔐 Best Practices for Deployment

### Environment Variables

Never hardcode sensitive values:

```bash
# ✅ Good - use environment variables
export DATABASE_URL=postgresql://user:pass@localhost/db
export API_KEYS=your-secret-key-here

# ❌ Bad - never hardcode credentials
DATABASE_URL = "postgresql://admin:password123@localhost/db"  # Never do this!
```

### API Key Management

- **Generate strong keys**: Use cryptographically secure random strings (32+ characters)
- **Rotate regularly**: Change API keys periodically
- **Limit scope**: Use different keys for different environments (dev/staging/prod)
- **Revoke compromised keys**: Immediately revoke any exposed keys

### Database Security

- **Use strong passwords**: Database password should be 20+ random characters
- **Restrict network access**: Only allow connections from application server
- **Enable SSL/TLS**: Encrypt database connections
- **Regular backups**: Backup database regularly and test restore process

### Network Security

- **Firewall rules**: Only expose necessary ports (8000 for API)
- **VPN/Tailscale**: Consider using VPN for internal access
- **Reverse proxy**: Use nginx or similar with security headers
- **DDoS protection**: Use Cloudflare or similar for public APIs

---

## 📋 Security Checklist for Contributors

When contributing code, please ensure:

- [ ] No hardcoded credentials or API keys
- [ ] All database queries use parameterized statements
- [ ] User input is validated and sanitized
- [ ] Error messages don't leak sensitive information
- [ ] New dependencies are from trusted sources
- [ ] Security implications are documented in PR description
- [ ] Tests include security-relevant edge cases

---

## 🔗 Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [PostgreSQL Security](https://www.postgresql.org/docs/current/security.html)
- [Git Security Best Practices](https://github.blog/security/)

---

## 📜 Security Disclosure Policy

We follow **coordinated vulnerability disclosure**:

1. **Private reporting** - Report to us privately first
2. **Fix development** - We develop and test a fix
3. **Advisory creation** - We create a GitHub Security Advisory
4. **Coordinated disclosure** - We agree on public disclosure timing (typically 90 days)
5. **Public disclosure** - We publish advisory and release patched version
6. **Credit** - We credit the reporter (if desired)

**Embargo Period**: We request a **90-day embargo** to allow users time to upgrade before public disclosure.

---

## 🏆 Security Hall of Fame

We appreciate security researchers who help make Kage Bunshin more secure. Researchers who report valid vulnerabilities will be credited here (with their permission):

*No vulnerabilities reported yet.*

---

## ❓ Questions?

If you have questions about this security policy:

1. Review the [GitHub Security documentation](https://docs.github.com/en/code-security)
2. Open a discussion in [GitHub Discussions](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/discussions) (for general security questions, not vulnerabilities)
3. Contact project maintainers via security advisory

---

**Thank you for helping keep Kage Bunshin and our users safe!** 🥷🔒

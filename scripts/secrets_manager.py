#!/usr/bin/env python3
"""
Kage Bunshin Secrets Manager
============================

Manages encrypted secrets stored in PostgreSQL using pgcrypto.

Usage:
    python secrets_manager.py list [--category=CAT] [--environment=ENV]
    python secrets_manager.py get <name>
    python secrets_manager.py set <name> <value> [--category=CAT] [--env=ENV]
    python secrets_manager.py delete <name>
    python secrets_manager.py rotate <name>
    python secrets_manager.py audit <name> [--limit=N]

Environment Variables:
    DATABASE_URL: PostgreSQL connection string
    KB_ENCRYPTION_KEY: Master encryption key (required for get/set)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


class SecretsManager:
    """Manages encrypted secrets in PostgreSQL."""

    def __init__(self, database_url: Optional[str] = None, encryption_key: Optional[str] = None):
        """
        Initialize secrets manager.

        Args:
            database_url: PostgreSQL connection string
            encryption_key: Master encryption key for pgcrypto
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://ndninja@localhost/claude_memory"
        )
        self.encryption_key = encryption_key or os.getenv("KB_ENCRYPTION_KEY")
        self._conn = None

    @property
    def conn(self):
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.database_url)
        return self._conn

    def _require_key(self):
        """Ensure encryption key is available."""
        if not self.encryption_key:
            raise ValueError(
                "Encryption key required. Set KB_ENCRYPTION_KEY environment variable."
            )

    def list_secrets(
        self,
        category: Optional[str] = None,
        environment: Optional[str] = None,
        scope: Optional[str] = None,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List secrets (metadata only, no values).

        Args:
            category: Filter by category
            environment: Filter by environment
            scope: Filter by scope
            include_inactive: Include soft-deleted secrets

        Returns:
            List of secret metadata dicts
        """
        query = """
            SELECT
                id::text,
                name,
                category,
                description,
                scope,
                node_id,
                service_name,
                environment,
                created_at,
                updated_at,
                last_accessed_at,
                access_count,
                created_by,
                is_active,
                expires_at,
                rotation_interval_days,
                last_rotated_at,
                CASE
                    WHEN NOT is_active THEN 'DELETED'
                    WHEN expires_at IS NOT NULL AND expires_at < NOW() THEN 'EXPIRED'
                    WHEN rotation_interval_days IS NOT NULL
                         AND last_rotated_at IS NOT NULL
                         AND last_rotated_at + (rotation_interval_days || ' days')::INTERVAL < NOW()
                    THEN 'ROTATION_DUE'
                    ELSE 'ACTIVE'
                END as status
            FROM kage_bunshin.secrets
            WHERE 1=1
        """
        params = []

        if not include_inactive:
            query += " AND is_active = true"

        if category:
            query += " AND category = %s"
            params.append(category)

        if environment:
            query += " AND environment = %s"
            params.append(environment)

        if scope:
            query += " AND scope = %s"
            params.append(scope)

        query += " ORDER BY category, name"

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_secret(self, name: str, log_access: bool = True) -> Optional[str]:
        """
        Retrieve and decrypt a secret value.

        Args:
            name: Secret name
            log_access: Whether to log this access

        Returns:
            Decrypted secret value or None if not found
        """
        self._require_key()

        with self.conn.cursor() as cur:
            # Get and decrypt
            cur.execute("""
                UPDATE kage_bunshin.secrets
                SET last_accessed_at = NOW(),
                    access_count = access_count + 1
                WHERE name = %s AND is_active = true
                RETURNING pgp_sym_decrypt(encrypted_value, %s)::text
            """, (name, self.encryption_key))

            result = cur.fetchone()

            if result and log_access:
                # Log access
                cur.execute("""
                    INSERT INTO kage_bunshin.secret_access_log
                    (secret_name, action, accessor, accessor_type, success)
                    VALUES (%s, 'read', %s, 'service', true)
                """, (name, os.getenv("USER", "unknown")))

            self.conn.commit()
            return result[0] if result else None

    def set_secret(
        self,
        name: str,
        value: str,
        category: str = "general",
        environment: str = "development",
        description: Optional[str] = None,
        scope: str = "global",
        node_id: Optional[str] = None,
        service_name: Optional[str] = None,
        rotation_interval_days: Optional[int] = None,
        expires_at: Optional[datetime] = None
    ) -> str:
        """
        Store an encrypted secret.

        Args:
            name: Unique secret name
            value: Secret value to encrypt
            category: Secret category
            environment: Target environment
            description: Optional description
            scope: global, node, or service
            node_id: For node-scoped secrets
            service_name: For service-scoped secrets
            rotation_interval_days: Auto-rotation period
            expires_at: Expiration timestamp

        Returns:
            Secret ID
        """
        self._require_key()

        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kage_bunshin.secrets (
                    name, encrypted_value, category, environment, description,
                    scope, node_id, service_name, rotation_interval_days,
                    expires_at, created_by, last_rotated_at
                )
                VALUES (
                    %s, pgp_sym_encrypt(%s, %s), %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (name) DO UPDATE SET
                    encrypted_value = pgp_sym_encrypt(%s, %s),
                    category = COALESCE(%s, kage_bunshin.secrets.category),
                    environment = COALESCE(%s, kage_bunshin.secrets.environment),
                    description = COALESCE(%s, kage_bunshin.secrets.description),
                    updated_at = NOW()
                RETURNING id::text
            """, (
                name, value, self.encryption_key, category, environment, description,
                scope, node_id, service_name, rotation_interval_days, expires_at,
                os.getenv("USER", "unknown"),
                value, self.encryption_key, category, environment, description
            ))

            secret_id = cur.fetchone()[0]

            # Log write
            cur.execute("""
                INSERT INTO kage_bunshin.secret_access_log
                (secret_name, action, accessor, accessor_type, success)
                VALUES (%s, 'write', %s, 'service', true)
            """, (name, os.getenv("USER", "unknown")))

            self.conn.commit()
            return secret_id

    def delete_secret(self, name: str, hard_delete: bool = False) -> bool:
        """
        Delete a secret (soft delete by default).

        Args:
            name: Secret name
            hard_delete: If True, permanently remove

        Returns:
            True if deleted, False if not found
        """
        with self.conn.cursor() as cur:
            if hard_delete:
                cur.execute("""
                    DELETE FROM kage_bunshin.secrets
                    WHERE name = %s
                    RETURNING id
                """, (name,))
            else:
                cur.execute("""
                    UPDATE kage_bunshin.secrets
                    SET is_active = false, updated_at = NOW()
                    WHERE name = %s AND is_active = true
                    RETURNING id
                """, (name,))

            result = cur.fetchone()

            if result:
                cur.execute("""
                    INSERT INTO kage_bunshin.secret_access_log
                    (secret_name, action, accessor, accessor_type, success)
                    VALUES (%s, %s, %s, 'service', true)
                """, (name, 'hard_delete' if hard_delete else 'soft_delete',
                      os.getenv("USER", "unknown")))

            self.conn.commit()
            return result is not None

    def rotate_secret(self, name: str, new_value: str) -> bool:
        """
        Rotate a secret with a new value.

        Args:
            name: Secret name
            new_value: New secret value

        Returns:
            True if rotated, False if not found
        """
        self._require_key()

        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE kage_bunshin.secrets
                SET encrypted_value = pgp_sym_encrypt(%s, %s),
                    last_rotated_at = NOW(),
                    updated_at = NOW()
                WHERE name = %s AND is_active = true
                RETURNING id
            """, (new_value, self.encryption_key, name))

            result = cur.fetchone()
            rotated = result is not None

            if rotated:
                cur.execute("""
                    INSERT INTO kage_bunshin.secret_access_log
                    (secret_name, action, accessor, accessor_type, success)
                    VALUES (%s, 'rotate', %s, 'service', true)
                """, (name, os.getenv("USER", "unknown")))

            self.conn.commit()
            return rotated

    def get_audit_log(self, name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get secret access audit log.

        Args:
            name: Filter by secret name
            limit: Maximum entries to return

        Returns:
            List of audit log entries
        """
        query = """
            SELECT
                id::text,
                secret_name,
                action,
                accessed_at,
                accessor,
                accessor_type,
                success,
                error_message
            FROM kage_bunshin.secret_access_log
        """
        params = []

        if name:
            query += " WHERE secret_name = %s"
            params.append(name)

        query += " ORDER BY accessed_at DESC LIMIT %s"
        params.append(limit)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Kage Bunshin Secrets Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # List command
    list_parser = subparsers.add_parser("list", help="List secrets metadata")
    list_parser.add_argument("--category", "-c", help="Filter by category")
    list_parser.add_argument("--environment", "-e", help="Filter by environment")
    list_parser.add_argument("--scope", "-s", help="Filter by scope")
    list_parser.add_argument("--include-inactive", action="store_true",
                            help="Include deleted secrets")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Get command
    get_parser = subparsers.add_parser("get", help="Get decrypted secret value")
    get_parser.add_argument("name", help="Secret name")
    get_parser.add_argument("--no-log", action="store_true",
                           help="Don't log this access")

    # Set command
    set_parser = subparsers.add_parser("set", help="Set encrypted secret")
    set_parser.add_argument("name", help="Secret name")
    set_parser.add_argument("value", nargs="?", help="Secret value (or use --stdin)")
    set_parser.add_argument("--stdin", action="store_true",
                           help="Read value from stdin")
    set_parser.add_argument("--category", "-c", default="general",
                           help="Secret category")
    set_parser.add_argument("--environment", "-e", default="development",
                           help="Target environment")
    set_parser.add_argument("--description", "-d", help="Secret description")
    set_parser.add_argument("--scope", "-s", default="global",
                           help="Scope: global, node, service")
    set_parser.add_argument("--node-id", help="Node ID for node-scoped secrets")
    set_parser.add_argument("--service", help="Service name for service-scoped secrets")
    set_parser.add_argument("--rotation-days", type=int,
                           help="Auto-rotation interval in days")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete secret")
    delete_parser.add_argument("name", help="Secret name")
    delete_parser.add_argument("--hard", action="store_true",
                              help="Permanently delete (no recovery)")

    # Rotate command
    rotate_parser = subparsers.add_parser("rotate", help="Rotate secret with new value")
    rotate_parser.add_argument("name", help="Secret name")
    rotate_parser.add_argument("value", nargs="?", help="New value (or use --stdin)")
    rotate_parser.add_argument("--stdin", action="store_true",
                              help="Read value from stdin")
    rotate_parser.add_argument("--generate", action="store_true",
                              help="Auto-generate new value")
    rotate_parser.add_argument("--length", type=int, default=32,
                              help="Length for auto-generated value")

    # Audit command
    audit_parser = subparsers.add_parser("audit", help="View access audit log")
    audit_parser.add_argument("name", nargs="?", help="Filter by secret name")
    audit_parser.add_argument("--limit", "-n", type=int, default=50,
                             help="Maximum entries")
    audit_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    manager = SecretsManager()

    try:
        if args.command == "list":
            secrets = manager.list_secrets(
                category=args.category,
                environment=args.environment,
                scope=args.scope,
                include_inactive=args.include_inactive
            )
            if args.json:
                print(json.dumps(secrets, default=str, indent=2))
            else:
                if not secrets:
                    print("No secrets found.")
                else:
                    print(f"{'Name':<30} {'Category':<15} {'Env':<12} {'Status':<12} {'Accessed':<20}")
                    print("-" * 90)
                    for s in secrets:
                        accessed = s['last_accessed_at'].strftime('%Y-%m-%d %H:%M') if s['last_accessed_at'] else 'Never'
                        print(f"{s['name']:<30} {s['category']:<15} {s['environment']:<12} {s['status']:<12} {accessed:<20}")

        elif args.command == "get":
            value = manager.get_secret(args.name, log_access=not args.no_log)
            if value:
                print(value)
            else:
                print(f"Secret '{args.name}' not found", file=sys.stderr)
                sys.exit(1)

        elif args.command == "set":
            value = args.value
            if args.stdin:
                value = sys.stdin.read().strip()
            if not value:
                print("Error: Value required (provide as argument or use --stdin)",
                      file=sys.stderr)
                sys.exit(1)

            secret_id = manager.set_secret(
                name=args.name,
                value=value,
                category=args.category,
                environment=args.environment,
                description=args.description,
                scope=args.scope,
                node_id=args.node_id,
                service_name=args.service,
                rotation_interval_days=args.rotation_days
            )
            print(f"Secret '{args.name}' stored (ID: {secret_id})")

        elif args.command == "delete":
            if manager.delete_secret(args.name, hard_delete=args.hard):
                action = "permanently deleted" if args.hard else "soft-deleted"
                print(f"Secret '{args.name}' {action}")
            else:
                print(f"Secret '{args.name}' not found", file=sys.stderr)
                sys.exit(1)

        elif args.command == "rotate":
            value = args.value
            if args.stdin:
                value = sys.stdin.read().strip()
            elif args.generate:
                import secrets
                value = secrets.token_hex(args.length // 2)
            if not value:
                print("Error: Value required (provide argument, --stdin, or --generate)",
                      file=sys.stderr)
                sys.exit(1)

            if manager.rotate_secret(args.name, value):
                print(f"Secret '{args.name}' rotated successfully")
                if args.generate:
                    print(f"New value: {value}")
            else:
                print(f"Secret '{args.name}' not found", file=sys.stderr)
                sys.exit(1)

        elif args.command == "audit":
            logs = manager.get_audit_log(name=args.name, limit=args.limit)
            if args.json:
                print(json.dumps(logs, default=str, indent=2))
            else:
                if not logs:
                    print("No audit entries found.")
                else:
                    print(f"{'Time':<20} {'Secret':<25} {'Action':<12} {'Accessor':<15} {'Success'}")
                    print("-" * 80)
                    for log in logs:
                        time = log['accessed_at'].strftime('%Y-%m-%d %H:%M:%S')
                        success = 'Yes' if log['success'] else 'No'
                        print(f"{time:<20} {log['secret_name']:<25} {log['action']:<12} {log['accessor'] or 'unknown':<15} {success}")

    finally:
        manager.close()


if __name__ == "__main__":
    main()

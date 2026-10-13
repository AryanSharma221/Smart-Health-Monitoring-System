-- ============================================================================
-- Smart Health Monitoring System — Operational Access Control & Least Privilege
-- ============================================================================
-- File: database/mysql/provision_least_privilege_users.sql
-- Description:
--   Provisions dedicated MySQL 8.4 database user accounts adhering strictly to
--   the principle of least privilege (PoLP) and role-based segregation of duties.
--
-- Account Taxonomy:
--   1. smart_health_app        - FastAPI runtime backend (DML + routine execution)
--   2. smart_health_analytics  - Read-only analytics, reports, and Streamlit
--   3. smart_health_migrator   - Alembic schema migrations and DDL evolution
--   4. smart_health_backup     - mysqldump automated backup agent
--   5. smart_health_admin      - DBA emergency recovery and isolated restore operator
--
-- Operational Guidelines:
--   - Replace placeholder passwords before executing in staging/production.
--   - In production environments, replace '%' with specific host CIDRs or IP addresses.
--   - Enforce REQUIRE SSL / REQUIRE X509 in live deployments.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Create Dedicated Service Accounts
-- ----------------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'smart_health_app'@'%'
    IDENTIFIED BY 'App_Runtime_StrongPass_2026!'
    WITH MAX_CONNECTIONS_PER_HOUR 10000;

CREATE USER IF NOT EXISTS 'smart_health_analytics'@'%'
    IDENTIFIED BY 'Analytics_ReadOnly_StrongPass_2026!'
    WITH MAX_CONNECTIONS_PER_HOUR 5000;

CREATE USER IF NOT EXISTS 'smart_health_migrator'@'%'
    IDENTIFIED BY 'Migrator_Schema_StrongPass_2026!'
    WITH MAX_CONNECTIONS_PER_HOUR 500;

CREATE USER IF NOT EXISTS 'smart_health_backup'@'%'
    IDENTIFIED BY 'Backup_Agent_StrongPass_2026!'
    WITH MAX_CONNECTIONS_PER_HOUR 200;

CREATE USER IF NOT EXISTS 'smart_health_admin'@'%'
    IDENTIFIED BY 'DBA_Emergency_StrongPass_2026!'
    WITH MAX_CONNECTIONS_PER_HOUR 1000;

-- ----------------------------------------------------------------------------
-- 2. Revoke Any Existing Wildcard Grants (Clean Baseline)
-- ----------------------------------------------------------------------------
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'smart_health_app'@'%';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'smart_health_analytics'@'%';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'smart_health_migrator'@'%';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'smart_health_backup'@'%';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'smart_health_admin'@'%';

-- ----------------------------------------------------------------------------
-- 3. Grant Specific Least-Privilege Permissions
-- ----------------------------------------------------------------------------

-- Role 1: Runtime Application User (FastAPI API Layer)
-- Needs standard CRUD operations and permission to execute stored routines.
-- Strictly barred from DDL (CREATE, DROP, ALTER), GRANT, or server admin privileges.
GRANT SELECT, INSERT, UPDATE, DELETE ON `smart_health`.* TO 'smart_health_app'@'%';
GRANT EXECUTE ON `smart_health`.* TO 'smart_health_app'@'%';

-- Role 2: Read-Only Analytics User (Streamlit, BI Reporting, Replication Readers)
-- Purely read-only access to operational tables and views. Zero write privileges.
GRANT SELECT, SHOW VIEW ON `smart_health`.* TO 'smart_health_analytics'@'%';

-- Role 3: Migration User (Alembic DDL Execution)
-- Scope limited to the application database. Full DDL control over tables, indexes,
-- views, triggers, and routines needed during deployment schema upgrades.
GRANT SELECT, INSERT, UPDATE, DELETE ON `smart_health`.* TO 'smart_health_migrator'@'%';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES ON `smart_health`.* TO 'smart_health_migrator'@'%';
GRANT CREATE VIEW, SHOW VIEW ON `smart_health`.* TO 'smart_health_migrator'@'%';
GRANT CREATE ROUTINE, ALTER ROUTINE, EXECUTE ON `smart_health`.* TO 'smart_health_migrator'@'%';
GRANT TRIGGER ON `smart_health`.* TO 'smart_health_migrator'@'%';

-- Role 4: Backup Agent User (mysqldump Automation)
-- Needs read access to schemas, tables, views, triggers, and routines.
-- Requires global PROCESS privilege for mysqldump metadata coordination.
-- Strictly barred from modifying any data (no INSERT, UPDATE, DELETE, DROP).
GRANT PROCESS ON *.* TO 'smart_health_backup'@'%';
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT ON `smart_health`.* TO 'smart_health_backup'@'%';

-- Role 5: DBA Recovery & Emergency Operator
-- Authorized to manage the production database and create isolated recovery targets
-- (e.g. smart_health_recovery) during disaster recovery exercises.
GRANT ALL PRIVILEGES ON `smart_health`.* TO 'smart_health_admin'@'%';
GRANT ALL PRIVILEGES ON `smart_health_recovery`.* TO 'smart_health_admin'@'%';
GRANT ALL PRIVILEGES ON `smart_health_recovery_%`.* TO 'smart_health_admin'@'%';
GRANT PROCESS, SHOW DATABASES ON *.* TO 'smart_health_admin'@'%';

-- ----------------------------------------------------------------------------
-- 4. Apply Privilege Table Changes
-- ----------------------------------------------------------------------------
FLUSH PRIVILEGES;

-- ----------------------------------------------------------------------------
-- 5. Verification Queries (Audit Grants)
-- ----------------------------------------------------------------------------
-- SHOW GRANTS FOR 'smart_health_app'@'%';
-- SHOW GRANTS FOR 'smart_health_analytics'@'%';
-- SHOW GRANTS FOR 'smart_health_migrator'@'%';
-- SHOW GRANTS FOR 'smart_health_backup'@'%';
-- SHOW GRANTS FOR 'smart_health_admin'@'%';

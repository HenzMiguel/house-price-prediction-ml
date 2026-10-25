\set ON_ERROR_STOP on
\getenv migration_password MIGRATION_PASSWORD
\getenv pipeline_password PIPELINE_PASSWORD
\getenv grafana_password GRAFANA_PASSWORD

SELECT format('CREATE ROLE migration_user LOGIN PASSWORD %L', :'migration_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migration_user') \gexec
SELECT format('CREATE ROLE pipeline_writer LOGIN PASSWORD %L', :'pipeline_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_writer') \gexec
SELECT format('CREATE ROLE grafana_reader LOGIN PASSWORD %L', :'grafana_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') \gexec

SELECT 'CREATE DATABASE mlflow OWNER ' || quote_ident(current_user)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow') \gexec
SELECT 'CREATE DATABASE optuna OWNER pipeline_writer'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'optuna') \gexec
CREATE SCHEMA IF NOT EXISTS observability AUTHORIZATION migration_user;
CREATE SCHEMA IF NOT EXISTS catalog AUTHORIZATION migration_user;

REVOKE ALL ON SCHEMA observability FROM PUBLIC;
GRANT USAGE ON SCHEMA observability TO pipeline_writer, grafana_reader;
GRANT USAGE, CREATE ON SCHEMA observability TO migration_user;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_user IN SCHEMA observability
  GRANT SELECT, INSERT, UPDATE ON TABLES TO pipeline_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_user IN SCHEMA observability
  GRANT SELECT ON TABLES TO grafana_reader;

REVOKE ALL ON SCHEMA catalog FROM PUBLIC;
GRANT USAGE ON SCHEMA catalog TO pipeline_writer;
GRANT USAGE, CREATE ON SCHEMA catalog TO migration_user;
ALTER DEFAULT PRIVILEGES FOR ROLE migration_user IN SCHEMA catalog
  GRANT SELECT, INSERT, UPDATE ON TABLES TO pipeline_writer;


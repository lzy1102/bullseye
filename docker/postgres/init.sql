-- Bullseye Framework - PostgreSQL Initialization Script

-- Create database extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create indexes for better performance
-- These will be created by SQLAlchemy automatically
-- but we can add custom indexes here if needed

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE bullseye TO bullseye;

-- Log
DO $$
BEGIN
    RAISE NOTICE 'Bullseye database initialized successfully!';
END $$;

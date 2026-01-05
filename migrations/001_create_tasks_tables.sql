-- Migration: Create tasks and progress_events tables
-- Database: claude_memory
-- Purpose: Store task state and real-time progress for Kage Bunshin no Jutsu orchestrator

-- Tasks table: Stores task metadata and execution results
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Serialized ParallelTaskConfig
    config JSONB NOT NULL,

    -- Serialized AggregatedResult (null until completion)
    result JSONB,

    -- Error tracking
    error TEXT,

    -- Metadata
    created_by VARCHAR(100),

    -- Indexes for common queries
    CONSTRAINT tasks_status_check CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
);

-- Progress events table: Real-time execution progress for SSE streaming
CREATE TABLE IF NOT EXISTS progress_events (
    id SERIAL PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    cli_name VARCHAR(50) NOT NULL,
    session_id VARCHAR(100),

    -- Event data
    status VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,

    -- Optional execution result data
    files_modified TEXT[],
    cost DECIMAL(10, 4),
    duration DECIMAL(10, 2),

    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT progress_events_status_check CHECK (status IN ('working', 'blocked', 'done', 'failed', 'waiting'))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_progress_task_id ON progress_events(task_id);
CREATE INDEX IF NOT EXISTS idx_progress_timestamp ON progress_events(timestamp DESC);

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at on tasks
CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions (assuming claude_mcp user from existing setup)
GRANT SELECT, INSERT, UPDATE, DELETE ON tasks TO claude_mcp;
GRANT SELECT, INSERT, UPDATE, DELETE ON progress_events TO claude_mcp;
GRANT USAGE, SELECT ON SEQUENCE progress_events_id_seq TO claude_mcp;

-- Comments for documentation
COMMENT ON TABLE tasks IS 'Stores task execution state for Kage Bunshin orchestrator';
COMMENT ON TABLE progress_events IS 'Real-time progress events for SSE streaming';
COMMENT ON COLUMN tasks.config IS 'Serialized ParallelTaskConfig with CLI assignments';
COMMENT ON COLUMN tasks.result IS 'Serialized AggregatedResult from parallel execution';

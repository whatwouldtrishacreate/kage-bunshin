-- ================================================================
-- Migration 002: Create Development Documentation Schema
-- ================================================================
-- Purpose: Create development_docs schema for auto-capturing
--          execution metadata, errors, and performance metrics
-- Approach: Hybrid - separate schema within claude_memory database
-- Date: 2026-01-08
-- LLM Council Decision: Hybrid approach (Option C)
-- ================================================================

-- ================================================================
-- CREATE SCHEMA
-- ================================================================
CREATE SCHEMA IF NOT EXISTS development_docs;

-- ================================================================
-- EXECUTION RESULTS
-- Purpose: Normalized execution data (from tasks.result JSONB)
-- Enables: Querying, filtering, analytics on individual CLI results
-- ================================================================
CREATE TABLE IF NOT EXISTS development_docs.execution_results (
    id SERIAL PRIMARY KEY,
    task_id UUID NOT NULL,
    cli_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    duration DECIMAL(10, 2) NOT NULL,
    cost DECIMAL(10, 4) NOT NULL DEFAULT 0.0,
    retries INTEGER NOT NULL DEFAULT 0,
    files_modified TEXT[],
    commits TEXT[],
    output_summary TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Foreign key to tasks table
    CONSTRAINT fk_exec_task FOREIGN KEY (task_id)
        REFERENCES public.tasks(id) ON DELETE CASCADE,

    -- Status validation
    CONSTRAINT chk_exec_status CHECK (
        status IN ('success', 'failure', 'timeout', 'cancelled', 'blocked')
    )
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_exec_results_task_id
    ON development_docs.execution_results(task_id);

CREATE INDEX IF NOT EXISTS idx_exec_results_cli_status
    ON development_docs.execution_results(cli_name, status);

CREATE INDEX IF NOT EXISTS idx_exec_results_created_at
    ON development_docs.execution_results(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_exec_results_cost
    ON development_docs.execution_results(cost DESC);

-- Comment documentation
COMMENT ON TABLE development_docs.execution_results IS
    'Individual CLI execution results, normalized from tasks.result JSONB';

COMMENT ON COLUMN development_docs.execution_results.output_summary IS
    'First 500 characters of stdout for quick reference';

-- ================================================================
-- EXECUTION OUTPUTS
-- Purpose: Store large stdout/stderr separately from metadata
-- Enables: Efficient queries without loading large text fields
-- ================================================================
CREATE TABLE IF NOT EXISTS development_docs.execution_outputs (
    id SERIAL PRIMARY KEY,
    execution_result_id INTEGER NOT NULL,
    output_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    size_bytes INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Foreign key to execution_results
    CONSTRAINT fk_output_exec_result FOREIGN KEY (execution_result_id)
        REFERENCES development_docs.execution_results(id) ON DELETE CASCADE,

    -- Output type validation
    CONSTRAINT chk_output_type CHECK (
        output_type IN ('stdout', 'stderr', 'parsed')
    )
);

-- Index for fast retrieval
CREATE INDEX IF NOT EXISTS idx_exec_outputs_result_id
    ON development_docs.execution_outputs(execution_result_id);

-- Comment documentation
COMMENT ON TABLE development_docs.execution_outputs IS
    'Large execution outputs (stdout/stderr) stored separately';

COMMENT ON COLUMN development_docs.execution_outputs.output_type IS
    'Type of output: stdout (full output), stderr (errors), parsed (extracted code)';

-- ================================================================
-- TASK ERRORS
-- Purpose: Dedicated error tracking for debugging and monitoring
-- Enables: Error pattern analysis, root cause investigation
-- ================================================================
CREATE TABLE IF NOT EXISTS development_docs.task_errors (
    id SERIAL PRIMARY KEY,
    task_id UUID NOT NULL,
    error_type VARCHAR(100) NOT NULL,
    error_message TEXT NOT NULL,
    error_details JSONB,
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Foreign key to tasks table
    CONSTRAINT fk_error_task FOREIGN KEY (task_id)
        REFERENCES public.tasks(id) ON DELETE CASCADE
);

-- Indexes for error analysis
CREATE INDEX IF NOT EXISTS idx_task_errors_task_id
    ON development_docs.task_errors(task_id);

CREATE INDEX IF NOT EXISTS idx_task_errors_type
    ON development_docs.task_errors(error_type);

CREATE INDEX IF NOT EXISTS idx_task_errors_occurred_at
    ON development_docs.task_errors(occurred_at DESC);

-- Comment documentation
COMMENT ON TABLE development_docs.task_errors IS
    'Task execution errors with stack traces and context';

COMMENT ON COLUMN development_docs.task_errors.error_details IS
    'JSONB containing traceback, context, and additional error metadata';

-- ================================================================
-- PERFORMANCE METRICS
-- Purpose: Time-series metrics for cost/duration analytics
-- Enables: Trend analysis, optimization opportunities, reporting
-- ================================================================
CREATE TABLE IF NOT EXISTS development_docs.performance_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(10, 2) NOT NULL,
    metric_unit VARCHAR(20),
    context JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for metrics queries
CREATE INDEX IF NOT EXISTS idx_perf_metrics_name
    ON development_docs.performance_metrics(metric_name);

CREATE INDEX IF NOT EXISTS idx_perf_metrics_recorded_at
    ON development_docs.performance_metrics(recorded_at DESC);

-- Comment documentation
COMMENT ON TABLE development_docs.performance_metrics IS
    'Time-series performance metrics (cost, duration, counts)';

COMMENT ON COLUMN development_docs.performance_metrics.metric_unit IS
    'Unit of measurement: seconds, dollars, count, percentage, etc.';

COMMENT ON COLUMN development_docs.performance_metrics.context IS
    'Additional metadata (task_id, cli_name, etc.)';

-- ================================================================
-- GRANTS
-- ================================================================
GRANT USAGE ON SCHEMA development_docs TO claude_mcp;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA development_docs TO claude_mcp;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA development_docs TO claude_mcp;

-- ================================================================
-- VERIFICATION
-- ================================================================
DO $$
BEGIN
    RAISE NOTICE 'Migration 002 applied successfully!';
    RAISE NOTICE 'Schema: development_docs created';
    RAISE NOTICE 'Tables: execution_results, execution_outputs, task_errors, performance_metrics';
    RAISE NOTICE 'Indexes: 9 indexes created for query optimization';
    RAISE NOTICE 'Grants: All privileges granted to claude_mcp user';
END $$;

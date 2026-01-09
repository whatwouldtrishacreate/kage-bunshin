#!/bin/bash
################################################################################
# Kage Bunshin Memory Leak Stress Test (Working Version)
#
# Tests memory stability by submitting multiple tasks and monitoring RSS memory.
# This version avoids background execution issues by running directly.
#
# Usage:
#   ./stress-test-final.sh [NUM_TASKS]
#   Default: 100 tasks
#
# Exit codes:
#   0 = No memory leak detected (growth < 20MB)
#   1 = Memory leak detected (growth > 50MB)
################################################################################

set -e
set -u

API_URL="http://localhost:8003"
API_KEY="dev-key-12345"
TOTAL=${1:-100}

# Get uvicorn process memory in MB
get_mem() {
    local pid=$(pgrep -f "uvicorn api.main:app" | head -1)
    if [ -n "$pid" ]; then
        echo $(( $(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ') / 1024 ))
    else
        echo "0"
    fi
}

echo "Kage Bunshin Memory Leak Test - $TOTAL tasks"
echo "=============================================="
echo ""

# Check API is running
if ! curl -s -f -H "X-API-Key: $API_KEY" "$API_URL/health" &>/dev/null; then
    echo "ERROR: API not responding at $API_URL"
    echo "Start the API server first:"
    echo "  cd ~/projects/kage-bunshin"
    echo "  source venv/bin/activate"
    echo "  BASE_BRANCH=master uvicorn api.main:app --port 8003"
    exit 1
fi

# Baseline measurement
start=$(get_mem)
echo "Baseline memory: ${start}MB"
echo ""
echo "Submitting $TOTAL tasks..."

success=0
fail=0

for i in $(seq 1 $TOTAL); do
    # Create JSON payload in temp file to avoid quoting issues
    cat > /tmp/task.json <<EOF
{
  "description": "Stress test task #$i: echo 'test $i' > /tmp/stress_$i.txt",
  "cli_assignments": [{"cli_name": "ollama", "timeout": 60}],
  "merge_strategy": "theirs"
}
EOF

    # Submit task via API
    result=$(curl -s -X POST "$API_URL/api/v1/tasks" \
        -H "X-API-Key: $API_KEY" \
        -H "Content-Type: application/json" \
        -d @/tmp/task.json)

    # Check if task was created successfully
    if echo "$result" | grep -q '"id"'; then
        ((success++))
    else
        ((fail++))
    fi

    # Report progress every 20 tasks
    if [ $((i % 20)) -eq 0 ]; then
        mem=$(get_mem)
        echo "  $i/$TOTAL tasks submitted (memory: ${mem}MB, success: $success, fail: $fail)"
    fi
done

rm -f /tmp/task.json

echo ""
echo "Submission complete: $success success, $fail failed"
echo ""

# Monitor memory for 60 seconds to detect delayed leaks
echo "Monitoring memory for 60 seconds..."
for j in {1..6}; do
    sleep 10
    mem=$(get_mem)
    echo "  ${j}0s: ${mem}MB"
done

echo ""

# Final analysis
end=$(get_mem)
growth=$((end - start))

echo "=============================================="
echo "Results:"
echo "  Start memory:  ${start}MB"
echo "  Final memory:  ${end}MB"
echo "  Growth:        ${growth}MB"
echo "  Tasks success: $success/$TOTAL"
echo "  Success rate:  $(awk "BEGIN {printf \"%.1f\", $success/$TOTAL*100}")%"
echo ""

# Determine pass/fail
if [ $growth -gt 50 ]; then
    echo "❌ MEMORY LEAK DETECTED (${growth}MB growth)"
    echo ""
    echo "Investigation needed:"
    echo "  - Check for unclosed resources in task execution"
    echo "  - Review asyncio task cleanup"
    echo "  - Check database connection pooling"
    exit 1
elif [ $growth -gt 20 ]; then
    echo "⚠️  Moderate memory growth (${growth}MB)"
    echo ""
    echo "This is acceptable but monitor in production."
    echo "Consider running longer tests (500+ tasks) to confirm."
    exit 0
else
    echo "✅ No memory leak detected (${growth}MB growth is normal)"
    echo ""
    echo "System is stable under load."
    exit 0
fi

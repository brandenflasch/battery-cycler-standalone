#!/bin/bash

# Battery Cycler - Fully Standalone version
# All dependencies bundled (battery, smc, stress-ng)
# ffmpeg for GPU stress is optional (uses system install if available)

# Find bundled binaries directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/bin" ]; then
    BIN_DIR="$SCRIPT_DIR/bin"
elif [ -d "$SCRIPT_DIR/../bin" ]; then
    BIN_DIR="$SCRIPT_DIR/../bin"
else
    BIN_DIR="$SCRIPT_DIR"
fi

# Add bundled binaries to PATH (priority over system)
export PATH="$BIN_DIR:$PATH"

# Define paths to tools
# Use system battery CLI (requires visudo setup) - bundled one won't have sudo permissions
BATTERY_CMD="/usr/local/bin/battery"
if [ ! -x "$BATTERY_CMD" ]; then
    BATTERY_CMD="$BIN_DIR/battery"  # Fallback to bundled
fi
STRESS_CMD="$BIN_DIR/stress-ng"
FFMPEG_CMD=$(command -v ffmpeg 2>/dev/null || echo "")  # Optional, use system ffmpeg

# Prevent Mac from sleeping
caffeinate -dims -w $$ &
CAFFEINATE_PID=$!

# Default config (overridden by config file)
UPPER_LIMIT=80
LOWER_LIMIT=20
CPU_STRESS="high"   # off, low, medium, high
GPU_STRESS="off"    # off, low, medium, high

CHECK_INTERVAL=30
LOG_FILE=~/battery_cycles.log
HEALTH_LOG=~/battery_health.csv
STATE_FILE=~/battery_cycle_state.txt
CONFIG_FILE=~/battery_cycle_config.json

# Check for bundled battery CLI
if [ ! -x "$BATTERY_CMD" ]; then
    echo "ERROR: Bundled 'battery' CLI not found at $BATTERY_CMD"
    exit 1
fi

# Load config from JSON file
load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        UPPER_LIMIT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('upper_limit', 80))" 2>/dev/null || echo 80)
        LOWER_LIMIT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('lower_limit', 20))" 2>/dev/null || echo 20)
        # Handle both old boolean and new string levels
        CPU_STRESS=$(python3 -c "
import json
v = json.load(open('$CONFIG_FILE')).get('cpu_stress', 'high')
if isinstance(v, bool): v = 'high' if v else 'off'
print(str(v).lower())
" 2>/dev/null || echo "high")
        GPU_STRESS=$(python3 -c "
import json
v = json.load(open('$CONFIG_FILE')).get('gpu_stress', 'off')
if isinstance(v, bool): v = 'high' if v else 'off'
print(str(v).lower())
" 2>/dev/null || echo "off")
    fi
}

load_config
echo "Battery cycling: $LOWER_LIMIT% <-> $UPPER_LIMIT%"
echo "Using battery CLI (self-contained, no AlDente needed)"
echo "CPU Stress: $CPU_STRESS | GPU Stress: $GPU_STRESS"
echo "Logging to: $LOG_FILE"
echo "Health tracking: $HEALTH_LOG"
echo "Press Ctrl+C to stop"

# GPU stress using ffmpeg VideoToolbox encoding (levels: off, low, medium, high)
# Note: ffmpeg is optional - uses system install if available
enable_gpu_stress() {
    local level="$1"
    if [ "$level" = "off" ]; then
        return
    fi
    if [ -z "$FFMPEG_CMD" ]; then
        log "GPU-STRESS: ffmpeg not found - GPU stress disabled"
        return
    fi
    if ! pgrep -f "ffmpeg.*videotoolbox" > /dev/null; then
        case "$level" in
            low)
                "$FFMPEG_CMD" -f lavfi -i testsrc=duration=99999:size=640x480:rate=30 \
                       -c:v hevc_videotoolbox -b:v 10M -f null - 2>/dev/null &
                log "GPU-STRESS: Started LOW (640x480@30fps, 10Mbps)"
                ;;
            medium)
                "$FFMPEG_CMD" -f lavfi -i testsrc=duration=99999:size=1280x720:rate=60 \
                       -c:v hevc_videotoolbox -b:v 30M -f null - 2>/dev/null &
                log "GPU-STRESS: Started MEDIUM (720p@60fps, 30Mbps)"
                ;;
            high)
                "$FFMPEG_CMD" -f lavfi -i testsrc=duration=99999:size=1920x1080:rate=60 \
                       -c:v hevc_videotoolbox -b:v 50M -f null - 2>/dev/null &
                log "GPU-STRESS: Started HIGH (1080p@60fps, 50Mbps)"
                ;;
        esac
    fi
}

disable_gpu_stress() {
    pkill -f "ffmpeg.*videotoolbox" 2>/dev/null
    pkill -f "ffmpeg.*testsrc" 2>/dev/null
    log "GPU-STRESS: Stopped"
}

# Ensure stress processes are running during discharge (resilience)
ensure_stress_running() {
    if [ "$CURRENT_STATE" != "discharging" ]; then
        return
    fi

    # Check and restart CPU stress if needed
    if [ "$CPU_STRESS" != "off" ] && ! pgrep -x "stress-ng" > /dev/null; then
        log "CPU-STRESS: Process died, restarting..."
        case "$CPU_STRESS" in
            low)
                "$STRESS_CMD" --cpu 2 --vm 1 --vm-bytes 1G --timeout 0 &
                log "CPU-STRESS: Restarted LOW (2 CPU, 1GB RAM)"
                ;;
            medium)
                "$STRESS_CMD" --cpu 4 --vm 2 --vm-bytes 2G --timeout 0 &
                log "CPU-STRESS: Restarted MEDIUM (4 CPU, 2GB RAM)"
                ;;
            high)
                "$STRESS_CMD" --cpu 0 --vm 4 --vm-bytes 4G --timeout 0 &
                log "CPU-STRESS: Restarted HIGH (all CPUs, 4GB RAM)"
                ;;
        esac
    fi

    # Check and restart GPU stress if needed
    if [ "$GPU_STRESS" != "off" ] && [ -n "$FFMPEG_CMD" ] && ! pgrep -f "ffmpeg.*videotoolbox" > /dev/null; then
        log "GPU-STRESS: Process died, restarting..."
        enable_gpu_stress "$GPU_STRESS"
    fi
}

# Battery control via battery CLI (self-contained)
enable_discharge() {
    # Set battery to discharge to lower limit
    $BATTERY_CMD discharge $LOWER_LIMIT 2>/dev/null &
    log "BATTERY: Discharge enabled (target: ${LOWER_LIMIT}%)"

    # Start CPU stress based on level (off, low, medium, high)
    if [ "$CPU_STRESS" != "off" ]; then
        if ! pgrep -x "stress-ng" > /dev/null; then
            case "$CPU_STRESS" in
                low)
                    "$STRESS_CMD" --cpu 2 --vm 1 --vm-bytes 1G --timeout 0 &
                    log "CPU-STRESS: Started LOW (2 CPU, 1GB RAM)"
                    ;;
                medium)
                    "$STRESS_CMD" --cpu 4 --vm 2 --vm-bytes 2G --timeout 0 &
                    log "CPU-STRESS: Started MEDIUM (4 CPU, 2GB RAM)"
                    ;;
                high)
                    "$STRESS_CMD" --cpu 0 --vm 4 --vm-bytes 4G --timeout 0 &
                    log "CPU-STRESS: Started HIGH (all CPUs, 4GB RAM)"
                    ;;
            esac
        fi
    fi

    # Start GPU stress based on level
    if [ "$GPU_STRESS" != "off" ]; then
        enable_gpu_stress "$GPU_STRESS"
    fi
}

disable_discharge() {
    # Stop CPU stress
    pkill -9 stress-ng 2>/dev/null
    log "CPU-STRESS: Stopped"

    # Stop GPU stress
    disable_gpu_stress

    # Set battery to charge to upper limit
    $BATTERY_CMD charge $UPPER_LIMIT 2>/dev/null &
    log "BATTERY: Charging enabled (target: ${UPPER_LIMIT}%)"
}

# Get battery health info
get_max_capacity_mah() {
    ioreg -rn AppleSmartBattery | grep '"NominalChargeCapacity"' | awk -F' = ' '{print $2}'
}

get_design_capacity() {
    ioreg -rn AppleSmartBattery | grep -o '"DesignCapacity"=[0-9]*' | awk -F'=' '{print $2}'
}

get_cycle_count() {
    ioreg -rn AppleSmartBattery | grep -o '"CycleCount"=[0-9]*' | awk -F'=' '{print $2}'
}

get_health_percent() {
    local max=$(get_max_capacity_mah)
    local design=$(get_design_capacity)
    if [ -n "$max" ] && [ -n "$design" ] && [ "$design" -gt 0 ]; then
        echo "scale=2; $max / $design * 100" | bc
    else
        echo "N/A"
    fi
}

get_battery_condition() {
    system_profiler SPPowerDataType 2>/dev/null | grep "Condition" | awk -F': ' '{print $2}'
}

get_apple_health() {
    system_profiler SPPowerDataType 2>/dev/null | grep "Maximum Capacity" | awk -F': ' '{print $2}' | tr -d '%'
}

get_temperature() {
    ioreg -rn AppleSmartBattery | grep '"Temperature"' | head -1 | awk -F' = ' '{print $2}'
}

# Send notification with sound
notify() {
    local title="$1"
    local message="$2"
    osascript -e "display notification \"$message\" with title \"$title\" sound name \"Glass\""
}

# Initialize or load state
if [ -f "$STATE_FILE" ]; then
    source "$STATE_FILE"
else
    TOTAL_DISCHARGE_CYCLES=0
    CURRENT_STATE="unknown"
    INITIAL_HEALTH=""
    INITIAL_APPLE_CYCLES=""
    CYCLE_START_TIME=""
    CHARGE_START_TIME=""
    TOTAL_ACTIVE_SECS=0
    TOTAL_DISCHARGE_SECS=0
    TOTAL_CHARGE_SECS=0
    LAST_CHECK_TIME=""
fi

# Initialize time tracking if not set
TOTAL_ACTIVE_SECS=${TOTAL_ACTIVE_SECS:-0}
TOTAL_DISCHARGE_SECS=${TOTAL_DISCHARGE_SECS:-0}
TOTAL_CHARGE_SECS=${TOTAL_CHARGE_SECS:-0}
LAST_CHECK_TIME=$(date +%s)

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" | tee -a "$LOG_FILE"
}

# Log battery health
log_health() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local max_cap=$(get_max_capacity_mah)
    local design_cap=$(get_design_capacity)
    local apple_cycles=$(get_cycle_count)
    local health_pct=$(get_health_percent)
    local apple_health=$(get_apple_health)
    local condition=$(get_battery_condition)
    local temp_raw=$(get_temperature)
    local temp_c=""

    if [ -n "$temp_raw" ]; then
        temp_c=$(echo "scale=1; $temp_raw / 100" | bc)
    fi

    # Create CSV header if file doesn't exist
    if [ ! -f "$HEALTH_LOG" ]; then
        echo "timestamp,script_cycles,apple_cycles,max_capacity_mah,design_capacity_mah,calc_health_percent,apple_health_percent,condition,temperature_c,event" > "$HEALTH_LOG"
    fi

    echo "$timestamp,$TOTAL_DISCHARGE_CYCLES,$apple_cycles,$max_cap,$design_cap,$health_pct,$apple_health,$condition,$temp_c,$1" >> "$HEALTH_LOG"

    log "HEALTH: Calc=${health_pct}% Apple=${apple_health}% | MaxCap: ${max_cap}mAh | AppleCycles: $apple_cycles | Temp: ${temp_c}C | Condition: $condition"
}

# Save state function
save_state() {
    cat > "$STATE_FILE" << STATE
TOTAL_DISCHARGE_CYCLES=$TOTAL_DISCHARGE_CYCLES
CURRENT_STATE="$CURRENT_STATE"
CYCLE_START_TIME="$CYCLE_START_TIME"
CHARGE_START_TIME="$CHARGE_START_TIME"
INITIAL_HEALTH="$INITIAL_HEALTH"
INITIAL_APPLE_CYCLES="$INITIAL_APPLE_CYCLES"
TOTAL_ACTIVE_SECS=$TOTAL_ACTIVE_SECS
TOTAL_DISCHARGE_SECS=$TOTAL_DISCHARGE_SECS
TOTAL_CHARGE_SECS=$TOTAL_CHARGE_SECS
STATE
}

# Update time tracking
update_time_stats() {
    local now=$(date +%s)
    local elapsed=$((now - LAST_CHECK_TIME))
    TOTAL_ACTIVE_SECS=$((TOTAL_ACTIVE_SECS + elapsed))
    if [ "$CURRENT_STATE" = "discharging" ]; then
        TOTAL_DISCHARGE_SECS=$((TOTAL_DISCHARGE_SECS + elapsed))
    elif [ "$CURRENT_STATE" = "charging" ]; then
        TOTAL_CHARGE_SECS=$((TOTAL_CHARGE_SECS + elapsed))
    fi
    LAST_CHECK_TIME=$now
}

# Cleanup function
cleanup() {
    log "========== SCRIPT STOPPED =========="
    log_health "script_stopped"
    kill $CAFFEINATE_PID 2>/dev/null
    pkill -9 stress-ng 2>/dev/null
    disable_gpu_stress

    # Restore battery to normal state (maintain at 80%)
    $BATTERY_CMD maintain 80 2>/dev/null

    save_state

    # Final summary
    echo ""
    echo "============ SESSION SUMMARY ============"
    echo "Total completed cycles: $TOTAL_DISCHARGE_CYCLES"
    echo ""
    echo "--- Current Battery Health ---"
    echo "Apple Health: $(get_apple_health)%"
    echo "Calculated Health: $(get_health_percent)%"
    echo "Max Capacity: $(get_max_capacity_mah) mAh"
    echo "Design Capacity: $(get_design_capacity) mAh"
    echo "Apple Cycle Count: $(get_cycle_count)"
    echo "Condition: $(get_battery_condition)"
    if [ -n "$INITIAL_HEALTH" ]; then
        current_health=$(get_health_percent)
        health_change=$(echo "scale=2; $current_health - $INITIAL_HEALTH" | bc)
        echo ""
        echo "--- Degradation Since Start ---"
        echo "Initial Health: ${INITIAL_HEALTH}%"
        echo "Current Health: ${current_health}%"
        echo "Change: ${health_change}%"
    fi
    echo ""
    echo "Log file: $LOG_FILE"
    echo "Health CSV: $HEALTH_LOG"
    echo "========================================="
    exit 0
}
trap cleanup SIGINT SIGTERM

# Log script start
log "========== SCRIPT STARTED =========="
log "CONFIG: Upper=$UPPER_LIMIT% Lower=$LOWER_LIMIT% Interval=${CHECK_INTERVAL}s"
log "MODE: Standalone (battery CLI)"
log "RESUMED: $TOTAL_DISCHARGE_CYCLES cycles completed previously"

# Record initial health if not set
if [ -z "$INITIAL_HEALTH" ]; then
    INITIAL_HEALTH=$(get_health_percent)
    INITIAL_APPLE_CYCLES=$(get_cycle_count)
    save_state
fi

log_health "script_started"
log "INITIAL HEALTH: ${INITIAL_HEALTH}% | Apple Cycles: $INITIAL_APPLE_CYCLES"

# Initial notification
notify "Battery Cycling Started" "Range: ${LOWER_LIMIT}% to ${UPPER_LIMIT}%"

# Get initial battery level and set initial state
# If above lower limit, discharge first. If at/below lower limit, charge.
battery=$(pmset -g batt | grep -Eo "\d+%" | head -1 | cut -d% -f1)
if [ "$battery" -gt $LOWER_LIMIT ]; then
    enable_discharge
    CURRENT_STATE="discharging"
    CYCLE_START_TIME=$(date +%s)
    log "INITIAL: Battery at ${battery}% > ${LOWER_LIMIT}%, starting discharge"
else
    disable_discharge
    CURRENT_STATE="charging"
    CHARGE_START_TIME=$(date +%s)
    log "INITIAL: Battery at ${battery}% <= ${LOWER_LIMIT}%, starting charge"
fi
save_state

while true; do
    # Reload config to pick up GUI changes
    load_config

    # Update time tracking
    update_time_stats
    save_state

    battery=$(pmset -g batt | grep -Eo "\d+%" | head -1 | cut -d% -f1)
    power_source=$(pmset -g batt | head -1 | grep -o "'.*'" | tr -d "'")
    apple_health=$(get_apple_health)
    cpu_running=$(pgrep -x "stress-ng" > /dev/null && echo "yes" || echo "no")
    gpu_running=$(pgrep -f "ffmpeg.*videotoolbox" > /dev/null && echo "yes" || echo "no")

    echo "$(date '+%H:%M:%S') - Battery: $battery% | AppleHealth: ${apple_health}% | Source: $power_source | CPU: $cpu_running | GPU: $gpu_running | Cycles: $TOTAL_DISCHARGE_CYCLES | State: $CURRENT_STATE"

    # Ensure stress processes are running during discharge (resilience check)
    ensure_stress_running

    if [ "$battery" -le $LOWER_LIMIT ]; then
        if [ "$CURRENT_STATE" != "charging" ]; then
            # Completed a discharge cycle
            CYCLE_END_TIME=$(date +%s)
            if [ -n "$CYCLE_START_TIME" ] && [ "$CYCLE_START_TIME" -gt 0 ]; then
                CYCLE_DURATION=$(( (CYCLE_END_TIME - CYCLE_START_TIME) / 60 ))
                log "DISCHARGE COMPLETE - Took ${CYCLE_DURATION} minutes"
            fi

            TOTAL_DISCHARGE_CYCLES=$((TOTAL_DISCHARGE_CYCLES + 1))
            log "CYCLE #$TOTAL_DISCHARGE_CYCLES - Started charging at $battery%"
            log_health "discharge_complete"

            # Disable discharge, enable charging
            disable_discharge
            notify "Cycle $TOTAL_DISCHARGE_CYCLES Complete" "Discharge done. Health: $(get_health_percent)% | Now charging to ${UPPER_LIMIT}%"

            CURRENT_STATE="charging"
            CHARGE_START_TIME=$(date +%s)
            save_state
        fi

    elif [ "$battery" -ge $UPPER_LIMIT ]; then
        if [ "$CURRENT_STATE" != "discharging" ]; then
            # Completed a charge cycle
            if [ -n "$CHARGE_START_TIME" ] && [ "$CHARGE_START_TIME" -gt 0 ]; then
                CHARGE_END_TIME=$(date +%s)
                CHARGE_DURATION=$(( (CHARGE_END_TIME - CHARGE_START_TIME) / 60 ))
                log "CHARGE COMPLETE - Took ${CHARGE_DURATION} minutes"
            fi

            log "CYCLE #$((TOTAL_DISCHARGE_CYCLES + 1)) - Started discharging at $battery%"
            log_health "charge_complete"

            # Enable discharge
            enable_discharge
            notify "Charge Complete" "Battery at ${battery}%. Starting discharge cycle #$((TOTAL_DISCHARGE_CYCLES + 1))"

            CURRENT_STATE="discharging"
            CYCLE_START_TIME=$(date +%s)
            save_state
        fi
    fi

    sleep $CHECK_INTERVAL
done

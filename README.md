# Battery Cycler

A macOS menu bar app for automated battery cycling. Useful for battery calibration, testing battery health monitoring systems, and maintaining accurate charge level readings.

## Download

**[Download Latest Release](https://github.com/brandenflasch/battery-cycler-standalone/releases/latest)**

1. Download `Battery-Cycler.dmg`
2. Open the DMG
3. Drag to Applications
4. Launch from Applications

> **Note:** On first launch, macOS may require you to right-click → Open to bypass Gatekeeper.

## Features

- **Automated Cycling** - Continuously cycles battery between configurable upper and lower limits
- **Menu Bar App** - Lives in your menu bar with real-time battery percentage display
- **Configurable Limits** - Set upper limit (50-100%) and lower limit (10-50%)
- **CPU Stress Testing** - Optional CPU load during discharge (Off/Low/Medium/High)
- **GPU Stress Testing** - Optional GPU load during discharge using VideoToolbox encoding
- **Health Tracking** - Monitors and logs battery health, capacity, and cycle count
- **Statistics** - View detailed stats including time spent charging/discharging
- **Pause/Resume** - Hold battery at any percentage or stop cycling entirely
- **Persistent State** - Remembers cycle count and settings across restarts
- **Self-Contained** - All dependencies bundled (no AlDente required)

## Screenshots

### Menu Bar Interface
```
🔋 78% ▼
├── Status: Cycling Active
├── ──────────────
├── Stop Cycling
├── Pause (Hold at 50%)        ►
├── Stop & Reset to 80%        ►
├── ──────────────
├── Upper Limit: 80%           ►
├── Lower Limit: 20%           ►
├── ──────────────
├── CPU Stress: High           ►
├── GPU Stress: High           ►
├── ──────────────
├── Cycles: 108 | Health: 77%
├── ──────────────
├── View Log
├── Show Stats
└── Quit
```

## How It Works

1. **Discharge Phase**: When battery reaches the upper limit, the app enables discharge mode and optionally starts CPU/GPU stress to accelerate drain
2. **Charge Phase**: When battery reaches the lower limit, discharge stops and normal charging resumes
3. **Repeat**: The cycle continues automatically until stopped

### Cycle Flow
```
    ┌─────────────────────────────────────┐
    │                                     │
    ▼                                     │
[Upper Limit] ──discharge──► [Lower Limit]
   (80%)        + stress        (20%)
                                  │
                                  │ charge
                                  │
                                  ▼
                            [Upper Limit]
                               (80%)
                                  │
                                  └──────┘
```

## Requirements

- macOS 12.0 or later
- Apple Silicon (M1/M2/M3) Mac
- `battery` CLI tool (installed automatically or via setup below)

### Dependencies Bundled
- `battery` CLI script for SMC control
- `smc` binary for System Management Controller access
- `stress-ng` for CPU stress testing

### Optional
- `ffmpeg` with VideoToolbox support for GPU stress (install via `brew install ffmpeg`)

## Installation

### Option 1: Download DMG (Recommended)
1. Download from [Releases](https://github.com/brandenflasch/battery-cycler-standalone/releases/latest)
2. Open DMG and drag to Applications
3. Run the app

### Option 2: Build from Source
```bash
# Clone repository
git clone https://github.com/brandenflasch/battery-cycler-standalone.git
cd battery-cycler-standalone

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install rumps py2app

# Install battery CLI (required for SMC permissions)
curl -s https://raw.githubusercontent.com/actuallymentor/battery/main/setup.sh | bash

# Build app
python setup.py py2app

# Install
cp -R "dist/Battery Cycler.app" /Applications/
```

## Configuration

Settings are stored in `~/battery_cycle_config.json`:

```json
{
  "upper_limit": 80,
  "lower_limit": 20,
  "pause_limit": 50,
  "reset_limit": 80,
  "cpu_stress": "high",
  "gpu_stress": "off"
}
```

### Settings Reference

| Setting | Values | Description |
|---------|--------|-------------|
| `upper_limit` | 50-100 | Battery percentage to start discharge |
| `lower_limit` | 10-50 | Battery percentage to start charge |
| `cpu_stress` | off, low, medium, high | CPU load during discharge |
| `gpu_stress` | off, low, medium, high | GPU load during discharge |

### Stress Levels

**CPU Stress (stress-ng)**
| Level | CPU Cores | VM Workers | Memory |
|-------|-----------|------------|--------|
| Low | 2 | 1 | 1GB |
| Medium | 4 | 2 | 2GB |
| High | All | 4 | 4GB |

**GPU Stress (ffmpeg VideoToolbox)**
| Level | Resolution | Frame Rate | Bitrate |
|-------|------------|------------|---------|
| Low | 640x480 | 30fps | 10Mbps |
| Medium | 1280x720 | 60fps | 30Mbps |
| High | 1920x1080 | 60fps | 50Mbps |

## Log Files

### Cycle Log
Location: `~/battery_cycles.log`

Contains timestamped entries for all cycling events:
```
2026-01-19 14:55:37 | ========== SCRIPT STARTED ==========
2026-01-19 14:55:37 | CONFIG: Upper=80% Lower=20% Interval=30s
2026-01-19 14:55:37 | BATTERY: Discharge enabled (target: 20%)
2026-01-19 14:55:37 | CPU-STRESS: Started HIGH (all CPUs, 4GB RAM)
2026-01-19 15:35:22 | DISCHARGE COMPLETE - Took 40 minutes
2026-01-19 15:35:22 | CYCLE #109 - Started charging at 20%
```

### Health Log
Location: `~/battery_health.csv`

CSV file tracking battery health over time:
```csv
timestamp,script_cycles,apple_cycles,max_capacity_mah,design_capacity_mah,calc_health_percent,apple_health_percent,condition,temperature_c,event
2026-01-19 14:55:37,108,898,4610,6079,75.00,77,Service Recommended,30.9,script_started
```

### State File
Location: `~/battery_cycle_state.txt`

Persists state across app restarts:
```
TOTAL_DISCHARGE_CYCLES=108
CURRENT_STATE="discharging"
INITIAL_HEALTH="74.00"
INITIAL_APPLE_CYCLES="846"
TOTAL_ACTIVE_SECS=54276
TOTAL_DISCHARGE_SECS=38827
TOTAL_CHARGE_SECS=15449
```

## Statistics

Access via **Show Stats** in the menu:

```
=== BATTERY HEALTH ===
Apple Reported: 77%
Calculated: 75%
Capacity: 4610/6079 mAh
Condition: Service Recommended

=== CYCLE COUNTS ===
Apple Cycles: 898
App Cycles: 108
Apple Cycles Added: 52

=== SESSION STATS ===
Total Active: 15h 4m
Time Discharging: 10h 47m
Time Charging: 4h 17m

=== CHANGES ===
Initial Health: 74%
Health Change: +1%
Initial Cycles: 846
```

## Troubleshooting

### App doesn't appear in menu bar
1. Check if app is running: `pgrep -fl "Battery Cycler"`
2. Try relaunching the app
3. Check System Settings → Control Center → Menu Bar Only

### Battery not discharging
1. Verify `battery` CLI works: `battery status`
2. Check for conflicting processes: `pgrep -fl battery`
3. Kill conflicts and restart: `pkill -f battery && open "/Applications/Battery Cycler.app"`

### "battery CLI not found" error
Install the battery CLI:
```bash
curl -s https://raw.githubusercontent.com/actuallymentor/battery/main/setup.sh | bash
```

### Charging doesn't resume
1. Check if "Optimized Battery Charging" is interfering (System Settings → Battery)
2. Manually enable charging: `battery charging on`

### GPU stress not working
Install ffmpeg with VideoToolbox support:
```bash
brew install ffmpeg
```

## Technical Details

### How Battery Control Works
The app uses the [battery](https://github.com/actuallymentor/battery) CLI tool which interfaces with the Mac's System Management Controller (SMC) to:
- Enable/disable charging
- Force discharge while plugged in
- Monitor battery status

### SMC Keys Used
- `CH0B`, `CH0C` - Charging control
- `CH0I` - Discharge control
- `CHTE` - Charge termination
- `ACLC` - MagSafe LED control

### Permissions
The battery CLI requires sudo permissions for SMC access. These are configured via `/private/etc/sudoers.d/battery` during installation.

## Related Projects

- [battery-cycler-aldente](https://github.com/brandenflasch/battery-cycler) - Alternative version using AlDente Pro

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - See [LICENSE](LICENSE) for details.

## Credits

- [battery CLI](https://github.com/actuallymentor/battery) - Battery control via SMC
- [rumps](https://github.com/jaredks/rumps) - Python menu bar framework
- [stress-ng](https://github.com/ColinIanKing/stress-ng) - CPU stress testing

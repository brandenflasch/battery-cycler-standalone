#!/usr/bin/env python3
"""Battery Cycler Menu Bar App - Uses battery CLI for direct SMC control.
No dependency on AlDente or Apple Shortcuts."""

import rumps
import subprocess
import json
import os
import sys
import signal

VERSION = "2.1.0"
BUILD_COMMIT = "bf3e094"  # Update with each release

def get_version_string():
    """Get version string with commit hash."""
    # Try to get live git commit if in dev environment
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return f"v{VERSION} ({result.stdout.strip()})"
    except:
        pass
    return f"v{VERSION} ({BUILD_COMMIT})"

CONFIG_FILE = os.path.expanduser("~/battery_cycle_config.json")
STATE_FILE = os.path.expanduser("~/battery_cycle_state.txt")
LOG_FILE = os.path.expanduser("~/battery_cycles.log")

# Find script path - works both in dev and in app bundle
def get_script_path():
    # Check if running from app bundle
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, "battery_cycle.sh")
    # Check in Resources folder (py2app)
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    resources_script = os.path.join(bundle_dir, "battery_cycle.sh")
    if os.path.exists(resources_script):
        return resources_script
    # Fallback to Dropbox location
    return os.path.expanduser("~/Dropbox/Claude Projects/battery-cycler-standalone/battery_cycle.sh")

DEFAULT_CONFIG = {
    "upper_limit": 80,
    "lower_limit": 20,
    "pause_limit": 50,
    "reset_limit": 80,
    "cpu_stress": "high",  # off, low, medium, high
    "gpu_stress": "off"    # off, low, medium, high
}

STRESS_LEVELS = ["Off", "Low", "Medium", "High"]


def get_bundled_bin_path():
    """Get path to bundled binaries directory."""
    # Check if running from app bundle (py2app)
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(bundle_dir, "bin")
    if os.path.exists(bin_dir):
        return bin_dir
    # Fallback to project directory
    return os.path.expanduser("~/Dropbox/Claude Projects/battery-cycler-standalone/bin")


def get_battery_cli_path():
    """Get path to battery CLI - prefer system (has visudo permissions)."""
    system_battery = "/usr/local/bin/battery"
    if os.path.exists(system_battery):
        return system_battery
    return os.path.join(get_bundled_bin_path(), "battery")


def check_battery_cli():
    """Check if bundled battery CLI exists."""
    return os.path.exists(get_battery_cli_path())


def run_battery_cmd(args):
    """Run the bundled battery CLI command."""
    try:
        battery_path = get_battery_cli_path()
        subprocess.run([battery_path] + args, capture_output=True, timeout=10)
    except Exception as e:
        print(f"battery command failed: {e}")


class BatteryCyclerApp(rumps.App):
    def __init__(self):
        super().__init__("", quit_button=None)
        self.script_process = None
        self.config = self.load_config()

        # Check for battery CLI
        if not check_battery_cli():
            rumps.alert(
                "battery CLI not found",
                "Install it with:\ncurl -s https://raw.githubusercontent.com/actuallymentor/battery/main/setup.sh | bash"
            )

        # Build menu
        self.status_item = rumps.MenuItem("Status: Idle", callback=None)
        self.status_item.set_callback(None)

        self.toggle_item = rumps.MenuItem("Start Cycling", callback=self.toggle_cycling)

        # Pause submenu with selectable percentage (20-100% in 5% increments)
        self.pause_menu = rumps.MenuItem("Pause (Hold at {}%)".format(self.config.get("pause_limit", 50)))
        for val in range(20, 101, 5):
            item = rumps.MenuItem("{}%".format(val), callback=self.pause_at_percent)
            if val == self.config.get("pause_limit", 50):
                item.state = 1
            self.pause_menu.add(item)

        # Stop/Reset submenu with selectable percentage
        self.stop_menu = rumps.MenuItem("Stop & Reset to {}%".format(self.config.get("reset_limit", 80)))
        for val in range(20, 101, 5):
            item = rumps.MenuItem("{}%".format(val), callback=self.stop_at_percent)
            if val == self.config.get("reset_limit", 80):
                item.state = 1
            self.stop_menu.add(item)

        # Upper limit submenu
        self.upper_menu = rumps.MenuItem("Upper Limit: {}%".format(self.config["upper_limit"]))
        for val in range(50, 101, 10):
            item = rumps.MenuItem("{}%".format(val), callback=self.set_upper_limit)
            if val == self.config["upper_limit"]:
                item.state = 1
            self.upper_menu.add(item)

        # Lower limit submenu (10-50%)
        self.lower_menu = rumps.MenuItem("Lower Limit: {}%".format(self.config["lower_limit"]))
        for val in range(10, 51, 10):
            item = rumps.MenuItem("{}%".format(val), callback=self.set_lower_limit)
            if val == self.config["lower_limit"]:
                item.state = 1
            self.lower_menu.add(item)

        # CPU stress submenu
        cpu_level = self.config.get("cpu_stress", "high")
        if isinstance(cpu_level, bool):  # migrate old config
            cpu_level = "high" if cpu_level else "off"
            self.config["cpu_stress"] = cpu_level
        self.cpu_stress_menu = rumps.MenuItem("CPU Stress: {}".format(cpu_level.title()))
        for level in STRESS_LEVELS:
            item = rumps.MenuItem(level, callback=self.set_cpu_stress)
            if level.lower() == cpu_level:
                item.state = 1
            self.cpu_stress_menu.add(item)

        # GPU stress submenu
        gpu_level = self.config.get("gpu_stress", "off")
        if isinstance(gpu_level, bool):  # migrate old config
            gpu_level = "high" if gpu_level else "off"
            self.config["gpu_stress"] = gpu_level
        self.gpu_stress_menu = rumps.MenuItem("GPU Stress: {}".format(gpu_level.title()))
        for level in STRESS_LEVELS:
            item = rumps.MenuItem(level, callback=self.set_gpu_stress)
            if level.lower() == gpu_level:
                item.state = 1
            self.gpu_stress_menu.add(item)

        # Info item
        self.info_item = rumps.MenuItem("Cycles: 0 | Health: --%", callback=None)
        self.info_item.set_callback(None)

        # Log viewer and stats
        self.view_log_item = rumps.MenuItem("View Log", callback=self.view_log)
        self.show_stats_item = rumps.MenuItem("Show Stats", callback=self.show_stats)

        # Version info
        self.version_item = rumps.MenuItem(get_version_string(), callback=None)
        self.version_item.set_callback(None)

        self.menu = [
            self.status_item,
            None,  # separator
            self.toggle_item,
            self.pause_menu,
            self.stop_menu,
            None,
            self.upper_menu,
            self.lower_menu,
            None,
            self.cpu_stress_menu,
            self.gpu_stress_menu,
            None,
            self.info_item,
            None,
            self.view_log_item,
            self.show_stats_item,
            None,
            self.version_item,
            rumps.MenuItem("Quit", callback=self.quit_app)
        ]

        # Start timer to update status
        self.timer = rumps.Timer(self.update_status, 5)
        self.timer.start()
        self.update_status(None)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge with defaults
                    for key in DEFAULT_CONFIG:
                        if key not in config:
                            config[key] = DEFAULT_CONFIG[key]
                    return config
            except:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2)

    def get_battery_info(self):
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout
            # Parse battery percentage
            import re
            match = re.search(r'(\d+)%', output)
            percent = int(match.group(1)) if match else 0

            # Check if charging
            charging = "charging" in output.lower() or "AC Power" in output
            return percent, charging
        except:
            return 0, False

    def get_cycle_info(self):
        cycles = 0
        health = "--"
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'rb') as f:
                    content = f.read().decode('ascii', 'replace')
                    for line in content.split('\n'):
                        if line.startswith("TOTAL_DISCHARGE_CYCLES="):
                            cycles = int(line.split("=")[1].strip())

            # Get Apple health from system_profiler (official value)
            result = subprocess.run(
                ["system_profiler", "SPPowerDataType"],
                capture_output=True, timeout=10
            )
            output = result.stdout.decode('utf-8', 'replace')
            for line in output.split('\n'):
                if "Maximum Capacity" in line and ":" in line:
                    health = line.split(':')[-1].strip()
                    break
        except:
            pass
        return cycles, health

    def update_status(self, _):
        percent, charging = self.get_battery_info()
        cycles, health = self.get_cycle_info()

        # Update title with battery percentage
        self.title = "{} {}%".format("" if charging else "", percent)

        # Update status
        if self.script_process and self.script_process.poll() is None:
            self.status_item.title = "Status: Cycling Active"
            self.toggle_item.title = "Stop Cycling"
        else:
            self.status_item.title = "Status: Idle"
            self.toggle_item.title = "Start Cycling"
            self.script_process = None

        # Update info
        self.info_item.title = "Cycles: {} | Health: {}".format(cycles, health)

    def toggle_cycling(self, _):
        if self.script_process and self.script_process.poll() is None:
            # Stop cycling
            try:
                os.killpg(os.getpgid(self.script_process.pid), signal.SIGTERM)
            except:
                self.script_process.terminate()
            self.script_process = None
            rumps.notification("Battery Cycler", "", "Cycling stopped")
        else:
            # Save current config before starting
            self.save_config()
            # Start cycling
            script_path = get_script_path()
            self.script_process = subprocess.Popen(
                ["bash", script_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            rumps.notification("Battery Cycler", "", "Cycling started")
        self.update_status(None)

    def set_upper_limit(self, sender):
        val = int(sender.title.replace('%', ''))
        self.config["upper_limit"] = val
        self.save_config()

        # Update menu
        self.upper_menu.title = "Upper Limit: {}%".format(val)
        for item in self.upper_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_lower_limit(self, sender):
        val = int(sender.title.replace('%', ''))
        self.config["lower_limit"] = val
        self.save_config()

        # Update menu
        self.lower_menu.title = "Lower Limit: {}%".format(val)
        for item in self.lower_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_cpu_stress(self, sender):
        level = sender.title.lower()
        self.config["cpu_stress"] = level
        self.save_config()
        self.cpu_stress_menu.title = "CPU Stress: {}".format(sender.title)
        for item in self.cpu_stress_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def set_gpu_stress(self, sender):
        level = sender.title.lower()
        self.config["gpu_stress"] = level
        self.save_config()
        self.gpu_stress_menu.title = "GPU Stress: {}".format(sender.title)
        for item in self.gpu_stress_menu.values():
            item.state = 1 if item.title == sender.title else 0

    def view_log(self, _):
        # Open Terminal with tail -f on the log file
        script = '''
        tell application "Terminal"
            activate
            do script "tail -f {}"
        end tell
        '''.format(LOG_FILE)
        subprocess.run(["osascript", "-e", script])

    def show_stats(self, _):
        # Use osascript to show stats (avoids rumps encoding issues)
        try:
            # Get current battery info from system_profiler
            result = subprocess.run(
                ["system_profiler", "SPPowerDataType"],
                capture_output=True, timeout=10
            )
            output = result.stdout.decode('utf-8', 'replace')
            apple_health = "N/A"
            condition = "N/A"
            apple_cycles = "N/A"
            for line in output.split('\n'):
                line = line.strip()
                if "Maximum Capacity" in line and ":" in line:
                    apple_health = line.split(':')[-1].strip()
                elif "Condition" in line and ":" in line:
                    condition = line.split(':')[-1].strip()
                elif "Cycle Count" in line and ":" in line:
                    apple_cycles = line.split(':')[-1].strip()

            # Get calculated health from ioreg
            result2 = subprocess.run(
                ["ioreg", "-rn", "AppleSmartBattery"],
                capture_output=True, timeout=5
            )
            output2 = result2.stdout.decode('utf-8', 'replace')
            nominal_cap = None
            design_cap = None
            calc_health = "N/A"
            for line in output2.split('\n'):
                if '"NominalChargeCapacity"' in line and '=' in line:
                    try:
                        nominal_cap = int(line.split('=')[-1].strip())
                    except:
                        pass
                if '"DesignCapacity"' in line and '=' in line:
                    try:
                        design_cap = int(line.split('=')[-1].strip())
                    except:
                        pass
            if nominal_cap and design_cap and design_cap > 0:
                calc_health = str(int(nominal_cap * 100 / design_cap)) + "%"
                cap_info = str(nominal_cap) + "/" + str(design_cap) + " mAh"
            else:
                cap_info = "N/A"

            # Get state file info
            script_cycles = 0
            initial_health = "N/A"
            initial_apple_cycles = "N/A"
            total_active_secs = 0
            total_discharge_secs = 0
            total_charge_secs = 0
            if os.path.exists(STATE_FILE):
                try:
                    with open(STATE_FILE, 'rb') as f:
                        content = f.read().decode('ascii', 'replace')
                        for line in content.split('\n'):
                            if line.startswith("TOTAL_DISCHARGE_CYCLES="):
                                script_cycles = int(line.split("=")[1].strip())
                            elif line.startswith("INITIAL_HEALTH="):
                                val = line.split("=")[1].strip().strip('"')
                                if val and val != "":
                                    initial_health = val + "%"
                            elif line.startswith("INITIAL_APPLE_CYCLES="):
                                val = line.split("=")[1].strip().strip('"')
                                if val and val != "":
                                    initial_apple_cycles = val
                            elif line.startswith("TOTAL_ACTIVE_SECS="):
                                try:
                                    total_active_secs = int(line.split("=")[1].strip())
                                except:
                                    pass
                            elif line.startswith("TOTAL_DISCHARGE_SECS="):
                                try:
                                    total_discharge_secs = int(line.split("=")[1].strip())
                                except:
                                    pass
                            elif line.startswith("TOTAL_CHARGE_SECS="):
                                try:
                                    total_charge_secs = int(line.split("=")[1].strip())
                                except:
                                    pass
                except:
                    pass

            # Format time
            def fmt_time(secs):
                if secs == 0:
                    return "0m"
                hours = secs // 3600
                mins = (secs % 3600) // 60
                if hours > 0:
                    return str(hours) + "h " + str(mins) + "m"
                return str(mins) + "m"

            # Calculate cycles added
            cycles_added = "N/A"
            if apple_cycles != "N/A" and initial_apple_cycles != "N/A":
                try:
                    cycles_added = str(int(apple_cycles) - int(initial_apple_cycles))
                except:
                    pass

            # Calculate health change
            health_change = "N/A"
            if initial_health != "N/A" and calc_health != "N/A":
                try:
                    init_val = float(initial_health.replace("%", ""))
                    curr_val = float(calc_health.replace("%", ""))
                    diff = curr_val - init_val
                    health_change = ("+" if diff >= 0 else "") + str(round(diff, 1)) + "%"
                except:
                    pass

            # Build stats message - pure ASCII
            stats = (
                "=== BATTERY HEALTH ===\\n"
                "Apple Reported: " + str(apple_health) + "\\n"
                "Calculated: " + str(calc_health) + "\\n"
                "Capacity: " + str(cap_info) + "\\n"
                "Condition: " + str(condition) + "\\n"
                "\\n"
                "=== CYCLE COUNTS ===\\n"
                "Apple Cycles: " + str(apple_cycles) + "\\n"
                "App Cycles: " + str(script_cycles) + "\\n"
                "Apple Cycles Added: " + str(cycles_added) + "\\n"
                "\\n"
                "=== SESSION STATS ===\\n"
                "Total Active: " + fmt_time(total_active_secs) + "\\n"
                "Time Discharging: " + fmt_time(total_discharge_secs) + "\\n"
                "Time Charging: " + fmt_time(total_charge_secs) + "\\n"
                "\\n"
                "=== CHANGES ===\\n"
                "Initial Health: " + str(initial_health) + "\\n"
                "Health Change: " + str(health_change) + "\\n"
                "Initial Cycles: " + str(initial_apple_cycles) + "\\n"
                "\\n"
                "=== SETTINGS ===\\n"
                "CPU: " + str(self.config.get("cpu_stress", "off")).title() + "  "
                "GPU: " + str(self.config.get("gpu_stress", "off")).title()
            )

            # Use osascript to display dialog (avoids rumps encoding)
            script = 'display dialog "{}" with title "Battery Cycler Stats" buttons {{"OK"}} default button "OK"'.format(stats)
            subprocess.run(["osascript", "-e", script])
        except Exception as e:
            subprocess.run(["osascript", "-e", 'display dialog "Error: {}" with title "Error"'.format(str(e).replace('"', "'"))])

    def pause_at_percent(self, sender):
        # Get the percentage from the menu item
        val = int(sender.title.replace("%", ""))
        self.config["pause_limit"] = val
        self.save_config()

        # Update menu checkmarks
        self.pause_menu.title = "Pause (Hold at {}%)".format(val)
        for item in self.pause_menu.values():
            item.state = 1 if item.title == sender.title else 0

        # Stop the cycling script if running
        if self.script_process and self.script_process.poll() is None:
            try:
                os.killpg(os.getpgid(self.script_process.pid), signal.SIGTERM)
            except:
                self.script_process.terminate()
            self.script_process = None

        # Kill any stress processes
        subprocess.run(["pkill", "-9", "stress-ng"], capture_output=True)
        subprocess.run(["pkill", "-f", "ffmpeg.*videotoolbox"], capture_output=True)

        # Use battery CLI to maintain at selected percentage
        run_battery_cmd(["maintain", str(val)])
        rumps.notification("Battery Cycler", "", "Paused - holding at {}%".format(val))
        self.update_status(None)

    def stop_at_percent(self, sender):
        # Get the percentage from the menu item
        val = int(sender.title.replace("%", ""))
        self.config["reset_limit"] = val
        self.save_config()

        # Update menu checkmarks
        self.stop_menu.title = "Stop & Reset to {}%".format(val)
        for item in self.stop_menu.values():
            item.state = 1 if item.title == sender.title else 0

        # Stop the cycling script if running
        if self.script_process and self.script_process.poll() is None:
            try:
                os.killpg(os.getpgid(self.script_process.pid), signal.SIGTERM)
            except:
                self.script_process.terminate()
            self.script_process = None

        # Kill any stress processes
        subprocess.run(["pkill", "-9", "stress-ng"], capture_output=True)
        subprocess.run(["pkill", "-f", "ffmpeg.*videotoolbox"], capture_output=True)

        # Use battery CLI to maintain at selected percentage
        run_battery_cmd(["maintain", str(val)])
        rumps.notification("Battery Cycler", "", "Stopped - reset to {}% limit".format(val))
        self.update_status(None)

    def quit_app(self, _):
        if self.script_process and self.script_process.poll() is None:
            try:
                os.killpg(os.getpgid(self.script_process.pid), signal.SIGTERM)
            except:
                self.script_process.terminate()
        rumps.quit_application()


if __name__ == "__main__":
    BatteryCyclerApp().run()

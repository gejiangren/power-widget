#!/bin/bash
# 一键安装 PowerWidget。

# 检测 1: Apple Silicon
ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    osascript -e 'display alert "只支持 Apple Silicon Mac" message "PowerWidget 只能在 M1/M2/M3/M4 芯片的 Mac 上运行。\n你的 Mac 是 Intel 芯片(x86_64)。" as critical' >/dev/null
    exit 1
fi

# 检测 2: App Translocation
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
if [[ "$SCRIPT_DIR" == *AppTranslocation* ]] || [ ! -d "$SCRIPT_DIR/PowerWidget.app" ]; then
    osascript -e 'display alert "请先解压到固定位置" message "请把 PowerWidget 文件夹整个拖到「桌面」或「下载」,然后再双击 install.command。" as warning' >/dev/null
    exit 1
fi

cd "$SCRIPT_DIR"
APP_FULL_PATH="$SCRIPT_DIR/PowerWidget.app"

echo "==> 正在安装 PowerWidget..."
echo ""

echo "[1/5] 解除 macOS 安全标记..."
xattr -dr com.apple.quarantine PowerWidget.app 2>/dev/null
xattr -dr com.apple.quarantine install.command 2>/dev/null
xattr -dr com.apple.quarantine uninstall.command 2>/dev/null

echo "[2/5] 停止旧实例(如果有)..."
pkill -f "PowerWidget.app/Contents/MacOS/PowerWidget" 2>/dev/null
pkill -f "python.*power_widget" 2>/dev/null
sleep 1
rm -f /tmp/power_widget.lock

echo "[3/5] 写后台服务配置文件..."
# 写 powermetrics LaunchDaemon plist
cat > /tmp/_powerwidget_pm.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.local.powerwidget-pm</string>
<key>ProgramArguments</key><array>
<string>/usr/bin/powermetrics</string>
<string>--samplers</string><string>cpu_power,thermal</string>
<string>-i</string><string>2000</string>
<string>-n</string><string>9999999</string>
<string>-o</string><string>/tmp/pm_widget.log</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardErrorPath</key><string>/dev/null</string>
</dict></plist>
PLIST

# 写日志清理 LaunchDaemon plist(超过 200MB 自动 truncate)
cat > /tmp/_powerwidget_clean.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.local.powerwidget-clean</string>
<key>ProgramArguments</key><array>
<string>/bin/sh</string><string>-c</string>
<string>for f in /tmp/asitop_powermetrics* /tmp/pm_widget.log; do [ -f "$f" ] && [ $(stat -f%z "$f") -gt 209715200 ] && /usr/bin/truncate -s 0 "$f"; done</string>
</array>
<key>StartInterval</key><integer>1800</integer>
<key>RunAtLoad</key><true/>
</dict></plist>
PLIST

echo "[4/5] 装后台服务(需要授权一次,弹密码框请输你的 Mac 登录密码)..."

# 让 Terminal 浮到前面,确保后续 alert / 密码框可见
osascript -e 'tell application "Terminal" to activate' 2>/dev/null

# 静音预警 alert(modal,用户必须点掉,确保盯着屏幕,不会错过紧跟的密码框)
osascript -e 'display alert "需要 Mac 密码授权" message "下一步会弹一个 macOS 系统密码框 — 请输入你的 Mac 登录密码,授权后台数据采集服务(只输这一次,重启后自动启动,不再问)。\n\n如果密码框被其他窗口挡住,请按 ⌘+Tab 切换找到它。" buttons {"我已了解,继续"} default button "我已了解,继续"' >/dev/null

osascript -e 'do shell script "
launchctl bootout system /Library/LaunchDaemons/com.local.powerwidget-pm.plist 2>/dev/null;
launchctl bootout system /Library/LaunchDaemons/com.local.powerwidget-clean.plist 2>/dev/null;
cp /tmp/_powerwidget_pm.plist /Library/LaunchDaemons/com.local.powerwidget-pm.plist &&
cp /tmp/_powerwidget_clean.plist /Library/LaunchDaemons/com.local.powerwidget-clean.plist &&
chmod 644 /Library/LaunchDaemons/com.local.powerwidget-pm.plist /Library/LaunchDaemons/com.local.powerwidget-clean.plist &&
launchctl bootstrap system /Library/LaunchDaemons/com.local.powerwidget-pm.plist &&
launchctl bootstrap system /Library/LaunchDaemons/com.local.powerwidget-clean.plist
" with administrator privileges' || {
    osascript -e 'display alert "授权失败" message "后台服务没装上,widget 会显示「等数据」。\n\n请再双击一次 install.command 重试,在密码框里输入你的 Mac 登录密码。" as warning' >/dev/null
    exit 1
}

# 配置 widget 用户级开机自启
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/com.local.powerwidget-app.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$LAUNCH_AGENT_PLIST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.local.powerwidget-app</string>
<key>ProgramArguments</key>
<array>
<string>/usr/bin/open</string>
<string>$APP_FULL_PATH</string>
</array>
<key>RunAtLoad</key><true/>
<key>StandardErrorPath</key><string>/tmp/powerwidget-agent.err</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT_PLIST" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT_PLIST" 2>/dev/null

echo "[5/5] 启动 PowerWidget..."
# 等 daemon 启动产生数据(2-3 秒)
sleep 3
open PowerWidget.app
sleep 2

osascript -e 'display alert "PowerWidget 已启动" message "桌面右上角应该出现深色半透明小组件,显示当前 CPU 功耗、电池电量、机身热度等。\n\n看不到?按 F11 或触控板四指张开 = 显示桌面。\n\n开机会自动启动,不再问密码。\n\n卸载请用 uninstall.command,不要只拖废纸篒。" buttons {"好的"} default button "好的"' >/dev/null

echo ""
echo "==> 完成!按任意键关闭本窗口。"
read -n 1 -s
exit 0

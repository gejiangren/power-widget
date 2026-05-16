#!/bin/bash
# 双击此文件即可卸载 PowerWidget。
# 会停止并删除后台服务、清掉日志和缓存。会要求一次 Mac 密码。

echo "==> 正在卸载 PowerWidget..."

# 停 widget 进程
pkill -f "python.*power_widget" 2>/dev/null
killall PowerWidget 2>/dev/null

# 卸用户级 LaunchAgent(widget 自启)— 不需要 sudo
echo "==> 移除开机自启..."
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/com.local.powerwidget-app.plist"
launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT_PLIST" 2>/dev/null
rm -f "$LAUNCH_AGENT_PLIST"

# 停止 + 删除系统 LaunchDaemons(需要 sudo)
echo "==> 移除后台服务(可能弹密码框)..."
sudo launchctl bootout system /Library/LaunchDaemons/com.local.powerwidget-pm.plist 2>/dev/null
sudo launchctl bootout system /Library/LaunchDaemons/com.local.powerwidget-clean.plist 2>/dev/null
sudo rm -f /Library/LaunchDaemons/com.local.powerwidget-pm.plist
sudo rm -f /Library/LaunchDaemons/com.local.powerwidget-clean.plist

# 杀掉 powermetrics 子进程
sudo killall powermetrics 2>/dev/null

# 清理临时文件和锁
sudo rm -f /tmp/pm_widget.log
rm -f /tmp/power_widget.lock
rm -f /tmp/_pm.plist /tmp/_clean.plist

# 删除用户偏好(位置记忆等)
defaults delete com.local.powerwidget 2>/dev/null

echo ""
echo "==> 完成!"
echo "==> 接下来请把 PowerWidget.app 拖到废纸篓。"
echo ""
read -n 1 -s -r -p "按任意键关闭本窗口..."
echo ""

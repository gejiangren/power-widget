#!/usr/bin/env python3
"""macOS 功耗浮窗 — 桌面图标层,可拖,双击退出。
   左:圆环(SoC 占满 30W 的百分比) + 环内百分数
   右:大字 W 数 + 小字电池流量"""
import subprocess, re, threading, objc, os, time, glob, sys, traceback, atexit
from Foundation import NSObject, NSTimer, NSAttributedString, NSMutableAttributedString, NSUserDefaults, NSPointFromString, NSStringFromPoint, NSNotificationCenter
from AppKit import (
    NSApplication, NSWindow, NSView, NSTextField, NSColor, NSFont,
    NSBackingStoreBuffered, NSScreen, NSBezierPath,
    NSWindowStyleMaskBorderless,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSTextAlignmentCenter,
    NSApplicationActivationPolicyAccessory,
    NSVisualEffectView,
    NSVisualEffectMaterialPopover,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectStateActive,
    NSFontAttributeName, NSForegroundColorAttributeName, NSBaselineOffsetAttributeName,
    NSWorkspace, NSEvent,
)
from Quartz import kCGDesktopIconWindowLevel


LOG_PATH = os.path.expanduser('~/Library/Logs/PowerWidget.log')
_log = None


def _setup_logging():
    """重定向 stdout/stderr 到 log 文件 + 捕获未处理异常。在 main() 启动时调用。"""
    global _log
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        _log = open(LOG_PATH, 'a', buffering=1)
        sys.stderr = _log
        sys.stdout = _log
        _log.write(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] === widget 启动 PID={os.getpid()} ===\n')

        def _log_uncaught(exc_type, exc_value, tb):
            try:
                _log.write(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] !!! 未捕获异常:\n')
                traceback.print_exception(exc_type, exc_value, tb, file=_log)
            except Exception:
                pass

        sys.excepthook = _log_uncaught
    except Exception:
        pass


import fcntl
_LOCK_PATH = '/tmp/power_widget.lock'
_lock_fp = None  # 模块级持有,防止 GC 释放锁


def _acquire_single_instance_lock():
    """单实例锁:已有实例则退出。在 main() 启动时调用。"""
    global _lock_fp
    try:
        _lock_fp = open(_LOCK_PATH, 'w')
        fcntl.flock(_lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fp.write(str(os.getpid()))
        _lock_fp.flush()
    except BlockingIOError:
        # 弹通知让用户知道(否则双击没反应会以为坏了)
        try:
            subprocess.run([
                '/usr/bin/osascript', '-e',
                'display notification "PowerWidget 已在桌面运行,按 F11 显示桌面查看" with title "PowerWidget"'
            ], timeout=3, capture_output=True)
        except Exception:
            pass
        try:
            sys.stderr.write(f'[{time.strftime("%H:%M:%S")}] 已有 widget 实例,退出\n')
        except Exception:
            pass
        sys.exit(0)


def read_soc_power():
    """读 SoC combined_power(W);兼容 asitop 的 plist 和 powermetrics 的 text。"""
    candidates = glob.glob('/tmp/asitop_powermetrics*') + ['/tmp/pm_widget.log']
    fresh = [f for f in candidates if os.path.exists(f)
             and time.time() - os.path.getmtime(f) < 5]
    if not fresh:
        return None
    f = max(fresh, key=os.path.getmtime)
    try:
        with open(f, 'rb') as fh:
            try:
                fh.seek(-300_000, 2)
            except OSError:
                fh.seek(0)
            text = fh.read().decode('utf-8', errors='ignore')
        m = re.findall(r'<key>combined_power</key>\s*<real>([\d.]+)</real>', text)
        if m:
            return float(m[-1]) / 1000.0
        m = re.findall(r'Combined Power.*?:\s*([\d.]+)\s*mW', text)
        if m:
            return float(m[-1]) / 1000.0
    except Exception:
        pass
    return None


APP_MAP = {
    'WindowServer': '系统(桌面)',
    'kernel_task': '系统(内核)',
    'launchd': '系统',
    'mds': '系统(索引)',
    'mds_stores': '系统(索引)',
    'mdworker': '系统(索引)',
    'corespotlightd': '系统(搜索)',
    'MTLCompilerServi': '系统(显卡编译)',
    'fileproviderd': '系统(iCloud)',
    'nsurlsessiond': '系统(下载)',
    'SpeechSynthesisS': '系统(语音)',
    'com.apple.audio.': '系统(音频)',
    'mediaanalysisd': '系统(媒体)',
    'powerd': '系统(电源)',
    'bluetoothd': '系统(蓝牙)',
    'cfprefsd': '系统',
    'Dock': '系统(Dock)',
    'Finder': '访达',
    'Activity Monito': '活动监视器',
    'Claude': 'Claude',
    'Claude Helper': 'Claude',
    'Google Chrome': 'Chrome',
    'Google Chrome H': 'Chrome',
    'Safari Web Cont': 'Safari',
    'Safari': 'Safari',
    'WeChat': '微信',
    'WeChatAppEx': '微信',
    'QQ': 'QQ',
    'Microsoft Word': 'Word',
    'Microsoft Excel': 'Excel',
    'Microsoft Power': 'PPT',
    'Code': 'VS Code',
    'Visual Studio C': 'VS Code',
    'iTerm2': 'iTerm',
    'Terminal': '终端',
    'Music': '音乐',
    'Mail': '邮件',
    'Calendar': '日历',
    'Notes': '备忘录',
    'Photos': '照片',
}


def humanize(name):
    name = name.strip()
    for key, val in APP_MAP.items():
        if name == key or name.startswith(key):
            return val
    # 去除 " Helper" / " (Renderer)" 等后缀
    if ' Helper' in name:
        return name.split(' Helper')[0]
    if '(' in name:
        return name.split('(')[0].strip()
    return name


def power_level(p):
    if p >= 30: return '高'
    if p >= 10: return '中'
    if p > 0: return '低'
    return '微'


def get_gui_apps():
    """{executable_name: localized_name},只含 Dock 里有图标的 GUI app。"""
    apps = {}
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.activationPolicy() == 0:  # NSApplicationActivationPolicyRegular
            exe = app.executableURL()
            if exe is None:
                continue
            apps[str(exe.lastPathComponent())] = str(app.localizedName())
    return apps


def read_top_apps(n=3):
    """top N 个高耗电 GUI 应用。
       per-line 容错:任一进程行解析失败,只跳过它,不影响其他行。"""
    gui = get_gui_apps()
    if not gui:
        return []
    # subprocess 调用:失败=没数据源,直接空
    try:
        out = subprocess.check_output(
            ['/usr/bin/top', '-l', '2', '-s', '1', '-o', 'power',
             '-stats', 'command,power', '-n', '50'],
            stderr=subprocess.DEVNULL, timeout=4
        ).decode('utf-8', errors='replace')
    except Exception:
        return []
    # 定位第二次采样的 COMMAND header
    lines = [l.strip() for l in out.split('\n') if l.strip()]
    start = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith('COMMAND'):
            start = i + 1
            break
    if start < 0:
        return []
    # 逐行解析,每行独立 try
    merged = {}
    for line in lines[start:]:
        try:
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            cmd = parts[0].strip()
            power = float(parts[1])
        except Exception:
            continue  # 这一行有问题,跳过,不影响后续
        try:
            for exe, display in gui.items():
                if cmd == exe or cmd.startswith(exe + ' ') or (exe and cmd.startswith(exe[:14])):
                    merged[display] = merged.get(display, 0.0) + power
                    break
        except Exception:
            continue
    return sorted(merged.items(), key=lambda x: -x[1])[:n]


THERMAL_MAP = {
    'Nominal':  '正常',
    'Light':    '微热',
    'Moderate': '偏热',
    'Heavy':    '较热',
    'Trapping': '严重发热',
    'Sleeping': '过热保护',
}


def read_thermal_pressure():
    """从 powermetrics plist 读最近的 thermal_pressure 等级。
       返回 (中文等级, 严重程度 0-3),严重程度用于上色。"""
    severity_order = {'Nominal': 0, 'Light': 1, 'Moderate': 1,
                      'Heavy': 2, 'Trapping': 3, 'Sleeping': 3}
    for f in glob.glob('/tmp/asitop_powermetrics*') + ['/tmp/pm_widget.log']:
        try:
            if not os.path.exists(f) or time.time() - os.path.getmtime(f) > 10:
                continue
            with open(f, 'rb') as fh:
                try:
                    fh.seek(-300_000, 2)
                except OSError:
                    fh.seek(0)
                text = fh.read().decode('utf-8', errors='replace')
            # asitop plist 格式
            m = re.findall(r'<key>thermal_pressure</key>\s*<string>([^<]+)</string>', text)
            if not m:
                # 我们 daemon 跑的文本格式:Current pressure level: Nominal
                m = re.findall(r'[Cc]urrent pressure level:\s*(\w+)', text)
            if m:
                en = m[-1]
                return THERMAL_MAP.get(en, en), severity_order.get(en, 0)
        except Exception:
            continue
    return '', 0


def read_battery():
    """返回 (状态字符串, 温度字符串, 电量百分比 0-1)"""
    try:
        raw = subprocess.check_output(
            ['ioreg', '-rw0', '-c', 'AppleSmartBattery'], stderr=subprocess.DEVNULL
        ).decode()
    except Exception:
        return '电池读取失败', '', 0.0
    def grab(pat):
        m = re.search(pat, raw)
        return int(m.group(1)) if m else 0
    v = grab(r'"Voltage"\s*=\s*(\d+)') / 1000.0
    i = grab(r'"InstantAmperage"\s*=\s*(-?\d+)')
    if i > 2**31:
        i -= 2**64
    i /= 1000.0
    soc_pct = grab(r'"CurrentCapacity"\s*=\s*(\d+)') / 100.0  # 跟 macOS 状态栏一致
    batt = v * i
    ext = '"ExternalConnected" = Yes' in raw
    charging = '"IsCharging" = Yes' in raw
    full = '"FullyCharged" = Yes' in raw
    if not ext:
        state = f'整机 {-batt:.1f} W'
    elif charging:
        state = f'电池 +{batt:.1f} W'
    elif full:
        state = '电池 满电'
    else:
        state = '插电 (暂停充电)'
    return state, soc_pct


def _is_point_on_some_screen(origin, w, h):
    """检测 widget frame(以 origin 为左下角)是否至少有一部分在某块 screen 内。"""
    try:
        ox, oy = (origin.x, origin.y) if hasattr(origin, 'x') else (origin[0], origin[1])
        for screen in NSScreen.screens():
            f = screen.visibleFrame()
            if (ox + w > f.origin.x and ox < f.origin.x + f.size.width and
                oy + h > f.origin.y and oy < f.origin.y + f.size.height):
                return True
    except Exception:
        pass
    return False


class RingView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(RingView, self).initWithFrame_(frame)
        if self:
            self._pct = 0.0
            self._label = ''
        return self

    def hitTest_(self, point):
        return None  # 圆环也鼠标穿透,不挡拖动

    @objc.python_method
    def updatePercent(self, p, label=None):
        self._pct = max(0.0, min(1.0, p))
        self._label = label if label is not None else f'{int(self._pct * 100)}%'
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        b = self.bounds()
        cx, cy = b.size.width / 2.0, b.size.height / 2.0
        r = min(cx, cy) - 5

        bg = NSBezierPath.bezierPath()
        bg.setLineWidth_(5.0)
        bg.appendBezierPathWithOvalInRect_(((cx - r, cy - r), (2 * r, 2 * r)))
        NSColor.quaternaryLabelColor().set()
        bg.stroke()

        pct = getattr(self, '_pct', 0)
        if pct > 0:
            arc = NSBezierPath.bezierPath()
            arc.setLineWidth_(6.0)
            arc.setLineCapStyle_(1)  # round
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                (cx, cy), r, 90.0, 90.0 - pct * 360.0, True
            )
            NSColor.systemGreenColor().set()
            arc.stroke()

        # 中央文字 — drawAtPoint 计算精确居中
        text = getattr(self, '_label', '')
        if text:
            attrs = {
                NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(13, 0.4),
                NSForegroundColorAttributeName: NSColor.labelColor(),
            }
            attr_str = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
            size = attr_str.size()
            x = (b.size.width - size.width) / 2.0
            y = (b.size.height - size.height) / 2.0
            attr_str.drawAtPoint_((x, y))


class PassLabel(NSTextField):
    """鼠标穿透的 label,点击事件冒泡到背景 view(让整窗都能拖)"""
    def hitTest_(self, point):
        return None


class BgView(NSVisualEffectView):
    """整窗可拖。手动 mouseDown/Dragged/Up + setFrameOrigin_,不依赖 macOS 的
       performWindowDragWithEvent(那个 API 在 borderless 桌面图标层 window 上跑久了会假死)。
       hitTest_ 强制返回 self,绕开 NSVisualEffectView 默认 hitTest 在长时间运行后偶尔返回 nil 的问题。"""

    def hitTest_(self, point):
        return self

    def mouseDown_(self, event):
        # 每次按下都 orderFront 一次,即使 keepalive 错过也保证后续事件能到
        try:
            self.window().orderFront_(None)
        except Exception:
            pass
        if event.clickCount() == 2:
            NSApplication.sharedApplication().terminate_(None)
            return
        self._dragStartMouse = NSEvent.mouseLocation()
        self._dragStartOrigin = self.window().frame().origin

    def mouseDragged_(self, event):
        start = getattr(self, '_dragStartMouse', None)
        if start is None:
            return
        cur = NSEvent.mouseLocation()
        dx = cur.x - start.x
        dy = cur.y - start.y
        self.window().setFrameOrigin_(
            (self._dragStartOrigin.x + dx, self._dragStartOrigin.y + dy)
        )

    def mouseUp_(self, event):
        self._dragStartMouse = None
        self._dragStartOrigin = None


class Controller(NSObject):
    def setup(self):
        w, h = 178, 154  # 顶部多 14 给热度行
        # 默认右上角
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + screen.size.width - w - 24
        y = screen.origin.y + screen.size.height - h - 24
        # 恢复上次的位置(如果还在某块屏幕内)
        defaults = NSUserDefaults.standardUserDefaults()
        saved = defaults.stringForKey_('widgetOrigin')
        if saved:
            try:
                p = NSPointFromString(saved)
                if _is_point_on_some_screen(p, w, h):
                    x, y = p.x, p.y
            except Exception:
                pass

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((x, y), (w, h)), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setOpaque_(False)
        self.window.setHasShadow_(False)
        self.window.setLevel_(kCGDesktopIconWindowLevel)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
        )
        # 不用 setMovableByWindowBackground,跟 performWindowDragWithEvent 冲突。
        # 改用 BgView.mouseDown_ 显式 performWindowDragWithEvent_ 处理拖动。
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, 'windowDidMove:', 'NSWindowDidMoveNotification', self.window
        )

        bg = BgView.alloc().initWithFrame_(((0, 0), (w, h)))
        bg.setMaterial_(NSVisualEffectMaterialPopover)
        bg.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        bg.setState_(NSVisualEffectStateActive)
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(18.0)
        bg.layer().setMasksToBounds_(True)
        self.window.setContentView_(bg)
        self.window.invalidateShadow()

        capFont = NSFont.systemFontOfSize_weight_(9, 0.3)
        capColor = NSColor.tertiaryLabelColor()
        OFFSET = 62  # 主区上移留出底部 top apps 空间

        # 左:圆环(中央百分数由 RingView 自画,精确居中) + 下方"电量"
        self.ring = RingView.alloc().initWithFrame_(((10, 14 + OFFSET), (56, 56)))
        bg.addSubview_(self.ring)
        bg.addSubview_(self._label((10, 0 + OFFSET, 56, 12), '电量', capFont, capColor))

        # 右:大字(inline "芯片" 前缀 + 数字)+ 小字(自带主语)
        self.powerLabel = self._label((72, 35 + OFFSET, 100, 26), '…',
            NSFont.monospacedDigitSystemFontOfSize_weight_(22, 0.56),
            NSColor.labelColor())
        bg.addSubview_(self.powerLabel)
        smallFont = NSFont.systemFontOfSize_weight_(12, 0.23)
        self.stateLabel = self._label((72, 6 + OFFSET, 100, 18), '…', smallFont, NSColor.secondaryLabelColor())
        bg.addSubview_(self.stateLabel)

        # 顶部:散热压力(macOS thermal_pressure 中文翻译,颜色随严重程度变)
        thermFont = NSFont.systemFontOfSize_weight_(11, 0.3)
        self.thermLabel = self._label((10, h - 16, w - 20, 12), '散热压力: …', thermFont, NSColor.tertiaryLabelColor())
        bg.addSubview_(self.thermLabel)

        # 底部:top apps 区
        bg.addSubview_(self._label((10, 48, w - 20, 10), '应用耗电指数(越大越耗电)', capFont, capColor))
        appFont = NSFont.systemFontOfSize_weight_(11, 0.23)
        self.appLabels = []
        for i in range(3):
            y_app = 32 - i * 14
            nameLbl = self._label((10, y_app, 110, 14), '—', appFont, NSColor.labelColor())
            nameLbl.setAlignment_(0)  # 左对齐
            powerLbl = self._label((120, y_app, w - 130, 14), '', appFont, NSColor.secondaryLabelColor())
            powerLbl.setAlignment_(2)  # 右对齐
            bg.addSubview_(nameLbl)
            bg.addSubview_(powerLbl)
            self.appLabels.append((nameLbl, powerLbl))

        self.window.makeKeyAndOrderFront_(None)

        self._reading = False
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True
        )

    @objc.python_method
    def _label(self, frame, text, font, color):
        x, y, w, h = frame
        lbl = PassLabel.alloc().initWithFrame_(((x, y), (w, h)))
        lbl.setStringValue_(text)
        lbl.setFont_(font)
        lbl.setTextColor_(color)
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        lbl.setAlignment_(NSTextAlignmentCenter)
        return lbl

    def tick_(self, sender):
        if not self._reading:
            self._reading = True
            threading.Thread(target=self._bgRead, daemon=True).start()
        # 每 3 秒额外刷新一次 top apps(top 命令耗时 1.5s,频率不能太高)
        self._tickCount = getattr(self, '_tickCount', 0) + 1
        if self._tickCount % 3 == 1 and not getattr(self, '_readingTop', False):
            self._readingTop = True
            threading.Thread(target=self._bgReadTop, daemon=True).start()
        # 每 2 秒主动 orderFront,强制 WindowServer 重新派事件
        # (短间隔避免"两次刷新之间偶尔掉线"现象)
        if self._tickCount % 2 == 0:
            try:
                self.window.orderFront_(None)
            except Exception:
                pass

    @objc.python_method
    def _bgReadTop(self):
        try:
            apps = read_top_apps(3)
        except Exception:
            apps = []
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyTopApps:", apps, False
        )

    def applyTopApps_(self, apps):
        for i, (nameLbl, powerLbl) in enumerate(self.appLabels):
            if i < len(apps):
                name, power = apps[i]
                p = float(power)
                nameLbl.setStringValue_(str(name)[:14])
                powerLbl.setStringValue_(f'{p:.0f}')
                if p >= 30:
                    powerLbl.setTextColor_(NSColor.systemRedColor())
                elif p >= 10:
                    powerLbl.setTextColor_(NSColor.systemOrangeColor())
                else:
                    powerLbl.setTextColor_(NSColor.secondaryLabelColor())
            else:
                nameLbl.setStringValue_('—')
                powerLbl.setStringValue_('')
                powerLbl.setTextColor_(NSColor.secondaryLabelColor())
        self._readingTop = False

    @objc.python_method
    def _bgRead(self):
        try:
            soc = read_soc_power()
            small, batt_pct = read_battery()
            therm_cn, therm_sev = read_thermal_pressure()
            if soc is None:
                info = {'big': '等数据', 'small': '需要 asitop 在跑',
                        'pct': batt_pct, 'pctText': f'{int(batt_pct * 100)}%',
                        'thermal': therm_cn, 'thermalSev': therm_sev}
            else:
                info = {
                    'big': f'{soc:.1f} W',
                    'small': small,
                    'pct': batt_pct,
                    'pctText': f'{int(batt_pct * 100)}%',
                    'thermal': therm_cn,
                    'thermalSev': therm_sev,
                }
        except Exception:
            info = {'big': '--', 'small': '读取失败', 'pct': 0.0, 'pctText': '--',
                    'thermal': '', 'thermalSev': 0}
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyResult:", info, False
        )

    def windowDidMove_(self, _notif):
        # 拖动结束保存 widget 位置
        try:
            p = self.window.frame().origin
            NSUserDefaults.standardUserDefaults().setObject_forKey_(
                NSStringFromPoint(p), 'widgetOrigin'
            )
        except Exception:
            pass

    def applyResult_(self, info):
        big = info['big']
        if 'W' in big:
            # "芯片  " 小灰字 + 大字 W 数字 inline
            attr = NSMutableAttributedString.alloc().init()
            attr.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(
                '芯片 ',
                {
                    NSFontAttributeName: NSFont.systemFontOfSize_weight_(11, 0.3),
                    NSForegroundColorAttributeName: NSColor.tertiaryLabelColor(),
                    NSBaselineOffsetAttributeName: 3.0,
                }
            ))
            attr.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(
                big,
                {
                    NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(22, 0.56),
                    NSForegroundColorAttributeName: NSColor.labelColor(),
                }
            ))
            self.powerLabel.setAttributedStringValue_(attr)
        else:
            self.powerLabel.setStringValue_(big)
        self.stateLabel.setStringValue_(info['small'])
        self.ring.updatePercent(info['pct'], info['pctText'])
        # 热度行
        therm = info.get('thermal', '')
        sev = info.get('thermalSev', 0)
        if therm:
            self.thermLabel.setStringValue_(f'散热压力: {therm}')
            if sev >= 3:
                self.thermLabel.setTextColor_(NSColor.systemRedColor())
            elif sev == 2:
                self.thermLabel.setTextColor_(NSColor.systemOrangeColor())
            elif sev == 1:
                self.thermLabel.setTextColor_(NSColor.systemYellowColor())
            else:
                self.thermLabel.setTextColor_(NSColor.tertiaryLabelColor())
        else:
            self.thermLabel.setStringValue_('散热压力: —')
            self.thermLabel.setTextColor_(NSColor.tertiaryLabelColor())
        self._reading = False


PM_DAEMON_PATH = '/Library/LaunchDaemons/com.local.powerwidget-pm.plist'
CLEAN_DAEMON_PATH = '/Library/LaunchDaemons/com.local.powerwidget-clean.plist'

PM_DAEMON_PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.local.powerwidget-pm</string>
<key>ProgramArguments</key>
<array>
<string>/usr/bin/powermetrics</string>
<string>--samplers</string><string>cpu_power,thermal</string>
<string>-i</string><string>2000</string>
<string>-n</string><string>9999999</string>
<string>-o</string><string>/tmp/pm_widget.log</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardErrorPath</key><string>/dev/null</string>
</dict></plist>'''

CLEAN_DAEMON_PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.local.powerwidget-clean</string>
<key>ProgramArguments</key>
<array>
<string>/bin/sh</string><string>-c</string>
<string>for f in /tmp/asitop_powermetrics* /tmp/pm_widget.log; do [ -f "$f" ] && [ $(stat -f%z "$f") -gt 209715200 ] && /usr/bin/truncate -s 0 "$f"; done</string>
</array>
<key>StartInterval</key><integer>1800</integer>
<key>RunAtLoad</key><true/>
</dict></plist>'''


def ensure_powermetrics():
    """检测后台服务是否在跑。install.command 应该已经装好 LaunchDaemon,这里不再主动装。"""
    # 不做任何 osascript 弹窗 — widget 是无人值守的浮窗,弹密码框会扰民
    # 数据源由 install.command 装的 LaunchDaemon 提供,这里只是 noop
    pass


_keep = []

def main():
    _setup_logging()
    _acquire_single_instance_lock()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ensure_powermetrics()
    ctrl = Controller.alloc().init()
    ctrl.setup()
    _keep.append(ctrl)
    app.run()


if __name__ == '__main__':
    main()

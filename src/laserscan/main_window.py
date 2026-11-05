"""Main window: sidebar settings, drawing canvas and run controls."""

from __future__ import annotations

import time
from dataclasses import asdict

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from laserscan import __version__, project, settings
from laserscan.canvas import Canvas
from laserscan.devices import HARDWARE_AVAILABLE, serial_ports
from laserscan.executor import State
from laserscan.flow import flow_widget
from laserscan.planning import (
    PATTERNS,
    Params,
    build_plan,
    clean_shape,
    estimate,
    overrun,
    region_polygons,
    shift,
)
from laserscan.session import SESSION

DEFAULT_PORTS = ("COM3", "COM6")
"""Default (stage, shutter) serial ports of the lab machine."""

TOOLS = {
    "select": ("Select", "W"),
    "pen": ("Bézier pen", "Shift+A"),
}
TEXT_MARGIN = 6


def _label(text: str, role: str = "field", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    label.setWordWrap(wrap)
    return label


def _alert(error: bool = True) -> QLabel:
    label = QLabel()
    label.setProperty("role", "alert")
    label.setProperty("error", error)
    label.setWordWrap(True)
    label.hide()
    return label


def _show(label: QLabel, text: str, error: bool | None = None) -> None:
    if error is not None:
        label.setProperty("error", error)
        label.style().unpolish(label)
        label.style().polish(label)
    label.setText(text)
    label.setVisible(bool(text))


def _button(text: str, **props: bool) -> QPushButton:
    button = QPushButton(text)
    for key, value in props.items():
        button.setProperty(key, value)
    return button


def _pill(text: str, tip: str = "", checkable: bool = False, checked: bool = False) -> QPushButton:
    button = _button(text, pill=True)
    button.setToolTip(tip)
    button.setCheckable(checkable)
    button.setChecked(checked)
    return button


def _spin(value: float, low: float, high: float, decimals: int = 1) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.lineEdit().setTextMargins(TEXT_MARGIN, 0, 0, 0)
    return spin


def _field(text: str, widget: QWidget) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(_label(text))
    layout.addWidget(widget)
    return box


def _grid(fields: list[QWidget]) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    for i in range(0, len(fields), 2):
        row = QHBoxLayout()
        row.setSpacing(12)
        for field in fields[i : i + 2]:
            row.addWidget(field, 1)
        if len(fields[i : i + 2]) == 1:
            row.addStretch(1)
        layout.addLayout(row)
    return box


def _pills(options: list[tuple[str, str]], current: str) -> tuple[QButtonGroup, QWidget, dict[str, QPushButton]]:
    row, layout = flow_widget()
    group, buttons = QButtonGroup(row), {}
    for label, value in options:
        button = _pill(label, checkable=True, checked=value == current)
        group.addButton(button)
        layout.addWidget(button)
        buttons[value] = button
    return group, row, buttons


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("h2")
    layout.addWidget(heading)
    return frame, layout


def _soften_popup(popup: QWidget) -> None:
    """Make a popup window frameless and translucent so no dark border or square corners show."""
    window = popup.window()
    window.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    window.setAttribute(Qt.WA_TranslucentBackground)


def _combo() -> QComboBox:
    combo = QComboBox()
    combo.setItemDelegate(QStyledItemDelegate(combo))
    combo.setMaxVisibleItems(12)
    _soften_popup(combo.view())
    return combo


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min {secs} s"


class MainWindow(QMainWindow):
    """The LaserScan window."""

    def __init__(self, simulate: bool = False) -> None:
        """Build the window.

        Args:
            simulate: Connect simulated devices at startup.
        """
        super().__init__()
        self.s = SESSION
        self.profile = settings.load()
        self.simulate = simulate or not HARDWARE_AVAILABLE
        self._traffic_seen = 0
        self._shutter_led: bool | None = None
        self.view_mode = "design"
        self.origin, self.motion = (0.0, 0.0), None
        self._run_plan: list = []
        self._was_running = False
        self.setWindowTitle("LaserScan")
        height = min(860, self.screen().availableGeometry().height() - 40)
        self.resize(1360, height)
        self.setMinimumSize(1100, 640)
        self.canvas = Canvas()
        self._build()
        self._replan_timer = QTimer(self, singleShot=True, interval=150)
        self._replan_timer.timeout.connect(self.replan)
        self.canvas.changed.connect(self.replan)
        self._shortcuts()
        QTimer(self, interval=200, timeout=self._poll).start()
        if self.simulate:
            self.s.devices.connect(simulate=True, start=self._stage_center())
        self._after_connect()
        if not self.simulate:
            QTimer.singleShot(200, self._connect)  # after the window is shown

    def _stage_center(self) -> tuple[float, float]:
        (x0, x1), (y0, y1) = self.profile["x_range_um"], self.profile["y_range_um"]
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(56)
        bar = QHBoxLayout(topbar)
        bar.setContentsMargins(24, 0, 24, 0)
        brand, version = QLabel("LaserScan"), QLabel(f"v{__version__}")
        brand.setObjectName("brand")
        version.setObjectName("version")
        bar.addWidget(self._menu(), 0, Qt.AlignVCenter)
        bar.addSpacing(8)
        bar.addWidget(brand)
        bar.addWidget(version)
        bar.addStretch(1)
        outer.addWidget(topbar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar())
        body.addWidget(self._divider())
        body.addWidget(self._content(), 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)

    def _menu(self) -> QMenuBar:
        """The "Files" menu in the top-left corner."""
        menubar = QMenuBar()
        menubar.setNativeMenuBar(False)
        menubar.setFixedHeight(34)
        menu = menubar.addMenu("Files")
        _soften_popup(menu)
        for text, shortcut, slot in (("Open…", QKeySequence.StandardKey.Open, self._open),
                                     ("Save…", QKeySequence.StandardKey.Save, self._save)):
            action = QAction(text, menu)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            menu.addAction(action)
        return menubar

    def _divider(self) -> QWidget:
        """The grey line between the sidebar and the content."""
        holder = QWidget()
        holder.setFixedWidth(1)
        line = QVBoxLayout(holder)
        line.setContentsMargins(0, 20, 0, 20)
        rule = QFrame()
        rule.setObjectName("divider")
        line.addWidget(rule)
        return holder

    def _sidebar(self) -> QScrollArea:
        panel = QWidget()
        panel.setObjectName("sidebar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 20, 20, 20)
        layout.setSpacing(16)

        card, box = _card("Devices")
        self.stage_port, self.shutter_port = _combo(), _combo()
        box.addWidget(_field("Stage port", self.stage_port))
        box.addWidget(_field("Shutter port", self.shutter_port))
        self._refresh_ports()
        row, flow = flow_widget(8)
        self.connect_btn = _button("Connect")
        self.connect_btn.clicked.connect(self._connect)
        self.device_status = _label("Not connected", "muted", wrap=True)
        flow.addWidget(self.connect_btn)
        flow.addWidget(self.device_status)
        box.addWidget(row)
        self.device_msg = _alert()
        box.addWidget(self.device_msg)
        layout.addWidget(card)

        self.scan_card, box = _card("Scan")
        box.addWidget(_label("Fill pattern (closed shapes)"))
        defaults = Params()
        self.pattern_group, row, self.pattern_buttons = _pills(
            [(p.capitalize(), p) for p in PATTERNS], defaults.pattern
        )
        self.pattern_group.buttonClicked.connect(lambda _b: self._replan_timer.start())
        box.addWidget(row)
        self.step = _spin(defaults.step, 0.01, 1e6, 2)
        self.angle = _spin(defaults.angle, -360, 360, 1)
        self.speed = _spin(defaults.speed, 0.1, 1e5, 1)
        self.margin = _spin(defaults.margin, 0, 1e5, 1)
        self.passes = QSpinBox()
        self.passes.setRange(1, 1000)
        self.passes.setKeyboardTracking(False)
        self.passes.lineEdit().setTextMargins(TEXT_MARGIN, 0, 0, 0)
        box.addWidget(_grid([_field("Step (µm)", self.step), _field("Angle (°)", self.angle),
                             _field("Speed (µm/s)", self.speed), _field("Margin (µm)", self.margin),
                             _field("Passes", self.passes)]))
        for spin in (self.step, self.angle, self.speed, self.margin, self.passes):
            spin.valueChanged.connect(lambda _v: self._replan_timer.start())
        layout.addWidget(self.scan_card)

        card, box = _card("Monitor")
        row, flow = flow_widget(8)
        self.hide_polling = _pill("Hide P / $,S polling", "Hide the position polling commands", True, True)
        clear = _pill("Clear")
        clear.clicked.connect(lambda: self.monitor.clear())
        flow.addWidget(self.hide_polling)
        flow.addWidget(clear)
        box.addWidget(row)
        self.monitor = QPlainTextEdit()
        self.monitor.setObjectName("monitor")
        self.monitor.setReadOnly(True)
        self.monitor.setMaximumBlockCount(500)
        self.monitor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.monitor.setFixedHeight(150)
        box.addWidget(self.monitor)
        layout.addWidget(card)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(404)
        return scroll

    def _content(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("content")
        panel.setMinimumWidth(620)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 24, 20)
        layout.setSpacing(20)

        card, box = _card("Canvas")
        head = box.itemAt(0).widget()
        box.removeWidget(head)
        title_row = QHBoxLayout()
        title_row.addWidget(head)
        self.badge = _label("MONITOR", "badge")
        self.badge.hide()
        title_row.addWidget(self.badge)
        title_row.addStretch(1)
        self.led = QLabel()
        self.led.setObjectName("led")
        self.led.setFixedSize(12, 12)
        self.led.setToolTip("Shutter")
        self.start_btn = _button("Start", primary=True)
        self.pause_btn = _button("Pause")
        self.abort_btn = _button("Abort", danger=True)
        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self.s.executor.toggle_pause)
        self.abort_btn.clicked.connect(lambda: self.s.executor.abort("Aborted by user"))
        title_row.addWidget(_label("Shutter", "muted"))
        title_row.addWidget(self.led)
        title_row.addSpacing(8)
        for button in (self.start_btn, self.pause_btn, self.abort_btn):
            title_row.addWidget(button)
        box.insertLayout(0, title_row)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self.status = _label("Idle", "muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        progress_row.addWidget(self.status)
        progress_row.addWidget(self.progress, 1)
        box.insertLayout(1, progress_row)
        self.estimate = _label("", "muted", wrap=True)
        box.addWidget(self.estimate)
        box.addWidget(self._toolbar())
        self.alerts, self.notice = _alert(), _alert(False)
        box.addWidget(self.alerts)
        box.addWidget(self.notice)
        box.addWidget(self.canvas, 1)
        self.cursor_label = _label("", "muted")
        self.canvas.cursorMoved.connect(self._show_cursor)
        self.canvas.message.connect(lambda text: _show(self.notice, text, False))
        box.addWidget(self.cursor_label)
        layout.addWidget(card, 1)

        return panel

    def _group(self, caption: str, flow, buttons: list[QPushButton]) -> None:
        frame = QFrame()
        frame.setObjectName("group")
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 4, 4, 4)
        row.setSpacing(4)
        row.addWidget(_label(caption.upper(), "caption"))
        for button in buttons:
            row.addWidget(button)
        flow.addWidget(frame)

    def _toolbar(self) -> QWidget:
        bar, flow = flow_widget(8)
        self.design_widgets: list[QWidget] = []

        self.view_group, self.view_buttons = QButtonGroup(bar), {}
        for key, text in (("design", "Design"), ("preview", "Preview")):
            button = _pill(text, f"{text} (Ctrl+{1 if key == 'design' else 2})", True, key == "design")
            self.view_group.addButton(button)
            self.view_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self._set_view(k))
        fit = _pill("Fit", "Fit the view (Home)")
        fit.clicked.connect(self.canvas.fit)
        self.fit_stage_btn = _pill("Fit stage", "Fit the whole stage range (Shift+Home)")
        self.fit_stage_btn.clicked.connect(self.canvas.fit_stage)
        self.fit_stage_btn.hide()
        self._group("View", flow, [*self.view_buttons.values(), fit, self.fit_stage_btn])

        self.tool_group, self.tool_buttons = QButtonGroup(bar), {}
        for key, (text, shortcut) in TOOLS.items():
            button = _pill(text, f"{text} ({shortcut})", True, key == "select")
            self.tool_group.addButton(button)
            self.tool_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self.canvas.set_tool(k))
        self.canvas.toolChanged.connect(lambda t: self.tool_buttons[t].setChecked(True))
        self.tool_buttons["pen"].setToolTip(
            "Bézier pen (Shift+A or W): click to place nodes, click the first node to close, Enter or right-click to finish. "
            "Then set node types and handles in Edit mode."
        )
        self._group("Draw", flow, list(self.tool_buttons.values()))

        self.object_btn = _pill("Object", "Select and move whole shapes (Tab)", True, True)
        self.edit_btn = _pill("Edit", "Edit the nodes of the selected shape (Tab). Double-click an edge to add a node.", True)
        self.mode_pair = QButtonGroup(bar)
        for button in (self.object_btn, self.edit_btn):
            self.mode_pair.addButton(button)
        self.object_btn.clicked.connect(self.canvas.exit_edit)
        self.edit_btn.clicked.connect(self._enter_edit)
        self.canvas.editChanged.connect(self._edit_changed)
        tips = {
            "sharp": "Sharp: remove the handles, straight segments (V menu)",
            "free": "Free: the two handles move independently",
            "smooth": "Smooth: handles stay on one line. Alt-drag a handle to break it",
            "symmetric": "Symmetric: handles on one line, equal length",
        }
        self.node_buttons = []
        for kind in ("sharp", "free", "smooth", "symmetric"):
            button = _pill(kind.capitalize(), tips[kind])
            button.clicked.connect(lambda _c=False, k=kind: self.canvas.set_node_type(k))
            self.node_buttons.append(button)
        self.smooth_btn, self.sharp_btn = self.node_buttons[2], self.node_buttons[0]
        for button in self.node_buttons:
            button.setEnabled(False)
        self._group("Mode", flow, [self.object_btn, self.edit_btn, *self.node_buttons])

        self.op_group, self.op_buttons = QButtonGroup(bar), {}
        tips = {
            "add": "New closed shapes add area (Alt+1)",
            "subtract": "New closed shapes remove area (Alt+2)",
            "merge": "New closed shapes add area and fuse with every shape they touch (Alt+3)",
        }
        for key, text in (("add", "Add"), ("subtract", "Subtract"), ("merge", "Merge")):
            button = _pill(text, tips[key], True, key == "add")
            self.op_group.addButton(button)
            self.op_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self.canvas.set_new_op(k))
        invert = _pill("Invert", "Toggle Add / Subtract of the selected shapes (Shift+X)")
        invert.clicked.connect(self._invert_selected)
        apply_cut = _pill("Apply", "Cut Subtract shapes into the shapes they touch, so the new edges get nodes (Ctrl+B)")
        apply_cut.clicked.connect(self.canvas.apply_subtract)
        self._group("Region", flow, [*self.op_buttons.values(), invert, apply_cut])

        self.snap_btn = _pill("Snap", "Snap to the grid and to vertices (Shift+Tab)", True, True)
        self.snap_btn.toggled.connect(lambda on: setattr(self.canvas, "snap_on", on))
        edit = [self.snap_btn]
        for text, tip, slot in (
            ("Undo", "Undo (Ctrl+Z)", self.canvas.undo),
            ("Redo", "Redo (Ctrl+Shift+Z)", self.canvas.redo),
            ("Delete", "Delete selected shapes (Delete)", self.canvas.delete_selected),
        ):
            button = _pill(text, tip)
            button.clicked.connect(slot)
            edit.append(button)
        self._group("Edit", flow, edit)

        self.design_widgets = [
            *self.tool_buttons.values(),
            self.object_btn,
            self.edit_btn,
            *self.op_buttons.values(),
            invert,
            apply_cut,
            *edit,
        ]
        self.toolbar = bar
        return bar

    def _shortcuts(self) -> None:
        """Blender-style keys. Most act on the canvas while it has focus (it takes focus when the mouse is over it)."""
        canvas = self.canvas

        def window(sequence, slot) -> None:
            QShortcut(QKeySequence(sequence), self, activated=slot)

        def key(sequence, slot) -> None:
            QShortcut(QKeySequence(sequence), canvas, activated=slot, context=Qt.WidgetShortcut)

        def design(slot):
            return lambda: self.view_mode == "design" and slot()

        key("Tab", design(canvas.toggle_edit))
        key("Shift+Tab", lambda: self.snap_btn.isEnabled() and self.snap_btn.click())
        key("Shift+A", design(lambda: self.tool_buttons["pen"].click()))
        key("W", design(canvas.pick_tool))
        key("A", design(canvas.select_all))
        key("Alt+A", design(canvas.deselect_all))
        key("Ctrl+I", design(canvas.invert_selection))
        key("G", design(lambda: canvas.start_transform("grab")))
        key("R", design(lambda: canvas.start_transform("rotate")))
        key("S", design(lambda: canvas.start_transform("scale")))
        key("Shift+D", design(canvas.duplicate))
        key("V", design(canvas.type_menu))
        key("E", design(canvas.extrude))
        key("X", design(lambda: canvas.set_axis("x") if canvas.transforming else canvas.delete_selected()))
        key("Y", design(lambda: canvas.set_axis("y")))
        key("Delete", design(canvas.delete_selected))
        key("Backspace", design(canvas.delete_selected))
        key("Ctrl+B", design(canvas.apply_subtract))
        key("Alt+1", lambda: self._choose_op("add"))
        key("Alt+2", lambda: self._choose_op("subtract"))
        key("Alt+3", lambda: self._choose_op("merge"))
        key("Shift+X", self._invert_selected)
        key("Home", canvas.fit)
        key("Shift+Home", canvas.fit_stage)
        window("Ctrl+1", lambda: self._set_view("design"))
        window("Ctrl+2", lambda: self._set_view("preview"))
        window(QKeySequence.StandardKey.Undo, canvas.undo)
        window(QKeySequence.StandardKey.Redo, canvas.redo)

    def _choose_tool(self, tool: str) -> None:
        if self.view_mode == "design":
            self.tool_buttons[tool].click()

    def _choose_op(self, op: str) -> None:
        if self.view_mode == "design":
            self.op_buttons[op].click()

    def _toggle_edit(self) -> None:
        if self.view_mode == "design":
            self.canvas.toggle_edit()

    def _enter_edit(self) -> None:
        if not self.canvas.enter_edit():
            self.object_btn.setChecked(True)

    def _edit_changed(self, editing: bool) -> None:
        (self.edit_btn if editing else self.object_btn).setChecked(True)
        for button in self.node_buttons:
            button.setEnabled(editing)

    def _invert_selected(self) -> None:
        selected = self.canvas.selected_shapes()
        if self.view_mode == "design" and selected:
            self.canvas.apply_op("add" if selected[0].op == "subtract" else "subtract")

    def _show_cursor(self, x: float, y: float) -> None:
        frame = "relative to start" if self.view_mode == "design" else "absolute"
        self.cursor_label.setText(f"x {x:.1f} µm   y {y:.1f} µm   ·   grid {self.canvas.grid_step:g} µm   ·   {frame}")

    def params(self) -> Params:
        """Read the scan parameters from the widgets."""
        return Params(
            pattern=next(k for k, b in self.pattern_buttons.items() if b.isChecked()),
            step=self.step.value(),
            angle=self.angle.value(),
            speed=self.speed.value(),
            margin=self.margin.value(),
            passes=self.passes.value(),
        )

    def _refresh_origin(self) -> None:
        """Read the stage position (the plan origin) and its acceleration profile."""
        if self.s.executor.running:
            return
        position = self.s.devices.position_um()
        self.origin = position or (0.0, 0.0)
        self.motion = self.s.devices.motion()
        _show(self.notice, "" if position else "No stage connected: the start position is assumed to be (0, 0).")

    def replan(self) -> None:
        """Rebuild the plan, estimate and range check; refresh the preview when it is shown."""
        s, params = self.s, self.params()
        shapes = [clean_shape(d) for d in self.canvas.shapes()]
        problems = []
        try:
            plan = build_plan(shapes, params)
        except ValueError as exc:
            plan = []
            problems.append(str(exc))
        flags, messages = overrun(plan, self.origin, self.profile["x_range_um"], self.profile["y_range_um"])
        if messages:
            problems.append("Path leaves the stage range from the current position: " + "; ".join(messages) + ".")
        s.plan, s.params, s.problems = plan, params, problems
        accel, ramp = self.motion or (None, 0.0)
        on, _off, seconds = estimate(plan, params.speed, accel, ramp)
        basis = "with acceleration" if self.motion else "constant speed, acceleration unknown"
        _show(self.estimate, f"{len(plan)} segments · {on / 1000:.2f} mm scanned · "
                             f"{_duration(seconds)} ({basis})" if plan else "")
        _show(self.alerts, "\n".join(problems))
        if self.view_mode != "design":
            self.canvas.set_preview(shift(plan, self.origin), region_polygons(shapes, self.origin), self.origin, flags)

    def _set_view(self, mode: str) -> None:
        if self.s.executor.running or mode == self.view_mode:
            return
        self.view_buttons[mode].setChecked(True)
        if mode == "preview":
            self._refresh_origin()
        self.view_mode = mode
        self.replan()
        self.canvas.set_mode(mode)
        self.fit_stage_btn.setVisible(mode != "design")
        for widget in self.design_widgets:
            widget.setEnabled(mode == "design")

    def _apply_profile(self, profile: dict) -> None:
        """Use a stage profile (read from the controller, or the default when simulating)."""
        self.profile = profile
        (x0, x1), (y0, y1) = profile["x_range_um"], profile["y_range_um"]
        self.canvas.set_stage(QRectF(x0, y0, x1 - x0, y1 - y0))
        self.replan()

    def _refresh_ports(self) -> None:
        ports = serial_ports() if not self.simulate else []
        for combo, none, default in ((self.stage_port, "", DEFAULT_PORTS[0]), (self.shutter_port, "None", DEFAULT_PORTS[1])):
            combo.clear()
            if self.simulate:
                combo.addItem("Simulated")
            else:
                combo.addItems(([none] if none else []) + ports)
                if default not in ports:
                    combo.addItem(default)
                combo.setCurrentText(default)
            combo.setEnabled(not self.simulate)

    def _after_connect(self) -> None:
        dev = self.s.devices
        self._apply_profile(dev.profile if dev.connected else settings.load())
        self._refresh_origin()
        self.replan()

    def _connect(self) -> None:
        s = self.s
        if s.executor.running:
            return _show(self.device_msg, "Abort the run first.")
        _show(self.device_msg, "")
        if s.devices.connected:
            s.devices.close()
            return self._after_connect()
        try:
            shutter = self.shutter_port.currentText()
            s.devices.connect(
                self.simulate,
                self.stage_port.currentText() or None,
                None if shutter in ("", "None") else shutter,
                self.profile["units_per_um"],
                self._stage_center(),
            )
        except Exception as exc:
            return _show(self.device_msg, f"Connection failed: {exc}", True)
        _show(self.device_msg, s.devices.note, True)
        self._after_connect()

    def _lock(self, locked: bool) -> None:
        for widget in (self.scan_card, self.toolbar):
            widget.setEnabled(not locked)
        self.badge.setVisible(locked)

    def _start(self) -> None:
        s = self.s
        _show(self.notice, "", False)
        if not s.devices.connected:
            return _show(self.notice, "Connect the devices first.", True)
        if self.view_mode == "design":  # the preview already fixed the origin the path was shown at
            self._refresh_origin()
        self.replan()
        if s.problems or not s.plan:
            return _show(self.notice, "Nothing to scan, or the plan leaves the stage range.", True)
        self._run_plan = shift(s.plan, self.origin)
        self.view_mode = "monitor"
        self.replan()
        self.canvas.set_mode("monitor")
        self._lock(True)
        try:
            s.executor.start(self._run_plan, s.params.speed)
        except RuntimeError as exc:
            self._finish_run()
            _show(self.notice, str(exc), True)

    def _finish_run(self) -> None:
        self._lock(False)
        self.view_mode = "preview"
        self.view_buttons["preview"].setChecked(True)
        self.canvas.set_mode("preview")
        self.fit_stage_btn.setVisible(True)
        for widget in self.design_widgets:
            widget.setEnabled(False)

    def _poll(self) -> None:
        ex, dev = self.s.executor, self.s.devices
        running = ex.running
        self.status.setText(
            f"{ex.state.value.capitalize()} · {ex.done}/{ex.total} points" if running else ex.message or "Idle"
        )
        self.progress.setMaximum(max(ex.total, 1))
        self.progress.setValue(ex.done)
        self.start_btn.setEnabled(not running and dev.connected and not self.s.problems and bool(self.s.plan))
        self.pause_btn.setEnabled(running)
        self.pause_btn.setText("Resume" if ex.state is State.PAUSED else "Pause")
        self.abort_btn.setEnabled(running)
        self.connect_btn.setText("Disconnect" if dev.connected else "Connect")
        kind = "Simulated" if dev.simulated else "Hardware"
        self.device_status.setText(f"{kind} devices connected" if dev.connected else "Not connected")
        self._update_led(dev.shutter is not None and ex.shutter_open)
        self._update_monitor()
        if running and self.view_mode == "monitor":
            if ex.done:
                self.canvas.set_progress(self._run_plan, ex.seg, ex.pt)
            self.canvas.set_marker(ex.live_position())
        elif self._was_running:
            self._finish_run()
            self.canvas.set_marker(dev.position)
        elif self.view_mode == "preview":
            self.canvas.set_marker(dev.position)
        self._was_running = running

    def _update_led(self, on: bool) -> None:
        if on != self._shutter_led:
            self._shutter_led = on
            self.led.setProperty("on", on)
            self.led.style().unpolish(self.led)
            self.led.style().polish(self.led)

    def _update_monitor(self) -> None:
        """Append the serial traffic logged since the last call."""
        records, self._traffic_seen = self.s.devices.new_traffic(self._traffic_seen)
        hide = self.hide_polling.isChecked()
        lines = [
            f"{time.strftime('%H:%M:%S', time.localtime(t))}.{int(t % 1 * 1000):03d} {direction} {text}"
            for t, direction, text, poll in records
            if not (poll and hide)
        ]
        if lines:
            self.monitor.appendPlainText("\n".join(lines))

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "LaserScan project (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                shapes, params, file_profile = project.loads(f.read())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return _show(self.notice, f"Cannot open project: {exc}", True)
        self._set_view("design")
        for key, value in asdict(params).items():
            widget = self.pattern_buttons.get(value) if key == "pattern" else getattr(self, key)
            widget.blockSignals(True)
            widget.setChecked(True) if key == "pattern" else widget.setValue(value)
            widget.blockSignals(False)
        self.canvas.set_shapes(shapes)
        self.canvas.fit()
        differs = file_profile and (
            file_profile.get("x_range_um") != self.profile["x_range_um"]
            or file_profile.get("y_range_um") != self.profile["y_range_um"]
        )
        _show(self.notice, "The project was drawn for a different stage range than the connected stage." if differs else "", True)
        self.replan()

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "scan.laserscan.json", "LaserScan project (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(project.dumps(self.canvas.shapes(), self.params(), self.profile))

    def closeEvent(self, event) -> None:
        if self.s.executor.running and QMessageBox.question(
            self,
            "Scan running",
            "A scan is running. Closing will abort it and close the shutter. Close anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return event.ignore()
        self.s.shutdown("window closed")
        event.accept()

"""
screens.py - the standard screens

Bootstrap -> Setup (first run) -> Games -> Install -> Manage <-> Settings / Update

Project hooks in games.py (only build_steps is required):
    build_steps(selected, choices) -> [pipeline.Step]     full install of the ticked games
    update_steps(games)            -> [pipeline.Step]     "Update Mods" (files only, Steam may stay open)
    check_updates(games)           -> {key: text}          shown on Manage; any non-empty -> Update Mods
    preflight(selected, choices)   -> [(path, gb)]         disk space to check before installing
    repair(games, say)                                     Settings > Repair (re-add shortcuts, templates)
    GAMES[key]["choices"] = {"id": {"label": "...", "options": {"opt": "Label", ...}}}
"""

import os
import subprocess

import identity
from .. import config, controller, detect, pipeline, preflight, selfupdate, steam
from ..detect_hw import DEVICES, OS_LABELS, detect_device, detect_os
from ..log import LOG_PATH, get_logger, tail_for_report
from ..qt import *
from .theme import T
from .widgets import (LogView, button, card, copy_text, download_failed_dialog, get_bridge, header, label,
                      message, preflight_dialog, run_in_thread)

_log = get_logger("ui")


def _games():
    import games
    return games


class Screen(QWidget):
    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.root = QVBoxLayout(self); self.root.setContentsMargins(28, 22, 28, 22); self.root.setSpacing(12)

    def go(self, name):
        from .app import go_to
        go_to(self.stack, name)

    def screen(self, name):
        return self.stack.screens[name]


# --- bootstrap

class BootstrapScreen(Screen):
    def __init__(self, stack):
        super().__init__(stack)
        self.root.addStretch(); t = label(identity.APP_TITLE, "title"); t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(t); self.msg = label("Starting...", "subtitle"); self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(self.msg); self.root.addStretch()

    def on_show(self):
        QTimer.singleShot(100, lambda: self.go("SetupScreen" if config.is_first_run() else "ManageScreen"))


# --- first-run setup

class SetupScreen(Screen):
    """Autodetect confirm, or OS + device pickers; then gyro, name, play mode."""

    def __init__(self, stack):
        super().__init__(stack)
        self.root.addWidget(header(f"Welcome to {identity.APP_TITLE}", "A few questions so games are set up for your device."))
        self.body = QVBoxLayout(); self.root.addLayout(self.body, 1)
        self.state = {}

    def _clear(self):
        while self.body.count():
            w = self.body.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _ask(self, title, options, pick, note=""):
        self._clear()
        f, lay = card(); lay.addWidget(label(f"<b>{title}</b>"))
        if note:
            lay.addWidget(label(note, "subtitle"))
        grid = QGridLayout(); grid.setSpacing(10)
        for i, (val, text) in enumerate(options):
            grid.addWidget(button(text, lambda v=val: pick(v)), i // 3, i % 3)
        lay.addLayout(grid); self.body.addWidget(f); self.body.addStretch()

    def on_show(self):
        os_key, dev = detect_os(), detect_device()
        if os_key:
            dev = dev or "general_pc"
            self._clear()
            f, lay = card()
            lay.addWidget(label(f"<b>Detected {DEVICES[dev]['label']} on {OS_LABELS.get(os_key, os_key)}.</b> Is this correct?"))
            row = QHBoxLayout()
            row.addWidget(button("Yes", lambda: self._device(dev, os_key), "primary")); row.addWidget(button("Change", self._pick_os))
            lay.addLayout(row); self.body.addWidget(f); self.body.addStretch()
        else:
            self._pick_os()

    def _pick_os(self):
        self._ask("Which system is this?", [(k, v) for k, v in OS_LABELS.items()], lambda o: self._pick_device(o))

    def _pick_device(self, os_key):
        self._ask("Which device?", [(k, d["label"]) for k, d in DEVICES.items()], lambda d: self._device(d, os_key))

    def _device(self, dev, os_key):
        self.state.update(device=dev, os_type=os_key)
        if DEVICES[dev]["gyro"]:
            self._ask("Use gyro aiming?", [("on", "Yes, while aiming"), ("hold", "Hold a button"),
                                           ("toggle", "Toggle with a button"), ("off", "No")], self._gyro,
                      "You can change this later in Settings.")
        else:
            self._gyro("off")

    def _gyro(self, mode):
        self.state["gyro_mode"] = mode
        self._clear()
        f, lay = card(); lay.addWidget(label("<b>Player name</b> (used in game configs)"))
        edit = QLineEdit(config.get("player_name") or config.steam_display_name() or "Player"); edit.setMaxLength(24)
        lay.addWidget(edit)
        lay.addWidget(button("Next", lambda: self._name(edit.text().strip() or "Player"), "primary"))
        self.body.addWidget(f); self.body.addStretch()

    def _name(self, name):
        self.state["player_name"] = name
        self._ask("How do you play?", [("handheld", "Handheld only"), ("docked", "Also docked / on a TV")], self._play)

    def _play(self, mode):
        self.state["play_mode"] = mode
        if mode == "docked":
            self._ask("Docked resolution", [(r, r) for r in ("1280x720", "1920x1080", "2560x1440", "3840x2160")] + [("own", "I set it in game")],
                      lambda r: (self.state.update(docked_resolution=r), self._ext()))
        else:
            self._finish()

    def _ext(self):
        self._ask("Which controller when docked?", [("playstation", "PlayStation"), ("xbox", "Xbox"),
                                                    ("steamcontroller", "Steam Controller"), ("other", "Other")],
                  lambda c: (self.state.update(external_controller=c), self._finish()))

    def _finish(self):
        config.update(**self.state, steam_root=steam.STEAM_ROOT)
        self.go("GamesScreen")


# --- game list

class GamesScreen(Screen):
    def __init__(self, stack):
        super().__init__(stack)
        self.root.addWidget(header("Choose games", "Games found on this device. Tick what to set up.", back=lambda: self.go("ManageScreen")))
        self.status = label("Scanning..."); self.root.addWidget(self.status)
        self.area = QScrollArea(); self.area.setWidgetResizable(True); self.root.addWidget(self.area, 1)
        row = QHBoxLayout()
        row.addWidget(button("Choose Folder", self._folder, tip="Add a folder that holds games installed outside Steam"))
        row.addStretch(); self.go_btn = button("Install", self._install, "primary"); row.addWidget(self.go_btn)
        self.root.addLayout(row)
        self.extra, self.found, self.checks, self.combos = [], {}, {}, {}

    def on_show(self):
        self.status.setText("Scanning for games...")
        run_in_thread(lambda: detect.find_all(config.get("steam_root"), self.extra), self._show)

    def _folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder with games", os.path.expanduser("~"))
        if d:
            self.extra.append(d); self.on_show()

    def _show(self, found):
        self.found = found
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(10)
        self.checks, self.combos = {}, {}
        g = _games().GAMES
        setup = config.setup_games()
        for key, meta in g.items():
            f, cl = card()
            hit = found.get(key)
            cb = QCheckBox(meta["name"]); cb.setEnabled(bool(hit)); cb.setChecked(bool(hit) and key not in setup)
            cl.addWidget(cb); self.checks[key] = cb
            cl.addWidget(label((f"{'Steam' if hit['source'] == 'steam' else 'Own copy'}: {hit['install_dir']}") if hit
                               else meta.get("missing_hint", "Not found. Install it, or use Choose Folder."), "subtitle"))
            for cid, ch in meta.get("choices", {}).items():
                row = QHBoxLayout(); row.addWidget(label(ch["label"], wrap=False))
                combo = QComboBox()
                for oid, text in ch["options"].items():
                    combo.addItem(text, oid)
                saved = config.get("choices", {}).get(key, {}).get(cid)
                if saved is not None and combo.findData(saved) >= 0:
                    combo.setCurrentIndex(combo.findData(saved))
                combo.setEnabled(bool(hit)); row.addWidget(combo, 1); cl.addLayout(row)
                self.combos[(key, cid)] = combo
            lay.addWidget(f)
        lay.addStretch(); self.area.setWidget(w)
        self.status.setText(f"{len(found)} game(s) found.")

    def _install(self):
        sel = {k: self.found[k] for k, cb in self.checks.items() if cb.isChecked()}
        if not sel:
            return
        choices = {}
        for (k, cid), combo in self.combos.items():
            if k in sel:
                choices.setdefault(k, {})[cid] = combo.currentData()
        c = config.load(); c.setdefault("choices", {}).update(choices); config.save(c)
        space = getattr(_games(), "preflight", lambda s, c: [])(sel, choices)
        self.go_btn.setEnabled(False); self.status.setText("Checking disk space and connection...")

        def checked(checks):
            self.go_btn.setEnabled(True)
            if preflight_dialog(self, checks):
                self.screen("InstallScreen").start(sel, choices)
                self.go("InstallScreen")
        run_in_thread(lambda: preflight.check(space), checked)


# --- install / update runner

class InstallScreen(Screen):
    def __init__(self, stack):
        super().__init__(stack)
        self.title = header("Installing", "Keep the device plugged in. Steam will be closed for part of this.")
        self.root.addWidget(self.title)
        self.step = label(""); self.root.addWidget(self.step)
        self.bar = QProgressBar(); self.root.addWidget(self.bar)
        self.sub = QProgressBar(); self.sub.setMaximumHeight(12); self.sub.setTextVisible(False); self.root.addWidget(self.sub)
        self.log = LogView(); self.root.addWidget(self.log, 1)
        row = QHBoxLayout(); row.addWidget(button("Copy Log", lambda: copy_text(tail_for_report())))
        row.addStretch(); self.done_btn = button("Continue", lambda: self.go("ManageScreen"), "primary"); self.done_btn.setEnabled(False)
        row.addWidget(self.done_btn); self.root.addLayout(row)

    def start(self, selected: dict, choices: dict = None, steps: list = None, title: str = None):
        b = get_bridge()
        self.log.clear(); self.bar.setValue(0); self.done_btn.setEnabled(False)
        steps = steps if steps is not None else _games().build_steps(selected, choices or {})
        ctx = pipeline.Context(games=selected, steam_root=config.get("steam_root") or steam.STEAM_ROOT,
                               progress=lambda p, m="": b.post(lambda: (self.sub.setValue(int(p)), m and self.step.setText(m))),
                               log=lambda line: b.post(lambda: self.log.add(line)))
        overall = lambda p, name: b.post(lambda: (self.bar.setValue(p), self.step.setText(name)))
        ask_dl = lambda err: b.ask(lambda: download_failed_dialog(self, err))
        ask_err = lambda s, ex: b.ask(lambda: pipeline.ABORT if message(
            self, f"{s.name} failed", f"{ex}\n\nSkip it and continue?", ["Skip", "Stop"]) == "Stop" else pipeline.SKIP)

        def work():
            res = pipeline.run(steps, ctx, ask_dl, ask_err, overall)
            for key in pipeline.games_ok(steps, res):
                g = selected.get(key, {})
                config.mark_game_setup(key, g.get("client", "modded"), g.get("source", "steam"))
            return res

        def done(res):
            bad = [k for k, v in res.items() if v != "ok"]
            self.log.add("Done." if not bad else f"Done with problems: {', '.join(bad)}")
            self.bar.setValue(100); self.done_btn.setEnabled(True)
            if config.is_first_run():
                config.complete_first_run(ctx.steam_root)

        def failed(ex):
            self.log.add(f"Stopped: {ex}"); self.done_btn.setEnabled(True)

        run_in_thread(work, done, failed)


# --- management

class ManageScreen(Screen):
    def __init__(self, stack):
        super().__init__(stack)
        top = QHBoxLayout(); top.addWidget(label(identity.APP_TITLE, "title"), 0)
        badge = getattr(identity, "BUILD_BADGE", "")
        if badge:
            b = label(badge, "badge", wrap=False); top.addWidget(b, 0)
        top.addStretch()
        self.upd_mods = button("Update Mods", self._update_mods); self.upd_mods.setVisible(False); top.addWidget(self.upd_mods)
        top.addWidget(button("Update App", lambda: self.go("UpdateScreen")))
        top.addWidget(button("Add Games", lambda: self.go("GamesScreen")))
        top.addWidget(button("Settings", lambda: self.go("SettingsScreen")))
        self.root.addLayout(top)
        self.status = label("", "subtitle"); self.root.addWidget(self.status)
        self.area = QScrollArea(); self.area.setWidgetResizable(True); self.root.addWidget(self.area, 1)
        self.found = {}
        self._checked = False

    def on_show(self):
        run_in_thread(lambda: detect.find_all(config.get("steam_root")), self._show)

    def _show(self, found):
        self.found = found
        setup = config.setup_games()
        w = QWidget(); grid = QGridLayout(w); grid.setSpacing(12)
        for i, (key, meta) in enumerate(_games().GAMES.items()):
            f, lay = card(); lay.addWidget(label(f"<b>{meta['name']}</b>"))
            state = "Set up" if key in setup else ("Found, not set up" if key in found else "Not installed")
            lay.addWidget(label(state, "subtitle"))
            if key in found:
                lay.addWidget(button("Reinstall" if key in setup else "Set Up",
                                     lambda k=key: (self.screen("InstallScreen").start({k: found[k]}, config.get("choices", {})),
                                                    self.go("InstallScreen"))))
            lay.addStretch(); grid.addWidget(f, i // 3, i % 3)
        self.area.setWidget(w)
        g = _games()
        if hasattr(g, "check_updates") and not self._checked:
            self._checked = True  # once per session: network calls
            run_in_thread(lambda: g.check_updates({k: found[k] for k in setup if k in found}), self._updates)

    def _updates(self, ups):
        ups = {k: v for k, v in (ups or {}).items() if v}
        self.upd_mods.setVisible(bool(ups))
        self.status.setText(" · ".join(f"{_games().GAMES[k]['name']}: {v}" for k, v in ups.items() if k in _games().GAMES))

    def _update_mods(self):
        setup = config.setup_games()
        sel = {k: self.found[k] for k in setup if k in self.found}
        steps = _games().update_steps(sel)
        self.screen("InstallScreen").start(sel, steps=steps)
        self.go("InstallScreen")


class SettingsScreen(Screen):
    def __init__(self, stack):
        super().__init__(stack)
        self.root.addWidget(header("Settings", back=lambda: self.go("ManageScreen")))
        cols = QHBoxLayout(); left, ll = card(); right, rl = card(); cols.addWidget(left); cols.addWidget(right)
        self.root.addLayout(cols, 1)
        ll.addWidget(label("<b>Player name</b>"))
        self.name = QLineEdit(); ll.addWidget(self.name)
        ll.addWidget(button("Save Name", lambda: config.put("player_name", self.name.text().strip() or "Player")))
        ll.addWidget(label("<b>Gyro</b>"))
        self.gyro = QComboBox()
        for k, v in (("on", "While aiming"), ("hold", "Hold"), ("toggle", "Toggle"), ("off", "Off")):
            self.gyro.addItem(v, k)
        self.gyro.currentIndexChanged.connect(lambda *_: config.put("gyro_mode", self.gyro.currentData()))
        ll.addWidget(self.gyro)
        self.music = QCheckBox("Background music"); ll.addWidget(self.music)
        self.music.toggled.connect(self._music)
        ll.addWidget(button("Re-apply Controller Templates", self._templates, tip="Closes Steam"))
        ll.addWidget(button("Repair", self._repair, tip="Re-add missing shortcuts and settings (closes Steam)"))
        ll.addStretch()
        rl.addWidget(button("View Log", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_PATH))))
        rl.addWidget(button("Copy Log", lambda: copy_text(tail_for_report())))
        rl.addWidget(button("Reset Config", self._reset))
        rl.addWidget(button("Uninstall", self._uninstall, "danger"))
        rl.addStretch()
        self.out = label("", "subtitle"); self.root.addWidget(self.out)

    def on_show(self):
        self.name.setText(config.get("player_name") or "")
        i = self.gyro.findData(config.get("gyro_mode") or "off")
        self.gyro.blockSignals(True); self.gyro.setCurrentIndex(max(i, 0)); self.gyro.blockSignals(False)
        self.music.blockSignals(True); self.music.setChecked(bool(config.get("music_enabled", True))); self.music.blockSignals(False)

    def _music(self, on):
        from .app import music
        config.put("music_enabled", on); music(on)

    def _closing_steam(self, fn, what):
        if steam.is_running() and message(self, what, "Steam will be closed for this.", ["Continue", "Cancel"]) != "Continue":
            return
        self.out.setText(f"{what}...")

        def work():
            steam.kill_steam()
            return fn()
        run_in_thread(work, lambda r: self.out.setText(f"{what}: done"), lambda ex: self.out.setText(f"{what} failed: {ex}"))

    def _templates(self):
        g = _games()

        def work():
            targets = getattr(g, "controller_targets", lambda found: [])(detect.find_all(config.get("steam_root")))
            controller.install_templates()
            ext = config.get("external_controller") if config.get("play_mode") == "docked" else None
            controller.assign(targets, external=ext)
        self._closing_steam(work, "Controller templates")

    def _repair(self):
        g = _games()
        if hasattr(g, "repair"):
            self._closing_steam(lambda: g.repair(detect.find_all(config.get("steam_root")), _log.info), "Repair")

    def _reset(self):
        if message(self, "Reset config?", "Your choices are cleared and setup runs again. Installed files stay.", ["Reset", "Cancel"]) == "Reset":
            config.reset(); self.go("BootstrapScreen")

    def _uninstall(self):
        if message(self, "Uninstall?", f"Removes {identity.APP_TITLE}, its mods, shortcuts and Steam changes.", ["Uninstall", "Cancel"]) != "Uninstall":
            return
        sh = os.path.join(identity.PROJECT_ROOT, "uninstall.sh")
        # Detached: the script deletes this app's folder while running
        subprocess.Popen(["bash", sh], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        QApplication.quit()


class UpdateScreen(Screen):
    def __init__(self, stack):
        super().__init__(stack)
        self.root.addWidget(header("Update", back=lambda: self.go("ManageScreen")))
        self.msg = label("Checking..."); self.root.addWidget(self.msg)
        self.bar = QProgressBar(); self.root.addWidget(self.bar)
        self.log = LogView(); self.root.addWidget(self.log, 1)
        row = QHBoxLayout(); row.addStretch()
        self.btn = button("Update Now", self._apply, "primary"); self.btn.setEnabled(False); row.addWidget(self.btn)
        self.root.addLayout(row)
        self.pending = None

    def on_show(self):
        self.btn.setEnabled(False); self.msg.setText("Checking for updates...")
        run_in_thread(selfupdate.check, self._checked, lambda ex: self.msg.setText(f"Could not check: {ex}"))

    def _checked(self, res):
        loc, remote, files = res
        if files == []:
            self.msg.setText("You have the latest version."); return
        self.pending = (remote, files)
        self.msg.setText(f"Update available ({'all files' if files is None else f'{len(files)} file(s)'}).")
        self.btn.setEnabled(True)

    def _apply(self):
        b = get_bridge(); self.btn.setEnabled(False)
        remote, files = self.pending
        prog = lambda p, m: b.post(lambda: (self.bar.setValue(p), self.log.add(m)))

        def done(changed):
            hint = "\nReset Config is recommended after this update." if selfupdate.reset_recommended(changed) else ""
            message(self, "Update complete", f"{len(changed)} file(s) updated.{hint}\nThe app restarts now.", ["OK"])
            selfupdate.relaunch()
        run_in_thread(lambda: selfupdate.apply(remote, files, prog), done, lambda ex: self.msg.setText(f"Update failed: {ex}"))

"""
ui_install.py - Install pipeline screens for NFSBlacklist

Screens: OwnScanScreen, OwnInstallScreen
No Steam pipeline screens (WelcomeScreen, SetupScreen, InstallScreen)
since these games were never on Steam.
"""

import os, subprocess, threading

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QCheckBox, QProgressBar,
    QPlainTextEdit, QFileDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer

import config as cfg
from net import DownloadError

from ui_constants import (
    C_BG, C_CARD, C_ACCENT1, C_ACCENT2, C_DIM, C_DARK_BTN,
    font, _btn, _lbl, _title_block, _log_to_file, _Sigs,
    ALL_GAMES,
    go_to, get_screen,
)


# -- OwnScanScreen ------------------------------------------------------------
class OwnScanScreen(QWidget):
    """
    Scans for NFS game folders in default and user-chosen locations.
    Shows found games with checkboxes, then advances to OwnInstallScreen.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "OwnScanScreen"
        self._own_found = {}
        self._checks = {}
        self._extra_paths = []

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content); clay.setContentsMargins(60, 40, 60, 40); clay.setSpacing(14)

        _title_block(clay, main_size=36)
        clay.addSpacing(8)
        clay.addWidget(_lbl(
            "NFSBlacklist will scan for your NFS game files. "
            "Make sure your games are in ~/Games, ~/NFS, or on an SD card.",
            13, C_DIM))

        self.status = _lbl("Scanning...", 14, C_DIM)
        clay.addWidget(self.status)
        self.bar = QProgressBar(); self.bar.setMaximum(100); self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)
        bw = QHBoxLayout(); bw.addStretch(); bw.addWidget(self.bar, 6); bw.addStretch()
        clay.addLayout(bw)

        # Scrollable list of found games
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        clay.addWidget(scroll, stretch=1)

        self._no_games_msg = _lbl(
            "No supported games found in the default locations.\n"
            "Use \"Choose Folder\" to pick where your games are installed.",
            13, C_ACCENT2, align=Qt.AlignCenter)
        self._no_games_msg.setVisible(False)
        clay.addWidget(self._no_games_msg)

        # Button row
        self.warning = _lbl("", 12, C_ACCENT2, align=Qt.AlignLeft)
        self.warning.setVisible(False); clay.addWidget(self.warning)
        btn_row = QHBoxLayout(); btn_row.setSpacing(16)

        back = _btn("<< Back", C_DARK_BTN, h=52); back.setFixedWidth(180)
        back.clicked.connect(lambda: go_to(self.stack, "SetupFlowScreen"))

        self._folder_btn = _btn("Choose Folder", C_DARK_BTN, h=52)
        self._folder_btn.setFixedWidth(200)
        self._folder_btn.clicked.connect(self._pick_folder)

        self._cont_btn = _btn("Continue >>", C_ACCENT1, h=52)
        self._cont_btn.setVisible(False)
        self._cont_btn.clicked.connect(self._continue)

        btn_row.addWidget(back)
        btn_row.addWidget(self._folder_btn)
        btn_row.addWidget(self._cont_btn, stretch=1)
        clay.addLayout(btn_row)
        lay.addWidget(content, stretch=1)

    def showEvent(self, e):
        super().showEvent(e)
        self._own_found.clear()
        self._checks.clear()
        self._extra_paths.clear()
        self._no_games_msg.setVisible(False)
        self._cont_btn.setVisible(False)
        self.bar.setValue(0)
        self.status.setText("Scanning for NFS games...")
        # Clear previous game rows
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        QTimer.singleShot(200, self._scan)

    def _scan(self):
        self.bar.setValue(30)
        self.status.setText("Scanning game folders...")
        self._s = _Sigs()
        self._s.progress.connect(lambda p, m: (self.bar.setValue(p), self.status.setText(m)))
        self._s.done.connect(lambda _: self._show_results())
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        from detect_games import find_own_installed
        results = find_own_installed(
            extra_paths=self._extra_paths if self._extra_paths else None,
            on_progress=lambda msg: self._s.progress.emit(60, msg),
        )
        self._own_found = results
        self._s.progress.emit(100, "Scan complete.")
        self._s.done.emit(True)

    def _show_results(self):
        self.bar.setValue(100)
        self._checks.clear()

        # Clear previous game rows (keep the trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._own_found:
            self.status.setText("No supported games found.")
            self.status.setStyleSheet(f"color:{C_ACCENT2};background:transparent;")
            self._no_games_msg.setVisible(True)
            self._cont_btn.setVisible(False)
            return

        self._no_games_msg.setVisible(False)
        count = len(self._own_found)
        self.status.setText(f"Found {count} game(s)!")
        self.status.setStyleSheet(f"color:{C_ACCENT1};background:transparent;")

        # Build game rows sorted by order
        for key in sorted(self._own_found, key=lambda k: self._own_found[k].get("order", 99)):
            game = self._own_found[key]
            row = QHBoxLayout(); row.setSpacing(12); row.setContentsMargins(8, 8, 8, 8)

            cb = QCheckBox()
            cb.setChecked(True)
            cb.toggled.connect(self._update_continue)
            self._checks[key] = cb
            row.addWidget(cb)

            name_lbl = _lbl(game["name"], 14, "#FFF", align=Qt.AlignLeft, wrap=False)
            row.addWidget(name_lbl, stretch=1)

            year_lbl = _lbl(str(game.get("year", "")), 12, C_DIM, align=Qt.AlignRight, wrap=False)
            row.addWidget(year_lbl)

            path_lbl = _lbl(game["install_dir"], 10, C_DIM, align=Qt.AlignRight, wrap=False)
            row.addWidget(path_lbl)

            cw = QWidget(); cw.setLayout(row)
            self._list_layout.insertWidget(self._list_layout.count() - 1, cw)

        self._cont_btn.setVisible(True)

    def _update_continue(self):
        """Show Continue only if at least one game is checked."""
        any_checked = any(cb.isChecked() for cb in self._checks.values())
        self._cont_btn.setVisible(any_checked)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select your games folder", os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if folder:
            if folder not in self._extra_paths:
                self._extra_paths.append(folder)
            # Re-scan with the new path included
            self.status.setText(f"Scanning {folder}...")
            self.bar.setValue(0)
            self._no_games_msg.setVisible(False)
            self._cont_btn.setVisible(False)
            QTimer.singleShot(200, self._scan)

    def _continue(self):
        """Store selected games and advance to OwnInstallScreen."""
        selected = {}
        for key, cb in self._checks.items():
            if cb.isChecked() and key in self._own_found:
                selected[key] = self._own_found[key]

        install_screen = get_screen(self.stack, "OwnInstallScreen")
        install_screen.selected = selected
        install_screen.steam_root = cfg.load().get("steam_root") or os.path.expanduser("~/.local/share/Steam")
        go_to(self.stack, "OwnInstallScreen")


# -- OwnInstallScreen ---------------------------------------------------------
class OwnInstallScreen(QWidget):
    """
    Runs the install pipeline for selected NFS games:
      1. Close Steam
      2. Enrich games (compute appids, compatdata paths, launch options)
      3. Download + install GE-Proton
      4. Create Proton prefixes for each game
      5. Per-game mod installs (in order):
         a. Widescreen Fix (all 4) - provides dinput8.dll ASI loader
         b. Extra Options (all 4) - bug fixes, QoL
         c. XtendedInput (all 4) - native controller support
         d. XenonEffects (NFSMW only) - Xbox 360 visual effects
      6. Create non-Steam shortcuts + artwork
      7. Controller templates + profiles (placeholder - not built yet)
      8. Mark games as setup

    Download failures trigger a manual download dialog so the user can
    grab the file from a browser and place it themselves.
    """
    def __init__(self, stack):
        super().__init__(); self.stack = stack; self.screen_name = "OwnInstallScreen"
        self.selected = {}      # game key -> game info dict
        self.steam_root = ""
        self._return_to_management = False

        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        content = QWidget()
        clay = QVBoxLayout(content); clay.setContentsMargins(60, 40, 60, 40); clay.setSpacing(14)

        _title_block(clay, main_size=36)
        clay.addSpacing(8)

        self.cur = _lbl("Preparing install...", 14, C_DIM)
        clay.addWidget(self.cur)

        self.bar = QProgressBar(); self.bar.setMaximum(100); self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)
        bw = QHBoxLayout(); bw.addStretch(); bw.addWidget(self.bar, 6); bw.addStretch()
        clay.addLayout(bw)

        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(font(11))
        self.log.setStyleSheet(
            "QPlainTextEdit{color:#666677;background:transparent;border:none;padding:10px;}")
        clay.addWidget(self.log, stretch=1)

        self.cont_btn = _btn("Continue  >>", C_ACCENT1, size=13, h=52)
        self.cont_btn.setFixedWidth(320); self.cont_btn.setVisible(False)
        self.cont_btn.clicked.connect(lambda: go_to(self.stack, "SetupCompleteScreen"))
        cw = QHBoxLayout(); cw.addStretch(); cw.addWidget(self.cont_btn); cw.addStretch()
        clay.addLayout(cw)
        lay.addWidget(content, stretch=1)

        self._s = _Sigs()
        self._s.progress.connect(lambda p, m: (self.bar.setValue(p), self.cur.setText(m)))
        self._s.log.connect(self._append_log)
        self._s.done.connect(self._on_done)
        self._s.pulse_start.connect(self._start_pulse)
        self._s.pulse_stop.connect(self._stop_pulse)
        self._s.manual_dl.connect(self._show_manual_dl_dialog)

        self._pulse_timer = QTimer()
        self._pulse_timer.timeout.connect(self._do_pulse)
        self._pulse_msg   = ""
        self._pulse_count = 0

    def _start_pulse(self, base_msg):
        self._pulse_msg   = base_msg
        self._pulse_count = 0
        self._pulse_timer.start(500)

    def _do_pulse(self):
        dots = "." * (self._pulse_count % 4)
        self.cur.setText(f"{self._pulse_msg}{dots}")
        self._pulse_count += 1

    def _stop_pulse(self):
        self._pulse_timer.stop()

    def _append_log(self, text):
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        _log_to_file(text)

    def showEvent(self, e):
        super().showEvent(e)
        self.bar.setValue(0); self.log.clear()
        self._stop_pulse()
        # Route the continue button based on context
        try:
            self.cont_btn.clicked.disconnect()
        except Exception:
            pass
        if self._return_to_management:
            self.cont_btn.setText("Back to My Games  >>")
            self.cont_btn.clicked.connect(self._go_management)
            self._return_to_management = False
        else:
            self.cont_btn.setText("Continue  >>")
            self.cont_btn.clicked.connect(lambda: go_to(self.stack, "SetupCompleteScreen"))
        self.cont_btn.setVisible(False)
        _log_to_file("-- Install started --")
        QTimer.singleShot(400, lambda: threading.Thread(target=self._run, daemon=True).start())

    def _on_done(self, _):
        self._stop_pulse()
        self.cur.setText("Installation complete!")
        self.cont_btn.setVisible(True)

    def _go_management(self):
        # Restart Steam so shortcuts and compat tool changes take effect
        os.system("gtk-launch steam.desktop &")
        go_to(self.stack, "ManagementScreen")

    def _show_manual_dl_dialog(self, url, dest_folder, filename, label):
        """
        Show a dialog telling the user to manually download a file.
        Runs on the main thread (called via signal from worker).
        """
        os.makedirs(dest_folder, exist_ok=True)
        dest_path = os.path.join(dest_folder, filename)

        msg = QMessageBox(self)
        msg.setWindowTitle(f"{label} - Download Failed")
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            f"<b>{label}</b> could not be downloaded automatically.<br><br>"
            f'Download it manually here:<br>'
            f'<a href="{url}">{url}</a><br><br>'
            f'Then place <b>{filename}</b> in:<br>'
            f'<code>{dest_folder}</code><br><br>'
            f'Click <b>Open Folder</b> to open the destination, then '
            f'<b>I\'ve Placed It</b> when the file is in place.'
        )
        open_btn = msg.addButton("Open Folder", QMessageBox.ActionRole)
        done_btn = msg.addButton("I've Placed It", QMessageBox.AcceptRole)
        skip_btn = msg.addButton("Skip", QMessageBox.RejectRole)

        while True:
            msg.exec_()
            clicked = msg.clickedButton()
            if clicked == open_btn:
                subprocess.Popen(["xdg-open", dest_folder])
                continue
            elif clicked == done_btn:
                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                    self._manual_dl_ok = True
                    self._manual_dl_event.set()
                    return
                QMessageBox.warning(
                    self, "File Not Found",
                    f"{filename} was not found in:\n{dest_folder}\n\n"
                    "Make sure the file is downloaded and placed in the correct folder.",
                )
                continue
            else:
                self._manual_dl_ok = False
                self._manual_dl_event.set()
                return

    # -- Manual download helper ------------------------------------------------
    # When a mod download fails, we emit the manual_dl signal to show a dialog
    # on the main thread. The worker thread blocks on _manual_dl_event until
    # the user either places the file or skips.

    def _offer_manual_download(self, err):
        """
        Called from the worker thread when a DownloadError is caught.
        Signals the main thread to show the dialog, then blocks until
        the user responds. Returns True if the user placed the file.
        """
        self._manual_dl_event = threading.Event()
        self._manual_dl_ok = False

        # The dest on the error points to a temp dir - we want the user
        # to place the file in the game's install dir instead. Extract
        # just the filename from the failed dest path.
        filename = os.path.basename(err.dest)

        # For the dest_folder, use the game's install dir. The caller
        # sets _manual_dl_game_dir before calling the mod installer.
        dest_folder = getattr(self, "_manual_dl_game_dir", os.path.dirname(err.dest))

        self._s.manual_dl.emit(err.url, dest_folder, filename, err.label)
        self._manual_dl_event.wait()
        return self._manual_dl_ok

    # -- Mod install wrapper ---------------------------------------------------
    # Wraps each mod install call with DownloadError handling. If the download
    # fails, we offer a manual download dialog. If the user skips, we log it
    # and continue with the next mod.

    def _install_mod(self, label, install_fn):
        """
        Call a mod installer function with DownloadError fallback.

        label      - human-readable name for logging (e.g. "NFSMW Widescreen Fix")
        install_fn - callable that performs the install, may raise DownloadError

        Returns True if install succeeded, False if it failed or was skipped.
        """
        try:
            result = install_fn()
            if result:
                self._s.log.emit(f"  ok  {label}")
            else:
                self._s.log.emit(f"  !!  {label} - install returned False")
            return result
        except DownloadError as e:
            self._s.log.emit(f"  !!  {label} - download failed: {e.cause}")
            self._s.log.emit(f"      Offering manual download...")

            if self._offer_manual_download(e):
                # User placed the file - retry the install
                self._s.log.emit(f"      Retrying {label}...")
                try:
                    result = install_fn()
                    if result:
                        self._s.log.emit(f"  ok  {label} (after manual download)")
                    else:
                        self._s.log.emit(f"  !!  {label} - still failed after manual download")
                    return result
                except Exception as e2:
                    self._s.log.emit(f"  !!  {label} - retry failed: {e2}")
                    return False
            else:
                self._s.log.emit(f"      {label} skipped by user")
                return False
        except Exception as e:
            self._s.log.emit(f"  !!  {label} - unexpected error: {e}")
            return False

    def _run(self):
        """
        Main install pipeline. Runs on a background thread.

        Mod install order per game (required):
          1. Widescreen Fix - provides dinput8.dll (ASI loader)
          2. Extra Options - .asi plugin, needs ASI loader
          3. XtendedInput - .asi plugin + TPK textures
          4. XenonEffects - NFSMW only, .asi plugin + TPK

        All mods download from GitHub at install time. If a download
        fails, the user gets a dialog to manually place the file.
        """
        import widescreen_fix
        import extra_options
        import xtended_input
        import xenon_effects
        import shortcut
        import ge_proton
        import wrapper

        selected_keys = list(self.selected.keys())
        if not selected_keys:
            self._s.log.emit("No games selected.")
            self._s.done.emit(True)
            return

        self._s.log.emit(f"Setting up {len(selected_keys)} game(s)...")
        for key in selected_keys:
            game = self.selected[key]
            self._s.log.emit(f"  {game['name']} at {game['install_dir']}")

        # -- Step 1: Close Steam -----------------------------------------------
        self._s.progress.emit(5, "Closing Steam...")
        self._s.log.emit("-- Closing Steam --")
        wrapper.kill_steam(
            on_progress=lambda msg: self._s.log.emit(f"  {msg}")
        )

        # -- Step 2: Enrich games ----------------------------------------------
        # Compute appids, compatdata paths, and launch options before prefix
        # creation so we know where each prefix goes.
        self._s.progress.emit(8, "Computing game shortcuts...")
        self._s.log.emit("-- Enriching game data --")
        self.selected = shortcut.enrich_own_games(
            self.selected, selected_keys,
            on_progress=lambda msg: self._s.log.emit(msg),
        )

        # -- Step 3: Download GE-Proton ----------------------------------------
        self._s.progress.emit(10, "Downloading GE-Proton...")
        self._s.log.emit("-- GE-Proton --")
        self._s.pulse_start.emit("Downloading GE-Proton")
        try:
            ge_version = ge_proton.install_ge_proton(
                on_progress=lambda pct, msg: (
                    self._s.progress.emit(10 + int(pct * 0.08), msg)
                ),
            )
            self._s.log.emit(f"  ok  GE-Proton {ge_version}")
            cfg.update({"ge_proton_version": ge_version})
        except Exception as e:
            self._s.log.emit(f"  !!  GE-Proton install failed: {e}")
            ge_version = None
        self._s.pulse_stop.emit()

        # -- Step 4: Create Proton prefixes ------------------------------------
        self._s.progress.emit(20, "Creating Proton prefixes...")
        self._s.log.emit("-- Proton prefixes --")
        self._s.pulse_start.emit("Creating Proton prefixes")

        # Build (label, compatdata_path) list from enriched game data
        prefix_list = []
        for key in selected_keys:
            game = self.selected[key]
            compat_path = game.get("compatdata_path")
            if compat_path:
                prefix_list.append((game["name"], compat_path))

        if prefix_list:
            proton_path = wrapper.get_proton_path(self.steam_root) if ge_version else None
            try:
                count = ge_proton.ensure_all_prefix_deps(
                    ge_version, prefix_list,
                    on_progress=lambda msg: self._s.log.emit(f"  {msg}"),
                    proton_path=proton_path,
                    steam_root=self.steam_root,
                )
                self._s.log.emit(f"  ok  {count} prefix(es) ready")
            except Exception as e:
                self._s.log.emit(f"  !!  Prefix creation error: {e}")
        else:
            self._s.log.emit("  No prefixes to create (missing compatdata paths)")

        self._s.pulse_stop.emit()

        # -- Step 5: Per-game mod installs -------------------------------------
        # Install order matters: WSF first (provides ASI loader), then ExOpts,
        # then XtendedInput, then XenonEffects (NFSMW only).
        total = len(selected_keys)
        for idx, key in enumerate(selected_keys):
            game = self.selected[key]
            install_dir = game["install_dir"]
            name = game["name"]

            # Store the game dir so _offer_manual_download knows where
            # to tell the user to place files
            self._manual_dl_game_dir = install_dir

            base_pct = 30 + int(idx / max(total, 1) * 40)
            self._s.progress.emit(base_pct, f"Installing mods for {name}...")

            # 5a. Widescreen Fix - foundation mod, provides dinput8.dll
            self._s.log.emit(f"-- Widescreen Fix: {name} --")
            self._s.pulse_start.emit(f"Downloading Widescreen Fix for {name}")
            self._install_mod(
                f"{name} Widescreen Fix",
                lambda k=key, d=install_dir: widescreen_fix.install(
                    k, d, on_progress=lambda msg: self._s.log.emit(f"  {msg}")
                ),
            )
            self._s.pulse_stop.emit()

            # 5b. Extra Options - bug fixes and QoL
            self._s.log.emit(f"-- Extra Options: {name} --")
            self._s.pulse_start.emit(f"Downloading Extra Options for {name}")
            self._install_mod(
                f"{name} Extra Options",
                lambda k=key, d=install_dir: extra_options.install(
                    k, d, on_progress=lambda msg: self._s.log.emit(f"  {msg}")
                ),
            )
            self._s.pulse_stop.emit()

            # 5c. XtendedInput - native controller support (all 4 games)
            self._s.log.emit(f"-- XtendedInput: {name} --")
            self._s.pulse_start.emit(f"Downloading XtendedInput for {name}")
            self._install_mod(
                f"{name} XtendedInput",
                lambda k=key, d=install_dir: xtended_input.install(
                    k, d, on_progress=lambda msg: self._s.log.emit(f"  {msg}")
                ),
            )
            self._s.pulse_stop.emit()

            # 5d. XenonEffects - NFSMW only, Xbox 360 visual effects
            if key == "nfsmw":
                self._s.log.emit(f"-- XenonEffects: {name} --")
                self._s.pulse_start.emit(f"Downloading XenonEffects for {name}")
                self._install_mod(
                    f"{name} XenonEffects",
                    lambda d=install_dir: xenon_effects.install(
                        d, on_progress=lambda msg: self._s.log.emit(f"  {msg}")
                    ),
                )
                self._s.pulse_stop.emit()

        # -- Step 6: Create non-Steam shortcuts --------------------------------
        self._s.progress.emit(75, "Creating non-Steam shortcuts...")
        self._s.log.emit("-- Non-Steam shortcuts --")
        self._s.pulse_start.emit("Creating shortcuts and downloading artwork")
        gyro_mode = cfg.load().get("gyro_mode") or "off"
        try:
            shortcut.write_own_shortcuts(
                self.selected, selected_keys, gyro_mode,
                on_progress=lambda msg: self._s.log.emit(f"  {msg}"),
            )
            self._s.log.emit("  ok  Shortcuts written")
        except Exception as e:
            self._s.log.emit(f"  !!  Shortcut creation error: {e}")
        self._s.pulse_stop.emit()

        # -- Step 7: Controller templates + profiles ---------------------------
        self._s.progress.emit(88, "Installing controller profiles...")
        self._s.log.emit("-- Controller profiles --")
        # TODO: from controller_profiles import install_templates, assign_profiles
        self._s.log.emit("  (placeholder - controller profiles not built yet)")

        # -- Step 8: Mark games as setup ---------------------------------------
        self._s.progress.emit(95, "Finishing up...")
        for key in selected_keys:
            cfg.mark_game_setup(key, source="own")
            self._s.log.emit(f"ok  {self.selected[key]['name']} marked as setup")

        # -- Done --------------------------------------------------------------
        cfg.complete_first_run(self.steam_root)
        self._s.progress.emit(100, "All done!")
        self._s.done.emit(True)

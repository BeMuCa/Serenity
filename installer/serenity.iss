; ============================================================
; Author:  Berk
; Created: 2026-08-06
; Purpose: Inno Setup script that wraps the PyInstaller onedir output into a single
;          Serenity-Setup.exe (per-user by default, no admin needed).
; Role:    The distribution step AFTER `pyinstaller serenity.spec` (see
;          notes/4_Packaging.md). Windows-only: it can be compiled ONLY on a box with
;          Inno Setup 6 (`iscc installer\serenity.iss`), never from this repo's WSL side.
;
; Sections:
; - [Setup]   identity, per-user install target, output name
; - [Tasks]   optional desktop icon + optional post-install model download
; - [Files]   the whole dist\Serenity onedir tree
; - [Icons]   Start-menu + optional desktop shortcut
; - [Run]     optional `Serenity.exe --fetch-models` and first launch
; ============================================================

; ---------------------------------------------------------------------------
; DELIBERATELY NOT DONE HERE (each has a reason):
; * No HKCU\...\Run autostart key. Serenity owns that key itself (Settings ->
;   "Start with Windows", serenity/ui/platform_win.py::set_autostart) and keeps it in
;   step with the setting on every launch; a key written by the installer would be
;   rewritten or fought over. Autostart is ON by default in the app.
; * No [UninstallDelete] of %APPDATA%\Serenity. That directory holds the user's
;   settings, the notes index, the diary and the downloaded models (>1 GB). Uninstalling
;   the program must not delete the user's data - removal stays a manual, explicit act.
; * No SetupIconFile / no exe icon: no .ico exists in the repo yet (img/ is .png/.gif/
;   .webp only), matching icon=None in serenity.spec. Add both together later.
; ---------------------------------------------------------------------------

#define AppName "Serenity"
#define AppVersion "0.1.0"
#define AppPublisher "Berk"
#define AppExeName "Serenity.exe"
; Built by: pyinstaller serenity.spec  ->  dist\Serenity\  (onedir, windowed)
#define SourceDir "..\dist\Serenity"

[Setup]
; A stable AppId is what lets a later version UPGRADE this install instead of
; installing a second copy - never change it once released.
AppId={{7B5E2C41-9D3A-4F62-A8C7-13E0B6D4F9A2}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
; Per-user install by default (no UAC prompt); the user can still elevate and install
; machine-wide from the dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; PySide6 ships 64-bit wheels only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
UninstallDisplayName={#AppName}
; Serenity is tray-resident: a running instance holds files open, so ask to close first.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Unchecked by default: ~1.2 GB, and the windowed exe shows no console while it runs
; (progress goes to %APPDATA%\Serenity\fetch-models.log). The app works without it -
; every AI/voice feature degrades to its deterministic path when a model is absent.
Name: "fetchmodels"; Description: "Download the on-device AI model and the German voice (~1.2 GB, needs internet)"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; serenity/__main__.py::main() short-circuits on --fetch-models BEFORE importing Qt, so
; this runs the downloader (serenity/core/model_fetch.py) and exits - no window, no tray.
Filename: "{app}\{#AppExeName}"; Parameters: "--fetch-models"; \
    StatusMsg: "Downloading the AI model and voice (this can take a few minutes)..."; \
    Tasks: fetchmodels
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

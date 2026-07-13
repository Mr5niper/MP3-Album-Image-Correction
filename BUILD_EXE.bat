@echo off
setlocal enabledelayedexpansion

:: ==========================================================================
:: Configuration
:: ==========================================================================
set "REQUIRED_PYTHON_VERSION=3.13.12"
set "PYTHON_DOWNLOAD_URL=https://www.python.org/downloads/release/python-31312/"
set "APP_NAME=MP3 Album Image Correction for Pioneer"
set "SCRIPT_NAME=MP3 Album Image Correction for Pioneer.py"

:: ffmpeg: if .\bin\ffmpeg.exe is missing, the build downloads the current
:: LGPL "latest" build from BtbN and extracts ffmpeg.exe into .\bin.
:: FFMPEG_TESTED_ZIP_SHA256 is the SHA-256 of the downloaded ZIP (as published on
:: the BtbN release page) for the build this project was tested with - it is
:: the archive's hash. FFMPEG_TESTED_EXE_SHA256 is the hash of the ffmpeg.exe
:: extracted from that archive (the actual bundled binary), for traceability.
:: The BtbN "latest" URL always serves the newest build, so a downloaded copy
:: may hash differently; that is allowed - the build just warns that it is a
:: newer, untested version and continues. Update the value below (and NOTICE)
:: when you validate a newer build.
set "FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip"
set "FFMPEG_TESTED_ZIP_SHA256=a61ef31877b5a8c554638d136f6f3f5451659fccbbf31dd9bd9b5d1e56a824a5"
set "FFMPEG_TESTED_EXE_SHA256=7b355a9c9ad772d06fe99b5fe2cd3fdd170002967de2f9dc5c7dc80e8cff870d"

:: ==========================================================================
:: Pre-flight Check: Verify Python Version
:: ==========================================================================
echo [INFO] Checking Python version...

:: Get the current Python version output (e.g., "Python 3.13.12")
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "CURRENT_PYTHON_VERSION=%%v"

echo [INFO] Current Python version: !CURRENT_PYTHON_VERSION!
echo [INFO] Required Python version: %REQUIRED_PYTHON_VERSION%

if "!CURRENT_PYTHON_VERSION!" neq "%REQUIRED_PYTHON_VERSION%" (
    echo.
    echo [ERROR] Incorrect Python version detected.
    echo.
    echo This build script requires Python %REQUIRED_PYTHON_VERSION%.
    echo You are currently using version !CURRENT_PYTHON_VERSION!.
    echo.
    echo Please install the correct version from:
    echo %PYTHON_DOWNLOAD_URL%
    echo.
    echo [NOTE] Ensure you add Python to your PATH during installation.
    goto :error
)

:: ==========================================================================
:: Pre-flight Check: Ensure a bundled ffmpeg is available
:: ==========================================================================
:: The app calls ffmpeg to re-embed the artwork. This build bundles it so the
:: finished .exe is self-contained.
::
:: Behavior:
::   - If .\bin\ffmpeg.exe already exists, use it as-is (your tested copy).
::   - Otherwise, download the current LGPL "latest" build from BtbN, extract
::     ffmpeg.exe into .\bin, and check its SHA-256 against the tested value.
::       * match    -> tested build, proceed quietly.
::       * mismatch -> a NEWER, untested build. Warn and continue anyway.
:: LGPL is used (not GPL/nonfree) so the release stays redistributable. See
:: NOTICE for the attribution terms.
if exist ".\bin\ffmpeg.exe" (
    echo [INFO] Using existing .\bin\ffmpeg.exe - it will be bundled into the app.
    goto :ffmpeg_ready
)

echo [INFO] No .\bin\ffmpeg.exe found - downloading the latest LGPL build from BtbN...
if not exist ".\bin" mkdir ".\bin"

set "FFMPEG_ZIP=%TEMP%\ffmpeg-latest-win64-lgpl.zip"

:: Download the zip. $ProgressPreference is silenced because Invoke-WebRequest's
:: progress UI is very slow and prints a large, misleading byte counter.
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Uri '%FFMPEG_URL%' -OutFile '%FFMPEG_ZIP%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo [ERROR] Failed to download ffmpeg from:
    echo         %FFMPEG_URL%
    echo Check your internet connection, or manually place an LGPL ffmpeg.exe
    echo at .\bin\ffmpeg.exe and run the build again.
    goto :error
)

:: Verify SHA-256 of the DOWNLOADED ZIP against the tested value. (The recorded
:: hash is the zip's hash, as published on the BtbN release page - not the hash
:: of the ffmpeg.exe inside it.)
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash '%FFMPEG_ZIP%' -Algorithm SHA256).Hash.ToLower()"`) do set "FFMPEG_GOT_ZIP_SHA256=%%H"

echo [INFO] Tested zip SHA-256:     %FFMPEG_TESTED_ZIP_SHA256%
echo [INFO] Downloaded zip SHA-256: %FFMPEG_GOT_ZIP_SHA256%
if /i "%FFMPEG_GOT_ZIP_SHA256%"=="%FFMPEG_TESTED_ZIP_SHA256%" (
    echo [INFO] ffmpeg archive matches the tested build.
) else (
    echo.
    echo [WARNING] The downloaded ffmpeg is a NEWER, UNTESTED build than the one
    echo           this project was validated against. The build will continue
    echo           using it. If you distribute the result, update the recorded
    echo           version and SHA-256 values in NOTICE to match what you shipped,
    echo           and keep the FFmpeg source link current. See NOTICE for details.
    echo.
)

:: Extract ONLY bin\ffmpeg.exe from the zip (the archive is ~350 MB unpacked;
:: we need just the one ~114 MB exe). The entry is at
:: <top-folder>/bin/ffmpeg.exe, so match any entry ending in bin/ffmpeg.exe.
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { Add-Type -AssemblyName System.IO.Compression.FileSystem; $zip=[System.IO.Compression.ZipFile]::OpenRead('%FFMPEG_ZIP%'); $entry=$zip.Entries | Where-Object { $_.FullName -match 'bin/ffmpeg\.exe$' } | Select-Object -First 1; if ($null -eq $entry) { $zip.Dispose(); Write-Host 'ffmpeg.exe not found in archive'; exit 1 }; [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, '.\bin\ffmpeg.exe', $true); $zip.Dispose() } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
    echo [ERROR] Could not extract ffmpeg.exe from the downloaded archive.
    goto :error
)

:: Report the SHA-256 of the extracted ffmpeg.exe (the actual bundled binary).
:: This is recorded in NOTICE alongside the zip hash for full traceability.
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash '.\bin\ffmpeg.exe' -Algorithm SHA256).Hash.ToLower()"`) do set "FFMPEG_GOT_EXE_SHA256=%%H"
echo [INFO] Tested exe SHA-256:     %FFMPEG_TESTED_EXE_SHA256%
echo [INFO] Extracted exe SHA-256:  %FFMPEG_GOT_EXE_SHA256%
if /i "%FFMPEG_GOT_EXE_SHA256%"=="%FFMPEG_TESTED_EXE_SHA256%" (
    echo [INFO] Bundled ffmpeg.exe matches the tested binary.
) else (
    echo [WARNING] Bundled ffmpeg.exe differs from the tested binary. If you
    echo           distribute this build, record this exe SHA-256 in NOTICE.
)

:: Clean up temp download artifact (best-effort)
if exist "%FFMPEG_ZIP%" del /q "%FFMPEG_ZIP%" >nul 2>&1

:ffmpeg_ready
echo [INFO] ffmpeg is ready at .\bin\ffmpeg.exe

:: ==========================================================================
:: Build Script for %APP_NAME%
:: ==========================================================================
:: Creates a virtual environment, installs dependencies, and builds a
:: single-file windowed executable using PyInstaller.
:: ==========================================================================
echo [INFO] Python version matches. Starting build process...

:: 1. Create Virtual Environment
echo [STEP 1/4] Creating virtual environment in '.\venv'...

if not exist .\venv (
    :: Use 'python' here since we just verified it is the correct version
    python -m venv .\venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        goto :error
    )
) else (
    echo [INFO] Virtual environment '.\venv' already exists. Skipping creation.
)

:: 2. Activate Virtual Environment
echo [STEP 2/4] Activating virtual environment...
call .\venv\Scripts\activate.bat

if not defined VIRTUAL_ENV (
    echo [ERROR] Failed to activate the virtual environment. Make sure '.\venv\Scripts\activate.bat' exists.
    goto :error
)

:: 3. Install Dependencies
echo [STEP 3/4] Upgrading pip and installing dependencies from requirements.txt...
python -m pip install --upgrade pip > nul
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    goto :error
)

pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies from requirements.txt.
    goto :error
)

:: 4. Build with PyInstaller
::    -F                        one-file exe
::    --noupx                   do not use UPX compression
::    --clean                   clear PyInstaller cache first
::    --windowed                GUI app; no console window
::    --collect-all tkinterdnd2 bundle the tkdnd binaries so drag-and-drop works
::    --collect-all tkinter     bundle Tcl/Tk so the GUI runs on clean machines
::    --collect-all send2trash  bundle send2trash so Recycle Bin removal works
::    --add-data bin\ffmpeg.exe;bin   bundle ffmpeg; the app finds it at bin\ffmpeg.exe
::    --version-file version.txt  embeds Windows file-details version
::    --icon / --add-data icon.ico  app icon (added only if icon.ico exists)
echo [STEP 4/4] Building executable with PyInstaller...

set "ICON_ARGS="
if exist icon.ico (
    set "ICON_ARGS=--icon icon.ico --add-data icon.ico;."
    echo [INFO] icon.ico found - embedding application icon.
) else (
    echo [INFO] No icon.ico found - building without a custom icon.
)

pyinstaller -F --noupx --clean --windowed --name "%APP_NAME%" --collect-all tkinterdnd2 --collect-all tkinter --collect-all send2trash --add-data "bin\ffmpeg.exe;bin" --version-file version.txt !ICON_ARGS! ".\%SCRIPT_NAME%"

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    goto :error
)

echo.
echo [SUCCESS] Build completed successfully.
echo The executable can be found in the '.\dist' directory.
echo.
echo [REMINDER] ffmpeg is bundled inside the .exe. When you publish the release,
echo            include the LGPL attribution and a link to the ffmpeg source for
echo            the exact build you shipped. See NOTICE for the required text.
goto :end

:error
echo.
echo [FAILURE] The build process failed. Please check the errors above.
echo.
pause
exit /b 1

:end
echo.
pause
endlocal

@echo off
setlocal enabledelayedexpansion

:: ==========================================================================
:: Configuration
:: ==========================================================================
set "REQUIRED_PYTHON_VERSION=3.13.12"
set "PYTHON_DOWNLOAD_URL=https://www.python.org/downloads/release/python-31312/"
set "APP_NAME=MP3 Album Image Correction for Pioneer (500x500jpg)"
set "SCRIPT_NAME=MP3 Album Image Correction for Pioneer (500x500jpg).py"

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
:: Pre-flight Check: Verify bundled ffmpeg is present
:: ==========================================================================
:: The app calls ffmpeg to re-embed the artwork. This build bundles it so the
:: finished .exe is self-contained. Place an ffmpeg.exe at .\bin\ffmpeg.exe
:: before building. Use an LGPL build (not a GPL or "nonfree" build) so the
:: release stays redistributable - see NOTICE for the attribution terms.
if not exist ".\bin\ffmpeg.exe" (
    echo.
    echo [ERROR] Missing .\bin\ffmpeg.exe
    echo.
    echo This build bundles ffmpeg into the executable, but no ffmpeg.exe was
    echo found at .\bin\ffmpeg.exe. Create a 'bin' folder next to this script
    echo and put an ffmpeg.exe inside it, then run the build again.
    echo.
    echo [TIP] Use an LGPL "shared" or "essentials" ffmpeg build to keep the
    echo       release legally redistributable. See NOTICE for details.
    goto :error
)
echo [INFO] Found .\bin\ffmpeg.exe - it will be bundled into the app.

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

pyinstaller -F --noupx --clean --windowed --name "%APP_NAME%" --collect-all tkinterdnd2 --collect-all tkinter --add-data "bin\ffmpeg.exe;bin" --version-file version.txt !ICON_ARGS! ".\%SCRIPT_NAME%"

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

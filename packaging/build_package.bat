@echo off
cd /d "%~dp0.."

set workbench_ver_dot=2.0.5
set workbench_ver_us=2_0_5

set current_date=%date:~0,4%%date:~5,2%%date:~8,2%
set str_time=%time: =0%
set str_time=%str_time:~0,2%%str_time:~3,2%%str_time:~6,2%

set package_dir=ForRocketWorkbench_v%workbench_ver_dot%_%current_date%%str_time%
set zipfile_name=ForRocketWorkbench_v%workbench_ver_us%_%current_date%%str_time%.zip

echo [1/5] Compiling resources and UI...
pipenv run pyrcc5 -o pics_rc.py pics.qrc
if errorlevel 1 ( echo [ERROR] pyrcc5 failed & exit /b 1 )

pipenv run pyuic5 -o gui_tool\main_window_ui.py gui_tool\main_window.ui
if errorlevel 1 ( echo [ERROR] pyuic5 failed & exit /b 1 )

echo [2/5] Building executable...
pipenv run pyinstaller packaging\ForRocketWorkbench.spec --noconfirm
if errorlevel 1 ( echo [ERROR] PyInstaller failed & exit /b 1 )

echo [3/5] Copying extra files to dist\...
if exist ForRocket.exe (
    copy /Y ForRocket.exe dist\
) else if exist "%USERPROFILE%\ForRocket\build\ForRocket.exe" (
    copy /Y "%USERPROFILE%\ForRocket\build\ForRocket.exe" dist\
) else (
    echo [WARNING] ForRocket.exe not found - place it in the repo root or %%USERPROFILE%%\ForRocket\build\
)

copy /Y forrocket_icon.ico dist\
copy /Y LICENSE dist\

xcopy /E /I /Y projects\example dist\example
if errorlevel 1 ( echo [ERROR] Failed to copy example project & exit /b 1 )

echo [4/5] Packaging into %package_dir%\...
if exist %package_dir% rmdir /s /q %package_dir%
mkdir %package_dir%
xcopy /E /I /Y dist\* %package_dir%\
if errorlevel 1 ( echo [ERROR] Package directory copy failed & exit /b 1 )

echo [5/5] Creating zip archive...
powershell -Command "Compress-Archive -Path '%package_dir%\*' -DestinationPath '%zipfile_name%' -Force"
if errorlevel 1 ( echo [ERROR] Zip creation failed & exit /b 1 )

rmdir /s /q %package_dir%

echo.
echo Build complete: %zipfile_name%

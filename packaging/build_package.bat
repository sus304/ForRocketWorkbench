
@REM Run from the repository root: packaging\build_package.bat
cd /d "%~dp0.."

set workbench_ver_dot=2.0.5
set workbench_ver_us=2_0_5

set current_date=%date:~0,4%%date:~5,2%%date:~8,2%
set str_time=%time: =0%
set str_time=%str_time:~0,2%%str_time:~3,2%%str_time:~6,2%


set package_dir=ForRocketWorkbench_v%workbench_ver_dot%_%current_date%%str_time%
set zipfile_name=ForRocketWorkbench_v%workbench_ver_us%_%current_date%%str_time%.zip
set project_dir=ForRocketWorkbench

pipenv run pyrcc5 -o pics_rc.py pics.qrc
pipenv run pyuic5 -o gui_tool\main_window_ui.py gui_tool\main_window.ui
pipenv run pyinstaller packaging\ForRocketWorkbench.spec

copy ForRocket.exe dist
copy forrocket_icon.ico dist
copy LICENSE dist

copy configuration_files\sample_config_area.json dist
copy configuration_files\sample_config_montecarlo.json dist
copy configuration_files\sample_config_list_stage1.json dist
copy configuration_files\sample_config_solver.json dist
copy configuration_files\sample_param_engine.json dist
copy configuration_files\sample_param_rocket.json dist
copy configuration_files\sample_sequence_of_event.json dist
copy configuration_files\sample_CA.csv dist
copy configuration_files\sample_thrust.csv dist
copy configuration_files\sample_wind.csv dist

mkdir .\%package_dir%
copy .\dist .\%package_dir%

@REM powershell Compress-Archive -Path .\%package_dir%\ -DestinationPath %zipfile_name%

@REM rmdir /s /q .\%package_dir%

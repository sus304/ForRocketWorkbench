pipenv run pyinstaller .\ForRocketWorkbench.py --onefile --icon=forrocket_icon.ico
copy ForRocket.exe dist
copy forrocket_icon.ico dist
copy LICENSE dist
copy sample_CA.csv dist
copy sample_config_area.json dist
copy sample_config_list_stage1.json dist
copy sample_config_solver.json dist
copy sample_param_engine.json dist
copy sample_param_rocket.json dist
copy sample_sequence_of_event.json dist
copy sample_thrust.csv dist
copy sample_wind.csv dist

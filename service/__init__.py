"""ForRocket Workbench compute service.

A long-lived job service that owns MC/trajectory/area/sensitivity runs independently of any
UI process, so runs survive a UI crash or host reboot. See docs/compute_server_design.md.
"""

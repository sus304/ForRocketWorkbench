"""Service-native GUI (design §11.5, Phase 9).

New NiceGUI routes built to the compute service's job-queue model, coexisting with the legacy
single-job pages. The GUI is a thin client over service.client.ServiceClient: it submits input
closures, polls job status/progress, cancels, and renders results directly from the service's
local work_dir (use case ②). No calculation logic runs in the GUI process.
"""

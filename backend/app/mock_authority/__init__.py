"""Simulated issuing authorities and AICTE institutional records (synthetic data only).

In production these are replaced by real connectors (DigiLocker, API Setu, ICAI UDIN portal,
state fire services, AICTE portal DB). The backend talks to them only through
app/services/connectors.py, so swapping the adapter does not touch validation logic.
"""

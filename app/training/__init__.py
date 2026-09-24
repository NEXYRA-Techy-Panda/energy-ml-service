"""OFFLINE training/evaluation workflow for forecast candidates (P016).

Never imported by the production app (app.main). Candidates trained here are
not loaded by /v1/forecast; model_available stays false until a separate,
reviewed integration task.
"""

"""Domain services shared by HTTP routes and CLI workers.

Import the owning feature module explicitly. Services enforce domain access and
lifecycle rules; routes adapt inputs and responses. Transaction ownership and
external effects are documented in each feature and docs/CODE_GUIDE.md.
"""

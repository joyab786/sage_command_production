# backend/services/optimization_repository.py
"""
Re-export of OptimizationRepository from backend.repositories.optimization_repository
for backwards and forwards compatibility across codebase conventions.
"""

try:
    from repositories.optimization_repository import (
        OptimizationRepository,
        optimization_repository,
    )
except ModuleNotFoundError:
    from backend.repositories.optimization_repository import (
        OptimizationRepository,
        optimization_repository,
    )

__all__ = ["OptimizationRepository", "optimization_repository"]

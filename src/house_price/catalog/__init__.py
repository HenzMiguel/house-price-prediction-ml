"""Durable model-catalog domain and operational error taxonomy."""


class CatalogError(RuntimeError):
    """Base class for catalog failures with a stable CLI exit code."""

    exit_code = 5
    retryable = False


class CatalogConfigurationError(CatalogError):
    exit_code = 2


class CatalogPartialError(CatalogError):
    exit_code = 3


class CatalogDependencyError(CatalogError):
    exit_code = 4
    retryable = True


class CatalogPersistenceError(CatalogError):
    exit_code = 6


class CatalogProtectedOperationError(CatalogError):
    exit_code = 7


class CatalogLockUnavailable(CatalogError):
    exit_code = 8
    retryable = True

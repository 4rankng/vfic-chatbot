"""Access domain errors."""


class AccessDeniedError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ResourceNotFoundError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

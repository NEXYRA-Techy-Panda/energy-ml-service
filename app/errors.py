"""Errors that map directly to the contract error envelope."""


class ApiError(Exception):
    """{ "error": { "code", "message", "field"?, "row"? } } with an HTTP status."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None, row: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.row = row

    def body(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.field is not None:
            error["field"] = self.field
        if self.row is not None:
            error["row"] = self.row
        return {"error": error}

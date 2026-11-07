class ArenaError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details = details or {}

    def payload(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}

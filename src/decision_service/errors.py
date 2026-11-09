ERRORS = {
    "invalid_request": (400, "Invalid request."),
    "unauthenticated": (401, "A valid bearer credential is required."),
    "forbidden_scope": (403, "The project or bank is outside the allowed scope."),
    "not_found": (404, "Decision not found."),
    "input_conflict": (409, "Request ID was used with different input."),
    "revision_conflict": (409, "Feedback conflicts with the stored event or revision."),
    "request_in_progress": (409, "Decision is still processing."),
    "unavailable": (503, "Decision service is unavailable."),
}


class APIError(Exception):
    def __init__(self, code, **refs):
        self.code, self.refs = code, refs


def error_payload(code, **refs):
    return {"error": {"code": code, "message": ERRORS[code][1], **refs}}

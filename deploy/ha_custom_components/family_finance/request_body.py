"""Request shape for the dashboard API and the local onboarding endpoint."""


def backend_body(message: dict, *, onboarding: bool, no_body: bool) -> dict | None:
    if no_body:
        return None
    body = {"operation": message["operation"], "payload": message.get("payload", {})}
    if not onboarding:
        body["source"] = message["source"]
    return body

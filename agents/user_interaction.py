def detect_language(message: str) -> str:
    if any("\u0b80" <= character <= "\u0bff" for character in message):
        return "ta"
    if any("\u0900" <= character <= "\u097f" for character in message):
        return "hi"
    return "en"

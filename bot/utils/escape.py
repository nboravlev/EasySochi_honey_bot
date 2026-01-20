from html import escape as html_escape

def safe_html(text: str | None) -> str:
    """Экранирует пользовательский ввод для безопасного использования в HTML сообщений Telegram."""
    if not text:
        return ""
    return html_escape(text)
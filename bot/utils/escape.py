from html import escape as html_escape

def safe_html(text) -> str:
    """Экранирует пользовательский ввод для безопасного использования в HTML сообщений Telegram."""
    if text is None or text == "":
        return ""
    return html_escape(str(text))
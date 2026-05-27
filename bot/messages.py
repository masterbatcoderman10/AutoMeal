def format_ack_message(meal_id: str) -> str:
    return f"📸 Received, processing… (ID: {meal_id[:8]})"


def format_start_message() -> str:
    return "MealTracker bot is active. Snap a photo and I'll log your meal."


def format_error_message() -> str:
    return "⚠️ Something went wrong processing your meal. I'll retry shortly."


def format_result_sentence(labels: list[str]) -> str:
    cleaned: list[str] = []
    for raw_label in labels:
        if not raw_label:
            continue
        label = raw_label.strip()
        if not label:
            continue
        cleaned.append(label)

    item_count = len(cleaned)
    if item_count == 0:
        return "I see your meal."
    return f"I see {item_count} items: {', '.join(cleaned)}."

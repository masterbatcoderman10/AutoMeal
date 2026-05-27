def format_ack_message(meal_id: str) -> str:
    return f"📸 Received, processing… (ID: {meal_id[:8]})"


def format_start_message() -> str:
    return "MealTracker bot is active. Snap a photo and I'll log your meal."


def format_error_message() -> str:
    return "⚠️ Something went wrong processing your meal. I'll retry shortly."

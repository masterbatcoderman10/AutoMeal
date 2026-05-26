import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.models.meal_log import MealProcessingStatus


class MessageTemplateTests(unittest.TestCase):
    def test_ack_message_truncates_meal_id(self) -> None:
        from bot.messages import format_ack_message

        self.assertEqual(
            format_ack_message("12345678-abcd-efgh"),
            "📸 Received, processing… (ID: 12345678)",
        )

    def test_start_message(self) -> None:
        from bot.messages import format_start_message

        self.assertEqual(
            format_start_message(),
            "MealTracker bot is active. Snap a photo and I'll log your meal.",
        )

    def test_error_message(self) -> None:
        from bot.messages import format_error_message

        self.assertEqual(
            format_error_message(),
            "⚠️ Something went wrong processing your meal. I'll retry shortly.",
        )


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_replies_with_start_message(self) -> None:
        from bot.handlers import start
        from bot.messages import format_start_message

        reply_text = AsyncMock()
        update = SimpleNamespace(message=SimpleNamespace(reply_text=reply_text))

        await start(update, SimpleNamespace())

        reply_text.assert_awaited_once_with(format_start_message())

    async def test_help_replies_with_shortcut_hint(self) -> None:
        from bot.handlers import help_command

        reply_text = AsyncMock()
        update = SimpleNamespace(message=SimpleNamespace(reply_text=reply_text))

        await help_command(update, SimpleNamespace())

        reply_text.assert_awaited_once_with(
            "Send a meal photo via the iOS Shortcut. I'll process it and tell you what I found."
        )


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_claims_pending_meal_and_acknowledges_it(self) -> None:
        from bot import polling

        meal = SimpleNamespace(
            id="12345678-abcd-efgh",
            processing_status=MealProcessingStatus.PENDING,
        )
        session = AsyncMock()
        session.execute.return_value.scalar_one_or_none.return_value = meal

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        bot = SimpleNamespace(send_message=AsyncMock())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=object()) as create_engine,
            patch.object(polling, "async_sessionmaker", return_value=session_factory) as sessionmaker,
            patch.object(polling, "format_ack_message", return_value="ack text") as format_ack_message,
            patch.object(
                polling.asyncio,
                "sleep",
                side_effect=asyncio.CancelledError,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_acknowledge(bot, settings, poll_interval=0.01)

        create_engine.assert_called_once_with(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
        )
        sessionmaker.assert_called_once()
        bot.send_message.assert_awaited_once_with(chat_id="999", text="ack text")
        format_ack_message.assert_called_once_with(meal.id)
        session.commit.assert_awaited_once()
        self.assertEqual(meal.processing_status, MealProcessingStatus.DETECTING)

    async def test_poll_reraises_cancelled_error(self) -> None:
        from bot import polling

        session = AsyncMock()
        session.execute.side_effect = asyncio.CancelledError

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        session_factory = Mock(return_value=SessionContext())
        settings = SimpleNamespace(
            DATABASE_URL="postgresql+asyncpg://meal:pw@db:5432/meal",
            TELEGRAM_CHAT_ID="999",
            BOT_POLL_INTERVAL=3.0,
        )

        with (
            patch.object(polling, "create_async_engine", return_value=object()),
            patch.object(polling, "async_sessionmaker", return_value=session_factory),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await polling.poll_and_acknowledge(
                    SimpleNamespace(send_message=AsyncMock()),
                    settings,
                    poll_interval=0.01,
                )


class MainWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_init_starts_background_polling_task(self) -> None:
        from bot import main as bot_main

        application = SimpleNamespace(bot=object(), bot_data={})
        settings = SimpleNamespace(BOT_POLL_INTERVAL=3.0)
        fake_task = object()

        with (
            patch.object(bot_main, "get_settings", return_value=settings),
            patch.object(bot_main, "poll_and_acknowledge", new=AsyncMock()) as poll_and_acknowledge,
            patch.object(bot_main.asyncio, "create_task", return_value=fake_task) as create_task,
        ):
            await bot_main.post_init(application)

        poll_and_acknowledge.assert_called_once_with(
            application.bot,
            settings,
            settings.BOT_POLL_INTERVAL,
        )
        create_task.assert_called_once()
        self.assertIs(application.bot_data["poll_task"], fake_task)

    async def test_post_shutdown_cancels_background_polling_task(self) -> None:
        from bot import main as bot_main

        poll_task = AsyncMock()
        poll_task.cancel = Mock()
        application = SimpleNamespace(bot_data={"poll_task": poll_task})

        await bot_main.post_shutdown(application)

        poll_task.cancel.assert_called_once_with()
        poll_task.assert_awaited_once()

    def test_main_builds_application_and_runs_polling(self) -> None:
        from bot import main as bot_main

        settings = SimpleNamespace(TELEGRAM_BOT_TOKEN="token")
        builder = Mock()
        application = Mock()

        builder.token.return_value = builder
        builder.post_init.return_value = builder
        builder.post_shutdown.return_value = builder
        builder.build.return_value = application

        with (
            patch.object(bot_main, "get_settings", return_value=settings),
            patch.object(bot_main.Application, "builder", return_value=builder),
            patch.object(bot_main, "CommandHandler", side_effect=lambda name, fn: (name, fn)),
        ):
            bot_main.main()

        builder.token.assert_called_once_with("token")
        builder.post_init.assert_called_once_with(bot_main.post_init)
        builder.post_shutdown.assert_called_once_with(bot_main.post_shutdown)
        application.add_handler.assert_called_once()
        application.run_polling.assert_called_once_with(
            allowed_updates=bot_main.Update.ALL_TYPES,
            drop_pending_updates=True,
        )

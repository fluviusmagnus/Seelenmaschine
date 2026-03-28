import asyncio
import html
import json
from typing import Any, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from core.approval import ApprovalService, PendingApprovalRequest
from utils.logger import get_logger

logger = get_logger()


class TelegramToolBridge:
    """Bridge tool approval and status notifications into Telegram."""

    def __init__(self, handler: Any):
        self.handler = handler

    async def request_approval(
        self, tool_name: str, arguments: dict, reason: str
    ) -> bool:
        """Send an approval request to the user and wait for a decision."""
        approval_service = getattr(self.handler, "_approval_service", None)
        if isinstance(approval_service, ApprovalService):

            async def _send_approval_message(
                text: str, parse_mode: Optional[str]
            ) -> None:
                if not getattr(self.handler, "telegram_bot", None):
                    return

                kwargs: Dict[str, Any] = {
                    "chat_id": self.handler.core_bot.config.TELEGRAM_USER_ID,
                    "text": text,
                }
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode
                await self.handler.telegram_bot.send_message(**kwargs)

            send_message = None
            if getattr(self.handler, "telegram_bot", None):
                send_message = _send_approval_message

            return await approval_service.request_approval(
                tool_name,
                arguments,
                reason,
                send_message=send_message,
                timeout_seconds=600.0,
            )

        async with self.handler._approval_lock:
            loop = asyncio.get_running_loop()
            pending_request = PendingApprovalRequest(
                tool_name=tool_name,
                arguments=dict(arguments),
                reason=reason,
                future=loop.create_future(),
                created_at=loop.time(),
            )
            self.handler._pending_approval = pending_request

            args_str = html.escape(json.dumps(arguments, ensure_ascii=False)[:800])
            msg = (
                "⚠️ <b>DANGEROUS ACTION DETECTED</b> ⚠️\n\n"
                f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
                f"<b>Reason:</b> <code>{html.escape(reason)}</code>\n"
                f"<b>Arguments:</b>\n<pre>{args_str}</pre>\n\n"
                "Reply <b>/approve</b> to execute.\n"
                "Any other message will <b>ABORT</b> this action."
            )

            if getattr(self.handler, "telegram_bot", None):
                try:
                    await self.handler.telegram_bot.send_message(
                        chat_id=self.handler.core_bot.config.TELEGRAM_USER_ID,
                        text=msg,
                        parse_mode="HTML",
                    )
                except Exception as error:
                    logger.error(f"Failed to send approval request: {error}")
                    self.handler._pending_approval = None
                    return False

            logger.info(
                "Approval request created for dangerous action: "
                f"tool={tool_name}, reason={reason}, args={arguments}"
            )

            try:
                approved = await asyncio.wait_for(pending_request.future, timeout=600.0)
            except asyncio.TimeoutError:
                approved = False
                logger.warning(
                    "Approval request timed out: " f"tool={tool_name}, reason={reason}"
                )
                if getattr(self.handler, "telegram_bot", None):
                    try:
                        await self.handler.telegram_bot.send_message(
                            chat_id=self.handler.core_bot.config.TELEGRAM_USER_ID,
                            text="⏰ Approval timed out. Action aborted.",
                        )
                    except Exception:
                        pass
            finally:
                if self.handler._pending_approval is pending_request:
                    self.handler._pending_approval = None

            return approved

    async def send_status_message(
        self, text: str, parse_mode: Optional[str] = None
    ) -> None:
        """Best-effort Telegram status notification."""
        if not getattr(self.handler, "telegram_bot", None):
            return

        try:
            kwargs: Dict[str, Any] = {
                "chat_id": self.handler.core_bot.config.TELEGRAM_USER_ID,
                "text": text,
            }
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await self.handler.telegram_bot.send_message(**kwargs)
        except Exception as error:
            logger.warning(f"Failed to send status message: {error}")

    async def notify_approved_action_finished(
        self, tool_name: str, result: str
    ) -> None:
        """Inform user that an approved action finished running."""
        result_preview = html.escape(self.handler._preview_text(result, max_length=300))
        if result.startswith("Error:") or result.startswith("Command failed"):
            prefix = "⚠️ <b>Approved action finished with an error-like result</b>"
        else:
            prefix = "✅ <b>Approved action finished</b>"

        msg = (
            f"{prefix}\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Result preview:</b> <pre>{result_preview}</pre>"
        )
        await self.send_status_message(msg, parse_mode="HTML")

    async def notify_approved_action_failed(
        self, tool_name: str, error: Exception
    ) -> None:
        """Inform user that an approved action failed unexpectedly."""
        error_preview = html.escape(self.handler._format_exception_for_user(error))
        msg = (
            "❌ <b>Approved action failed unexpectedly</b>\n\n"
            f"<b>Tool:</b> <code>{html.escape(tool_name)}</code>\n"
            f"<b>Error:</b> <pre>{error_preview}</pre>"
        )
        await self.send_status_message(msg, parse_mode="HTML")

    async def handle_approve(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /approve command to authorize a pending dangerous action."""
        del context
        if not update.effective_user or not update.message:
            return
        if update.effective_user.id != self.handler.core_bot.config.TELEGRAM_USER_ID:
            return

        approval_service = getattr(self.handler, "_approval_service", None)
        if isinstance(approval_service, ApprovalService):
            pending_request = approval_service.approve_pending()
        else:
            pending_request = self.handler._pending_approval
            if pending_request and not pending_request.future.done():
                pending_request.future.set_result(True)
                logger.info(
                    "Approval received from user: "
                    f"tool={pending_request.tool_name}, reason={pending_request.reason}"
                )

        if pending_request is None:
            await update.message.reply_text("No pending action to approve.")

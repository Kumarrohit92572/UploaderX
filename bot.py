import asyncio
import os
import time
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ForceReply,
    CallbackQuery,
)
from config import API_ID, API_HASH, BOT_TOKEN, AUTH_USERS
from database import db
from downloader import Downloader
import logging
from pyrogram.enums import ParseMode
import traceback

# Initialize bot
app = Client("url_uploader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Set up logging for Pyrogram to avoid excessive messages
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pyrogram.client").setLevel(logging.WARNING)
logging.getLogger("pyrogram.connection.connection").setLevel(logging.WARNING)
logging.getLogger("pyrogram.dispatcher").setLevel(logging.WARNING)

# Set up logger for bot
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(handler)

# User states
USER_STATES = {}


def format_size(size_bytes):
    """Format size in human-readable form"""
    if size_bytes is None or size_bytes == 0:
        return "0 B"

    # Convert to float and define units
    size_bytes = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]

    # Determine appropriate unit
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024
        i += 1

    # Format with proper precision
    if i == 0:
        return f"{int(size_bytes)} {units[i]}"
    else:
        return f"{size_bytes:.2f} {units[i]}"


def create_progress_bar(progress):
    """Create a beautiful progress bar"""
    bar_length = 20
    filled_length = int(bar_length * progress / 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)
    return bar


# Function to determine if file is a video
def is_video_file(file_path):
    """Check if the file is a video based on its extension"""
    video_extensions = [
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".3gp",
    ]
    ext = os.path.splitext(file_path)[1].lower()
    return ext in video_extensions


@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    if message.from_user.id not in AUTH_USERS:
        await message.reply_text(
            "⚠️ You are not authorized to use this bot.\n"
            "Please contact the administrator for access.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📞 Contact Admin", url="https://t.me/your_admin_username"
                        )
                    ]
                ]
            ),
        )
        return

    welcome_text = (
        "🌟 **Welcome to URL Uploader Bot!** 🌟\n\n"
        "This bot helps you download and upload files from various sources.\n\n"
        "**Features:**\n"
        "• Support for videos, PDFs, and images\n"
        "• Real-time download progress\n"
        "• Modern UI with progress bar\n"
        "• Decryption support for special videos\n"
        "• High-quality video uploads with thumbnails\n\n"
        "Let's get started! Please provide your @username to continue."
    )

    USER_STATES[message.from_user.id] = {"state": "waiting_username"}
    await message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
                [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
            ]
        ),
    )


@app.on_message(filters.command("stop"))
async def stop_command(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in USER_STATES:
        # Cancel any active downloads
        if USER_STATES[user_id].get("canceled") != True:
            USER_STATES[user_id]["canceled"] = True

        del USER_STATES[user_id]
        await message.reply_text(
            "👋 Thank you for using URL Uploader Bot!\n\n"
            "Send /start to begin a new session.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Start New Session", callback_data="start")]]
            ),
        )
    else:
        await message.reply_text(
            "❌ No active session found.\n\n" "Send /start to begin a new session.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Start New Session", callback_data="start")]]
            ),
        )


@app.on_message(filters.text & filters.private & ~filters.command(["start", "stop"]))
async def handle_messages(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in AUTH_USERS:
        return

    if user_id not in USER_STATES:
        await start_command(client, message)
        return

    state = USER_STATES[user_id].get("state")

    if state == "waiting_username":
        username = message.text
        if not username.startswith("@"):
            await message.reply_text(
                "⚠️ Invalid username format!\n"
                "Please provide a valid username starting with @",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
                ),
            )
            return

        USER_STATES[user_id].update(
            {"username": username, "state": "waiting_batch_name"}
        )

        await message.reply_text(
            "📝 Please provide a batch name for your files:\n\n"
            "Example: `URL Uploader 2024`",
            reply_markup=ForceReply(selective=True),
        )

    elif state == "waiting_batch_name":
        batch_name = message.text.strip()
        USER_STATES[user_id].update(
            {"batch_name": batch_name, "state": "waiting_file_url"}
        )

        await message.reply_text(
            "📝 Please send the file details in the format:\n\n"
            "`Filename : URL`\n\n"
            "Example:\n"
            "`My Video : https://example.com/video.mp4`\n"
            "`Encrypted Video : https://example.com/video.mkv*12345`\n\n"
            "Use /stop to end the session at any time.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ForceReply(selective=True),
        )

    elif state == "waiting_file_url":
        if ":" not in message.text:
            await message.reply_text(
                "⚠️ Invalid format!\n\n"
                "Please use the format:\n"
                "`Filename : URL`\n"
                "For encrypted videos: `Filename : URL.mkv*key`\n\n"
                "Examples:\n"
                "`My Video : https://example.com/video.mp4`\n"
                "`Encrypted Video : https://example.com/video.mkv*12345`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ForceReply(selective=True),
            )
            return

        filename, url = [x.strip() for x in message.text.split(":", 1)]
        if not filename or not url:
            await message.reply_text(
                "⚠️ Invalid format!\n\n" "Please provide both filename and URL.",
                reply_markup=ForceReply(selective=True),
            )
            return

        # Check if it's an encrypted video URL
        is_encrypted = "*" in url and any(
            ext in url.lower()
            for ext in [".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"]
        )

        # Store current download info in case user wants to cancel
        USER_STATES[user_id]["current_task"] = {
            "filename": filename,
            "url": url,
            "is_encrypted": is_encrypted,
            "status_message": None,
            "last_update_time": 0,
        }

        # Set canceled flag to False for new download
        USER_STATES[user_id]["canceled"] = False

        # Initial status message
        status_message = await message.reply_text(
            f"{'🔐 Dᴇᴄʀʏᴘᴛɪɴɢ & ' if is_encrypted else ''}Dᴏᴡɴʟᴏᴀᴅ Sᴛᴀʀᴛᴇᴅ....\n\n"
            "⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜\n\n"
            "╭━━━━❰ᴘʀᴏɢʀᴇss ʙᴀʀ❱━➣\n"
            "┣⪼ 🗃️ Sɪᴢᴇ: Waiting... \n"
            "┣⪼ ⏳️ Dᴏɴᴇ : 0%\n"
            "┣⪼ 🚀 Sᴩᴇᴇᴅ: Calculating...\n"
            "┣⪼ ⏰️ Eᴛᴀ: Calculating...\n"
            "╰━━━━━━━━━━━━━━━➣",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]]
            ),
        )

        # Save status message for potential cancellation and updates
        USER_STATES[user_id]["current_task"]["status_message"] = status_message
        USER_STATES[user_id]["current_task"]["message_id"] = status_message.id
        USER_STATES[user_id]["current_task"]["chat_id"] = status_message.chat.id

        # Helper function to format ETA
        def format_eta(seconds):
            if seconds is None or seconds <= 0:
                return "Almost done..."

            minutes, seconds = divmod(int(seconds), 60)
            hours, minutes = divmod(minutes, 60)

            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"

        # Progress callback - updates the status message
        async def progress_callback(
            progress, speed, total_size, downloaded_size, eta, filename=""
        ):
            try:
                # Check if user has canceled
                if user_id not in USER_STATES or USER_STATES[user_id].get(
                    "canceled", False
                ):
                    return

                # Get current task info
                current_task = USER_STATES[user_id].get("current_task", {})
                current_message = current_task.get("status_message")

                # If no message to update, exit
                if not current_message:
                    logger.warning(f"No status message found for user {user_id}")
                    return

                # Create progress text
                progress_bar = create_progress_bar(progress)
                status_text = (
                    f"{'🔐 Dᴇᴄʀʏᴘᴛɪɴɢ & ' if is_encrypted else ''}Dᴏᴡɴʟᴏᴀᴅɪɴɢ....\n\n"
                    f"{progress_bar}\n\n"
                    "╭━━━━❰ᴘʀᴏɢʀᴇss ʙᴀʀ❱━➣\n"
                    f"┣⪼ 🗃️ Sɪᴢᴇ: {format_size(downloaded_size)} / {format_size(total_size)}\n"
                    f"┣⪼ ⏳️ Dᴏɴᴇ : {progress:.1f}%\n"
                    f"┣⪼ 🚀 Sᴩᴇᴇᴅ: {format_size(speed)}/s\n"
                    f"┣⪼ ⏰️ Eᴛᴀ: {format_eta(eta)}\n"
                    "╰━━━━━━━━━━━━━━━➣"
                )

                # Update the message with new progress
                try:
                    await current_message.edit_text(
                        status_text,
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "❌ Cancel", callback_data="cancel_download"
                                    )
                                ]
                            ]
                        ),
                    )
                    # Log successful update
                    logger.info(f"Updated progress for user {user_id}: {progress:.1f}%")
                except Exception as e:
                    logger.error(f"Failed to update progress message: {e}")

            except Exception as e:
                # Log the full exception with traceback
                logger.error(f"Progress callback error: {e}")
                logger.error(traceback.format_exc())

        try:
            # Create and start downloader
            downloader = Downloader(url, filename, progress_callback)
            success, result, video_info = await downloader.download()

            # Check if user has canceled during download
            if user_id not in USER_STATES or USER_STATES[user_id].get(
                "canceled", False
            ):
                if result and os.path.exists(result):
                    os.remove(result)
                if (
                    video_info
                    and video_info.thumbnail
                    and os.path.exists(video_info.thumbnail)
                ):
                    os.remove(video_info.thumbnail)
                return

            if not success:
                await status_message.edit_text(
                    f"❌ Download failed!\n\n"
                    f"Error: {result}\n\n"
                    f"Please try again or contact support if the problem persists.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "🔄 Try Again", callback_data="continue"
                                )
                            ]
                        ]
                    ),
                )
                return

            await status_message.edit_text(
                "📤 Uploading to Telegram...\n\n"
                "Please wait while we upload your file."
            )

            # Different caption formats for different file types
            caption = (
                "➖➖➖➖➖➖➖➖➖➖\n"
                "📂 **File Details**\n"
                "➖➖➖➖➖➖➖➖➖➖\n"
                f"📝 **File Name:** `{filename}`\n"
                f"👤 **Downloaded By:** _{USER_STATES[user_id]['username']}_\n"
                f"🎯 **Batch:** `{USER_STATES[user_id]['batch_name']}`\n"
                f"⚡ **Status:** ✅ _Successfully Processed_\n"
                "\n"
                "🔗 __Stay Connected:__ [@MrGadhvii](https://t.me/MrGadhvii)\n"
                "➖➖➖➖➖➖➖➖➖➖"
            )

            # Last upload update time
            last_upload_update_time = time.time()
            update_interval = 2  # seconds between updates

            # Progress callback for upload with rate limiting
            async def upload_progress(current, total):
                nonlocal last_upload_update_time
                current_time = time.time()

                # Throttle updates to avoid Telegram's rate limits
                if (current_time - last_upload_update_time) < update_interval:
                    return

                last_upload_update_time = current_time

                try:
                    # Check if user has canceled
                    if user_id not in USER_STATES or USER_STATES[user_id].get(
                        "canceled", False
                    ):
                        return

                    progress = (current / total) * 100
                    progress_bar = create_progress_bar(progress)
                    status_text = (
                        "📤 Uᴘʟᴏᴀᴅɪɴɢ....\n\n"
                        f"{progress_bar}\n\n"
                        "╭━━━━❰ᴘʀᴏɢʀᴇss ʙᴀʀ❱━➣\n"
                        f"┣⪼ 🗃️ Sɪᴢᴇ: {format_size(current)} / {format_size(total)}\n"
                        f"┣⪼ ⏳️ Dᴏɴᴇ : {progress:.1f}%\n"
                        "╰━━━━━━━━━━━━━━━➣"
                    )
                    await status_message.edit_text(status_text)
                    logger.info(f"Upload progress for user {user_id}: {progress:.1f}%")
                except Exception as e:
                    logger.error(f"Upload progress error: {e}")

            # Get thumbnail path from video_info
            thumbnail_path = None
            if (
                video_info
                and video_info.thumbnail
                and os.path.exists(video_info.thumbnail)
            ):
                thumbnail_path = video_info.thumbnail
                logger.info(f"Using thumbnail: {thumbnail_path}")

            # Send as video if it's a video file, otherwise as document
            if is_video_file(result):
                try:
                    # Get video dimensions and duration from metadata
                    width = (
                        video_info.width
                        if video_info and video_info.width > 0
                        else 1280
                    )
                    height = (
                        video_info.height
                        if video_info and video_info.height > 0
                        else 720
                    )
                    duration = (
                        video_info.duration
                        if video_info and video_info.duration > 0
                        else 60
                    )

                    # Log video metadata for debugging
                    logger.info(
                        f"Sending video: {os.path.basename(result)}, {width}x{height}, {duration}s"
                    )
                    if thumbnail_path:
                        logger.info(
                            f"Using thumbnail: {os.path.basename(thumbnail_path)}"
                        )

                    # Send as video with proper thumb and metadata
                    await message.reply_video(
                        result,
                        caption=caption,
                        supports_streaming=True,
                        width=width,
                        height=height,
                        duration=duration,
                        thumb=thumbnail_path,
                        progress=upload_progress,
                    )
                    logger.info(f"Successfully sent video to user {user_id}")
                except Exception as video_error:
                    logger.error(f"Error sending as video: {video_error}")
                    logger.error(traceback.format_exc())
                    # Fallback to document if video send fails
                    await message.reply_document(
                        result,
                        caption=caption,
                        thumb=thumbnail_path,
                        progress=upload_progress,
                    )
                    logger.info(
                        f"Sent as document after video error for user {user_id}"
                    )
            else:
                # Send as document for non-video files
                await message.reply_document(
                    result,
                    caption=caption,
                    thumb=thumbnail_path,
                    progress=upload_progress,
                )
                logger.info(f"Sent document to user {user_id}")

            # Clean up the files after sending
            if os.path.exists(result):
                os.remove(result)
                logger.info(f"Removed downloaded file: {result}")
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                logger.info(f"Removed thumbnail: {thumbnail_path}")

            # Delete status message
            try:
                await status_message.delete()
            except Exception as e:
                logger.error(f"Error deleting status message: {e}")

            await message.reply_text(
                "✅ File uploaded successfully!\n\n"
                "Would you like to download another file?",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("✅ Yes", callback_data="continue"),
                            InlineKeyboardButton("❌ No", callback_data="stop"),
                        ]
                    ]
                ),
            )
        except Exception as e:
            logger.error(f"Download/upload error: {e}")
            logger.error(traceback.format_exc())
            await status_message.edit_text(
                f"❌ An error occurred!\n\n"
                f"Error: {str(e)}\n\n"
                f"Please try again or contact support if the problem persists.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔄 Try Again", callback_data="continue")]]
                ),
            )


@app.on_callback_query()
async def answer_callback(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    message = callback_query.message

    if data == "cancel":
        if user_id in USER_STATES:
            del USER_STATES[user_id]

        await message.edit_text(
            "❌ Operation cancelled.\n\n" "Send /start to begin a new session.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Start New Session", callback_data="start")]]
            ),
        )

    elif data == "cancel_download":
        # Mark the download as canceled
        if user_id in USER_STATES:
            USER_STATES[user_id]["canceled"] = True
            logger.info(f"User {user_id} canceled download")
            await message.edit_text(
                "❌ Download cancelled.\n\n" "Send /start to begin a new session.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔄 Start New Session", callback_data="start"
                            )
                        ]
                    ]
                ),
            )

    elif data == "start":
        await start_command(client, callback_query.message)

    elif data == "continue":
        if user_id in USER_STATES:
            USER_STATES[user_id].update({"state": "waiting_file_url"})

            await message.edit_text(
                "📝 Please send the file details in the format:\n\n"
                "`Filename : URL`\n\n"
                "Example:\n"
                "`My Video : https://example.com/video.mp4`\n"
                "`Encrypted Video : https://example.com/video.mkv*12345`\n\n"
                "Use /stop to end the session at any time.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None,
            )

    elif data == "stop":
        if user_id in USER_STATES:
            del USER_STATES[user_id]

        await message.edit_text(
            "👋 Thank you for using URL Uploader Bot!\n\n"
            "Send /start to begin a new session.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Start New Session", callback_data="start")]]
            ),
        )

    elif data == "help":
        await message.edit_text(
            "ℹ️ **Help & Information**\n\n"
            "This bot helps you download files from URLs and upload them to Telegram.\n\n"
            "**Commands:**\n"
            "/start - Start the bot\n"
            "/stop - Stop the current session\n\n"
            "**URL Formats:**\n"
            "- Regular videos: `Filename : https://example.com/video.mp4`\n"
            "- Encrypted videos: `Filename : https://example.com/video.mkv*decryption_key`\n\n"
            "**Features:**\n"
            "- High-quality video uploads with thumbnails\n"
            "- Real-time progress display\n"
            "- Decryption for special video URLs\n"
            "- Support for various file formats\n\n"
            "For more help, contact the bot administrator.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="start")]]
            ),
        )

    await callback_query.answer()


# Start the bot
if __name__ == "__main__":
    logger.info("Starting URL Uploader Bot...")
    app.run()

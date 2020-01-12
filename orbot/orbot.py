# -*- coding: UTF-8 -*-
# This file is part of the orbot package (https://github.com/officinerobotiche/orbot or http://www.officinerobotiche.it).
# Copyright (C) 2020, Raffaello Bonghi <raffaello@rnext.it>
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


import json
import logging
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
import re
import os
from functools import wraps
from uuid import uuid4
import sys
from threading import Thread

from .utils import build_menu, check_key_id, isAdmin, filter_channel, restricted, rtype, register
from .channels import Channels
from .config import Config
from .announce import Announce
from .sites import Sites

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
# Version match
VERSION_RE = re.compile(r""".*__version__ = ["'](.*?)['"]""", re.S)


def get_version():
    # Load version package
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, "__init__.py")) as fp:
        VERSION = VERSION_RE.match(fp.read()).group(1)
    return VERSION


class ORbot:

    class BotException(Exception):
        pass

    def __init__(self, settings_file):
        # Load settings
        self.settings_file = settings_file
        try:
            with open(settings_file) as stream:
                self.settings = json.load(stream)
        except FileNotFoundError:
            raise ORbot.BotException(f"Setting file in {self.settings_file} not found")
        if 'telegram' not in self.settings:
            raise ORbot.BotException(f"telegram config is not defined on {self.settings_file}")
        telegram = self.settings['telegram']
        # List of admins
        if 'token' not in telegram:
            raise ORbot.BotException(f"token is not defined in telegram config")
        if 'admins' not in telegram:
            raise ORbot.BotException(f"admins are not defined in telegram config")
        self.LIST_OF_ADMINS = telegram['admins']
        # Create the Updater and pass it your bot's token.
        # Make sure to set use_context=True to use the new context based callbacks
        # Post version 12 this will no longer be necessary
        self.updater = Updater(telegram['token'], use_context=True)
        # Settings manager
        self.channels = Channels(self.updater, self.settings, self.settings_file)
        # Configuration manager
        self.config = Config(self.updater, self.settings, self.settings_file, self.channels)
        # Announce manager
        self.announce = Announce(self.updater, self.settings, self.settings_file, self.channels)
        # Sites manager
        self.sites = Sites(self.updater, self.settings, self.settings_file, self.channels)
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Add commands
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("help", self.help))
        dp.add_handler(CommandHandler('restart', self.restart))
        # Unknown handler
        unknown_handler = MessageHandler(Filters.command, self.unknown)
        dp.add_handler(unknown_handler)
        # Add group handle
        add_group_handle = MessageHandler(Filters.status_update.new_chat_members, self.add_group)
        dp.add_handler(add_group_handle)
        # log all errors
        dp.add_error_handler(self.error)
        # Send a message to all admins when the system is started
        version = get_version()
        # Run the bot and send a welcome message
        bot = Bot(token=telegram['token'])
        infobot = bot.get_me()
        logger.info(f"Bot: {infobot}")
        for user_chat_id in self.LIST_OF_ADMINS:
            bot.send_message(chat_id=user_chat_id, text=f"🤖 Bot started! v{version}")

    def runner(self):
        # Start the Bot
        self.updater.start_polling()
        # Run the bot until you press Ctrl-C or the process receives SIGINT,
        # SIGTERM or SIGABRT. This should be used most of the time, since
        # start_polling() is non-blocking and will stop the bot gracefully.
        self.updater.idle()

    @register
    @filter_channel
    def start(self, update, context):
        """ Start ORbot """
        user = update.message.from_user
        logger.info(f"New user join {user['first_name']}")
        message = 'Welcome to ORbot'
        context.bot.send_message(chat_id=update.effective_user.id, text=message, parse_mode='HTML')

    def stop_and_restart(self):
        """Gracefully stop the Updater and replace the current process with a new one"""
        self.updater.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    @filter_channel
    @rtype(['private'])
    @restricted
    def restart(self, update, context):
        for user_chat_id in self.LIST_OF_ADMINS:
            context.bot.send_message(chat_id=user_chat_id, text='Bot is restarting...')
        Thread(target=self.stop_and_restart).start()

    @register
    @filter_channel
    def unknown(self, update, context):
        logger.info(f"Unknown command: {update.message.text}")
        context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")

    @register
    def add_group(self, update, context):
        new_members = []
        for member in update.message.new_chat_members:
            isMember = self.channels.isMember(context, member.id)
            if not member.is_bot and update.effective_chat.id in isMember and len(isMember) == 1:
                new_members += [member.username]
        # If there are new members send welcome
        if new_members:
            # Build list channels buttons
            members_string = ", ".join(new_members)
            reply_markup = self.channels.getChannels(update, context)
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=f"{members_string} Welcome! All channels avalable are:",
                                     reply_markup=reply_markup)

    @register
    @filter_channel
    def help(self, update, context):
        """ Help list of all commands """
        #chat_id = update.effective_chat.id
        message = ""
        if 'private' in self.channels.isAllowed(update, context):
            if not self.channels.isRestricted(update, context):
                message += "<b>Admin commands:</b>\n"
                message += " - /start your bot \n"
                message += " - /announce a message \n"
                message += " - /settings channels \n"
                message += " - Configuration /sites \n"
                message += " - /config bot \n"
                message += " - /restart this bot \n"
            message += "All commands available in this bot are show below \n"
        # Print all commands availables
        message += " - /info about OR \n"
        message += " - All /channels available \n"
        message += " - This /help \n"
        # update.message.reply_text(message, parse_mode='HTML')
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML')

    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)
# EOF

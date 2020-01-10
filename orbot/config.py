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

from uuid import uuid4
from functools import wraps
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
import logging
import json
# Menu 
from .utils import build_menu, check_key_id, isAdmin, filter_channel

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def restricted(func):
    @wraps(func)
    def wrapped(self, update, context):
        if self.channels.isRestricted(update, context):
            logger.info(f"Unauthorized access denied for {update.effective_user.id}.")
            update.message.reply_text("Unauthorized access denied.")
            return
        return func(self, update, context)
    return wrapped


def rtype(rtype):
    def group(func):
        @wraps(func)
        def wrapped(self, update, context):
            type_chat = self.channels.isAllowed(update, context)
            if [value for value in rtype if value in type_chat]:
                return func(self, update, context)
            logger.info(f"Unauthorized access denied for {update.effective_chat.type}.")
            context.bot.send_message(chat_id=update.effective_chat.id, text="Unauthorized access denied.")
            return
        return wrapped
    return group


def register(func):
    @wraps(func)
    def wrapped(self, update, context):
        # Register group
        self.channels.register_chat(update, context)
        return func(self, update, context)
    return wrapped


class Config:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Configuration
        dp.add_handler(CommandHandler("config", self.config))
        dp.add_handler(CallbackQueryHandler(self.config_save, pattern='CONF_SAVE'))
        dp.add_handler(CallbackQueryHandler(self.config_cancel, pattern='CONF_CANCEL'))
        dp.add_handler(CallbackQueryHandler(self.config_notify, pattern='CONF_NOTIFY'))

    @filter_channel
    @rtype(['private'])
    @restricted
    def config(self, update, context):
        """ Configuration bot """
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Make buttons
        buttons = [InlineKeyboardButton("Notifications " + ("🔊" if self.settings['config'].get('notify', True) else "🔇"),
                                        callback_data=f"CONF_NOTIFY {keyID}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"CONF_CANCEL {keyID}")))
        message = f"Configuration\n"
        for k, v in self.settings['config'].items():
            message += f" - {k}={v}\n"
        context.bot.send_message(chat_id=update.effective_user.id, text=message, parse_mode='HTML', reply_markup=reply_markup)
        # Store value
        context.user_data[keyID] = {} 

    @check_key_id('Error message')
    def config_save(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # Add chat id in user data
        message = f"Stored\n"
        for n in range(2, len(data)):
            var = data[n]
            name, value = var.split('=')
            message += f" - {name}={value}\n"
            if value == "True":
                value = True
            elif value == "False":
                value = False
            self.settings['config'][name] = value
        # remove key from user_data list
        del context.user_data[keyID]
        # Save to CSV file
        with open(self.settings_file, 'w') as fp:
            json.dump(self.settings, fp)
        # edit message
        query.edit_message_text(text=message)

    @check_key_id('Error message')
    def config_cancel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        message = f"Abort"
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=message)

    @check_key_id('Error message')
    def config_notify(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # Make buttons
        buttons = [InlineKeyboardButton("🔊 Enable" + (" [X]" if self.settings['config'].get('notify', True) else ""),
                                        callback_data=f"CONF_SAVE {keyID} notify=True"),
                   InlineKeyboardButton("🔇 Disable" + ("" if self.settings['config'].get('notify', True) else " [X]"),
                                        callback_data=f"CONF_SAVE {keyID} notify=False")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
        message = f"🔈 Notifications"
        # edit message
        query.edit_message_text(text=message, parse_mode='HTML', reply_markup=reply_markup)
# EOF

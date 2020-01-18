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
from .utils import build_menu, check_key_id, isAdmin, filter_channel, restricted, rtype, save_config
from .channels import Channels

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class Config:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Initialize config if empty
        if 'config' not in self.settings:
            self.settings['config'] = {}
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Configuration
        dp.add_handler(CommandHandler("config", self.config))
        dp.add_handler(CallbackQueryHandler(self.config_save, pattern='C_SAVE'))
        dp.add_handler(CallbackQueryHandler(self.config_cancel, pattern='C_CANCEL'))
        dp.add_handler(CallbackQueryHandler(self.config_notify, pattern='C_NOTIFY'))
        dp.add_handler(CallbackQueryHandler(self.config_inline, pattern='C_INLINE'))
        dp.add_handler(CallbackQueryHandler(self.config_def_channel, pattern='C_DEF_CHANNEL'))

    def makeMessage(self, context):
        message = ["Notifications " + ("🔊" if self.settings['config'].get('notify', True) else "🔇")]
        def_ch = self.settings['config'].get('dch', None)
        if def_ch is not None:
            def_ch = context.bot.getChat(def_ch).title
        else:
            def_ch = "None"
        message += ["Default channel: " + def_ch]
        type_chat = Channels.TYPE[self.settings['config'].get('inline', '0')]
        message += ["Inline hide: " + type_chat['name'] + " " + (type_chat.get('icon', '👥'))]
        return message

    @filter_channel
    @rtype(['private'])
    @restricted
    def config(self, update, context):
        """ Configuration bot """
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Make buttons
        message = self.makeMessage(context)
        buttons = [InlineKeyboardButton(message[0], callback_data=f"C_NOTIFY {keyID}"),
                   InlineKeyboardButton(message[1], callback_data=f"C_DEF_CHANNEL {keyID}"),
                   InlineKeyboardButton(message[2], callback_data=f"C_INLINE {keyID}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"C_CANCEL {keyID}")))
        message = f"Configuration"
        # for k, v in self.settings['config'].items():
        #    message += f"\n - {k}={v}"
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
        for n in range(2, len(data)):
            var = data[n]
            name, value = var.split('=')
            if value == "True":
                value = True
            elif value == "False":
                value = False
            elif value == "None":
                value = None
            self.settings['config'][name] = value
        # Make the message
        message = self.makeMessage(context)
        # remove key from user_data list
        del context.user_data[keyID]
        # Save to CSV file
        save_config(self.settings_file, self.settings)
        # edit message
        query.edit_message_text(text="<b>Stored!</b>\n" + "\n".join(message), parse_mode='HTML')

    @check_key_id('Error message')
    def config_cancel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        message = self.makeMessage(context)
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text="<b>Abort</b>\n" + "\n".join(message), parse_mode='HTML')

    @check_key_id('Error message')
    def config_notify(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # Make buttons
        buttons = [InlineKeyboardButton("🔊 Enable" + (" [X]" if self.settings['config'].get('notify', True) else ""),
                                        callback_data=f"C_SAVE {keyID} notify=True"),
                   InlineKeyboardButton("🔇 Disable" + ("" if self.settings['config'].get('notify', True) else " [X]"),
                                        callback_data=f"C_SAVE {keyID} notify=False")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
        message = f"🔈 Notifications"
        # edit message
        query.edit_message_text(text=message, parse_mode='HTML', reply_markup=reply_markup)

    @check_key_id('Error message')
    def config_inline(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # Make buttons
        buttons = []
        level = int(self.settings['config'].get('inline', '0'))
        for typech in Channels.TYPE:
            icon = Channels.TYPE[typech].get('icon', '')
            if icon:
                icon = f"[{icon}] - "
            check = " [X]" if level == int(typech) else ""
            buttons += [InlineKeyboardButton(icon + Channels.TYPE[typech]['name'] + check, callback_data=f"C_SAVE {keyID} inline={typech}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1))
        message = f"👥 inline hide level"
        # edit message
        query.edit_message_text(text=message, parse_mode='HTML', reply_markup=reply_markup)

    @check_key_id('Error message')
    def config_def_channel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # List of channels
        buttons = []
        def_ch = self.settings['config'].get('dch', None)
        for chat_id in self.settings['channels']:
            chat = context.bot.getChat(chat_id)
            if chat.type == 'channel':
                icons = self.channels.getIcons(context, chat_id)
                isSelected = " [X]" if def_ch == chat_id else ""
                buttons += [InlineKeyboardButton(icons + chat.title + isSelected,
                                                  callback_data=f"C_SAVE {keyID} dch={chat_id}")]
        # Footer button
        footer_button = InlineKeyboardButton("None" + (" [X]" if def_ch is None else ""),
                                             callback_data=f"C_SAVE {keyID} dch=None")
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1,
                                            footer_buttons=footer_button))
        message = f"Select the default channel:"
        # edit message
        query.edit_message_text(text=message, parse_mode='HTML', reply_markup=reply_markup)
# EOF

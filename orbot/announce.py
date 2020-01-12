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
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
import logging
# Menu 
from .utils import build_menu, check_key_id, isAdmin, filter_channel, restricted, rtype

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


class Announce:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        dp.add_handler(CommandHandler('announce', self.announce))
        dp.add_handler(CallbackQueryHandler(self.announce_select, pattern='AN_SELECT'))
        dp.add_handler(CallbackQueryHandler(self.announce_send, pattern='AN_SEND'))
        dp.add_handler(CallbackQueryHandler(self.announce_cancel, pattern='AN_CANCEL'))

    @filter_channel
    @rtype(['private', 'channel'])
    def announce(self, update, context):
        chat_id = update.effective_chat.id
        #text = update.message.text
        if not self.channels.isAdmin(update, context):
            context.bot.send_message(chat_id=chat_id, text="You are not admin of this chat, you cannot announce messages", parse_mode='Markdown')
            return
        message = ""
        if update.message.reply_to_message is not None:
            message = update.message.reply_to_message.text
        if context.args:
            message = " ".join(context.args)
        if not message:
            context.bot.send_message(chat_id=chat_id, text="Format command:\n/announce [message]", parse_mode='Markdown')
            return
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Store value
        context.user_data[keyID] = {'message': message, 'main_chat': chat_id}
        # Send a message to the admin user
        buttons = []
        for chat_id in self.settings['channels']:
            chat = context.bot.getChat(chat_id)
            if chat.type == 'channel':
                icons = self.channels.getIcons(context, chat_id)
                buttons += [InlineKeyboardButton(icons + chat.title, callback_data=f"AN_SELECT {keyID} {chat_id}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"AN_CANCEL {keyID}")))
        message = f"Message to announce:\n{context.user_data[keyID]['message']}"
        try:
            context.bot.send_message(chat_id=update.effective_user.id, text=message, parse_mode='Markdown', reply_markup=reply_markup)
        except TelegramError:
            context.bot.send_message(chat_id=update.effective_user.id, text=message, reply_markup=reply_markup)


    @check_key_id('Error message')
    def announce_select(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        message = context.user_data[keyID]['message']
        # Store the type of message to announce
        context.user_data[keyID]['chat_id'] = data[2]
        # Second message ask
        buttons = [InlineKeyboardButton("📢 Announce", callback_data=f"AN_SEND {keyID}"),
                   InlineKeyboardButton("📢 Announce & 📌 Pin", callback_data=f"AN_SEND {keyID} PIN")]
        # Only for admin in admin groups
        if not self.channels.isRestricted(update, context):
            n_channels = len(self.settings['channels'])
            buttons += [InlineKeyboardButton(f"📢📢📢 Announce in *all* {n_channels} channels", callback_data=f"AN_SEND {keyID} ALL", parse_mode='Markdown')]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2,
                                            footer_buttons=InlineKeyboardButton("🚫 Abort", callback_data=f"AN_CANCEL {keyID}")))
        # Extract chat id
        chat_id = context.user_data[keyID]['chat_id']
        chat = context.bot.getChat(chat_id)
        try:
            query.edit_message_text(text=f"*Announce* {chat.title}:\n{message}", reply_markup=reply_markup, parse_mode='Markdown')
        except TelegramError:
            query.edit_message_text(text=f"Announce {chat.title}:\n{message}", reply_markup=reply_markup)

    def sendAnnounce(self, update, context, chat_id):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        message = context.user_data[keyID]['message']
        pin_message = False
        if len(data) > 2:
            if data[2] == 'PIN':
                pin_message = True
        #Send message
        try:
            msg = context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown', disable_notification=True)
        except TelegramError:
            msg = context.bot.send_message(chat_id=chat_id, text=message, disable_notification=True)
        if pin_message:
            # Notify message
            context.bot.pinChatMessage(chat_id=chat_id, message_id=msg.message_id, disable_notification=False)
        return msg

    @check_key_id('Error message')
    def announce_send(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # Send to channel
        chat_id = context.user_data[keyID]['chat_id']
        main_chat = context.user_data[keyID]['main_chat']
        chat = context.bot.getChat(chat_id)
        #Send message
        msg = self.sendAnnounce(update, context, chat_id)
        context.bot.forward_message(chat_id=main_chat, from_chat_id=chat_id, message_id=msg.message_id)
        # Check forward in all chats
        all = False
        if len(data) > 2:
            if data[2] == 'ALL':
                all = True
        if all:
            logger.info(f"Send in all chats")
            for n_chat_id in [value for value in self.settings['channels'] if value not in [chat_id, main_chat]]:
                context.bot.forward_message(chat_id=n_chat_id, from_chat_id=chat_id, message_id=msg.message_id)
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"*Announce* {chat.title} Sent!", parse_mode='Markdown')

    @check_key_id('Error message')
    def announce_cancel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"Abort")
# EOF

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


from os import path
import json
import logging
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import csv
from functools import wraps

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
# Offset flags
OFFSET = 127462 - ord('A')

def hasNumbers(inputString):
    return any(char.isdigit() for char in inputString)

def saveFile(csv_file, dict_data):
    csv_columns = ['No','Name','Country']
    try:
        with open(csv_file, 'w') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            writer.writeheader()
            for data in dict_data:
                writer.writerow(data)
    except IOError:
        print("I/O error")

def flag(code):
    code = code.upper()
    return chr(ord(code[0]) + OFFSET) + chr(ord(code[1]) + OFFSET)


def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, [header_buttons])
    if footer_buttons:
        menu.append([footer_buttons])
    return menu


def isAdmin(context, chat_id):
    for member in context.bot.getChatAdministrators(chat_id):
        if member.user.username == context.bot.username:
            return True
    return False

def register(func):
    @wraps(func)
    def wrapped(self, update, context, *args, **kwargs):
        type_chat = update.effective_chat.type
        chat_id = update.effective_chat.id
        if type_chat == 'group':
            for ch in self.channels:
                if ch['id'] == chat_id:
                    return func(self, update, context, *args, **kwargs)
            if chat_id not in self.groups:
                self.groups[chat_id] = {'title': update.effective_chat.title}
        return func(self, update, context, *args, **kwargs)
    return wrapped


def restricted(func):
    @wraps(func)
    def wrapped(self, update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in self.LIST_OF_ADMINS:
            logger.info(f"Unauthorized access denied for {user_id}.")
            update.message.reply_text("Unauthorized access denied.")
            return
        return func(self, update, context, *args, **kwargs)
    return wrapped


def rtype(rtype):
    def group(func):
        @wraps(func)
        def wrapped(self, update, context, *args, **kwargs):
            type_chat = update.effective_chat.type
            if type_chat == rtype:
                return func(self, update, context, *args, **kwargs)
            else:
                logger.info(f"Unauthorized access denied for {type_chat}.")
                context.bot.send_message(chat_id=update.effective_chat.id, text="Unauthorized access denied.")
                return
        return wrapped
    return group


class ORbot:

    def __init__(self, settings):
        # List of admins
        self.LIST_OF_ADMINS = settings['admins']
        # Load settings
        self.channels = []
        channels_file = settings.get('channels', 'config/channels.json')
        if path.exists(channels_file):
            with open(channels_file) as stream:
                self.channels = json.load(stream)
        # Create the Updater and pass it your bot's token.
        # Make sure to set use_context=True to use the new context based callbacks
        # Post version 12 this will no longer be necessary
        self.updater = Updater(settings['token'], use_context=True)
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Add commands
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("help", self.help))
        dp.add_handler(CommandHandler("channels", self.cmd_channels))
        dp.add_handler(CallbackQueryHandler(self.bb_groups, pattern='GR'))
        dp.add_handler(CommandHandler("settings", self.cmd_groups))
        # Unknown handler
        unknown_handler = MessageHandler(Filters.command, self.unknown)
        dp.add_handler(unknown_handler)
        # Add group handle
        add_group_handle = MessageHandler(Filters.status_update.new_chat_members, self.add_group)
        dp.add_handler(add_group_handle)
        # log all errors
        dp.add_error_handler(self.error)
        # Allow chats
        self.groups = {}

    def runner(self):
        # Start the Bot
        self.updater.start_polling()
        # Run the bot until you press Ctrl-C or the process receives SIGINT,
        # SIGTERM or SIGABRT. This should be used most of the time, since
        # start_polling() is non-blocking and will stop the bot gracefully.
        self.updater.idle()

    def unknown(self, update, context):
        context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")

    def add_group(self, update, context):
        for member in update.message.new_chat_members:
            context.bot.send_message(chat_id=update.effective_chat.id, text=f"{member.username} add group")

    @restricted
    @rtype('private')
    def cmd_groups(self, update, context):
        """ Bot manager """
        chat_id = update.effective_chat.id
        buttons = []
        for name in self.groups:
            title = self.groups[name]['title']
            buttons += [InlineKeyboardButton(title, callback_data=f"GR DATA {name}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1))
        message = 'List of new groups:' if buttons else 'No new groups'
        context.bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML', reply_markup=reply_markup)

    def bb_groups(self, update, context):
        query = update.callback_query
        data = query.data.split()
        chat_id = int(data[2])
        if chat_id in self.groups:
            name = self.groups[chat_id]['title']
            if data[1] == 'DATA':
                if isAdmin(context, chat_id):
                    buttons = [InlineKeyboardButton("Save", callback_data=f"GR SAVE {data[2]}"),
                            InlineKeyboardButton("Remove", callback_data=f"GR REMOVE {data[2]}")]
                    reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
                    query.edit_message_text(text=f"{name}", reply_markup=reply_markup)
                else:
                    query.edit_message_text(text=f"{name} Require admin")
            elif data[1] == "SAVE":
                group = self.groups[chat_id]
                # Add in channels
                self.channels += [{'title': group['title'],
                                   'id': chat_id,
                                   'link': context.bot.exportChatInviteLink(chat_id)}]
                # Remove from groups list
                del self.groups[chat_id]
                # edit message
                query.edit_message_text(text=f"{name} Saved")
            else:
                # Remove from groups list
                del self.groups[chat_id]
                # edit message
                query.edit_message_text(text=f"{name} Removed")
        else:
            query.edit_message_text(text="Error")

    @register
    def start(self, update, context):
        """ Start ORbot """
        user = update.message.from_user
        logger.info(f"New user join {user['first_name']}")
        message = 'Welcome to ORbot'
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML')

    @register
    @rtype('group')
    def cmd_channels(self, update, context):
        """ List all channels availables """
        message = "All channels availables are:\n"
        for channel in self.channels:
            name = channel['title']
            link = channel.get('link', '#')
            # Make flag lang
            lang = flag(channel.get('lang', 'ita'))
            message += f" - {lang} <a href='{link}'>{name}</a>\n"
        # Send message with reply in group
        # update.message.reply_text(message, parse_mode='HTML')
        # Send message without reply in group
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML')

    def help(self, update, context):
        """ Help list of all commands """
        message = "All commands available in this bot are show below \n"
        message += " - /start Start your bot \n"
        message += " - /channels All channels \n"
        message += " - /help This help \n"
        # update.message.reply_text(message, parse_mode='HTML')
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML')

    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)

# EOF

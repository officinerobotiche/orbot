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
from uuid import uuid4
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
import logging
# Menu 
from .utils import build_menu, check_key_id, isAdmin, filter_channel, restricted

from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSING, EDIT = range(2)


class Sites:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Initialize sites if empty
        if 'sites' not in self.settings:
            self.settings['sites'] = {}
        # self serving keyID
        self.keyID = None
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Add site conversation
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('sites', self.start)],
            states={
                CHOOSING: [CallbackQueryHandler(self.choosing, pattern='SITE_CHOOSING'),
                           MessageHandler(Filters.text, self.typing)],
                EDIT: [CallbackQueryHandler(self.edit, pattern='SITE_EDIT')],
            },
            fallbacks=[CallbackQueryHandler(self.cancel, pattern='SITE_CANCEL'),
                       CallbackQueryHandler(self.store, pattern='SITE_STORE'),
                       CallbackQueryHandler(self.remove, pattern='SITE_REMOVE')],
            per_message=False
        )
        dp.add_handler(conv_handler)
        # self counter
        self.counter = 0

    def start(self, update, context):
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        buttons = [InlineKeyboardButton(title, callback_data=f"SITE_CHOOSING {keyID} {title}") for title in self.settings['sites']]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1,
                                                       header_buttons=InlineKeyboardButton("New site", callback_data=f"SITE_CHOOSING {keyID}"),
                                                       footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"SITE_CANCEL {keyID}")))
        context.user_data[keyID] = {}
        # Init message
        message = "All sites:" if self.settings['sites'] else 'No sites'
        # Send message without reply in group
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML', reply_markup=reply_markup)
        return CHOOSING

    @check_key_id('Error message')
    def choosing(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        if len(data) > 2:
            title = " ".join(data[2:])
            link = self.settings['sites'][title]
            context.user_data[keyID]['title'] = title
            context.user_data[keyID]['link'] = link
            context.user_data[keyID]['old_title'] = title
        message = "Select your option\n"
        message += f"title={context.user_data[keyID].get('title', '')}\n"
        message += f"link={context.user_data[keyID].get('link', '')}"
        # edit message
        query.edit_message_text(text=message, parse_mode='HTML', reply_markup=self.edit_line(context, keyID))
        return EDIT
    
    def edit_line(self, context, keyID):
        # Buttons title and link
        buttons = [InlineKeyboardButton("Title", callback_data=f"SITE_EDIT {keyID} title"),
                   InlineKeyboardButton("🔗 Link", callback_data=f"SITE_EDIT {keyID} link"),
                   InlineKeyboardButton("🗂 Store", callback_data=f"SITE_STORE {keyID}")]
        if 'old_title' in context.user_data[keyID]:
                   buttons += [InlineKeyboardButton("🧹 Remove", callback_data=f"SITE_REMOVE {keyID}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"SITE_CANCEL {keyID}")))
        return reply_markup

    def typing(self, update, context):
        # Read keyID
        keyID = self.keyID
        # Clean keyID value
        self.keyID = None
        self.counter = 0
        # Read state
        state = context.user_data[keyID]['state']
        # Set value
        context.user_data[keyID][state] = update.message.text
        # Make message
        message = f"title={context.user_data[keyID].get('title', '')}\n"
        message += f"link={context.user_data[keyID].get('link', '')}"
        # edit message
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, reply_markup=self.edit_line(context, keyID))
        return EDIT

    @check_key_id('Error message')
    def edit(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        # Store keyID serving
        #if self.keyID is not None:
        #    query.edit_message_text(text=f"I can't service, another user edit a site", parse_mode='HTML')
        #    return ConversationHandler.END
        self.keyID = keyID
        # Set status
        state = data[2]
        context.user_data[keyID]['state'] = state
        if state in context.user_data[keyID]:
            value = f"\nnow={context.user_data[keyID][state]}"
        else:
            value = ""
        # edit message
        reply_markup = InlineKeyboardMarkup(build_menu([InlineKeyboardButton("Undo", callback_data=f"SITE_CHOOSING {keyID}")], 1))
        query.edit_message_text(text=f"Write *{state}* or press undo{value}", parse_mode='Markdown', reply_markup=reply_markup)
        return CHOOSING

    @check_key_id('Error message')
    def cancel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        self.keyID = None
        self.counter = 0
        message = f"Abort"
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=message)
        return ConversationHandler.END

    @check_key_id('Error message')
    def remove(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        self.keyID = None
        self.counter = 0
        # Extract title
        title = context.user_data[keyID]['old_title']
        # Remove from list
        del self.settings['sites'][title]
        # Save to CSV file
        with open(self.settings_file, 'w') as fp:
            json.dump(self.settings, fp)
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"Removed")
        return ConversationHandler.END

    @check_key_id('Error message')
    def store(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        self.keyID = None
        # Add info title
        if 'title' not in context.user_data[keyID] or 'link' not in context.user_data[keyID]:
            self.counter += 1
            query.edit_message_text(text=f"Require a title and link before to store! ({self.counter})", reply_markup=self.edit_line(context, keyID))
            return EDIT
        # Remove old title
        if 'old_title' in context.user_data[keyID]:
            # Extract title
            title = context.user_data[keyID]['old_title']
            # Remove from list
            del self.settings['sites'][title]
        # Extract title
        title = context.user_data[keyID]['title']
        link = context.user_data[keyID]['link']
        self.settings['sites'][title] = link
        # Save to CSV file
        with open(self.settings_file, 'w') as fp:
            json.dump(self.settings, fp)
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"Stored!\n{title}\n{link}")
        return ConversationHandler.END
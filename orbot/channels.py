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
import logging
from functools import wraps
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler, InlineQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
from telegram import InlineQueryResultArticle, ParseMode, InputTextMessageContent, InlineQueryResultCachedPhoto, InlineQueryResultPhoto
from telegram.utils.helpers import escape_markdown

# Menu 
from .utils import build_menu, check_key_id, isAdmin, filter_channel, save_config

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def restricted(func):
    @wraps(func)
    def wrapped(self, update, context):
        if self.isRestricted(update, context):
            logger.info(f"Unauthorized access denied for {update.effective_user.id}.")
            context.bot.send_message(chat_id=update.effective_chat.id, text="Unauthorized access denied.")
            return
        return func(self, update, context)
    return wrapped


def rtype(rtype):
    def group(func):
        @wraps(func)
        def wrapped(self, update, context):
            type_chat = self.isAllowed(update, context)
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
        self.register_chat(update, context)
        return func(self, update, context)
    return wrapped


class Channels:

    TYPE = {"-10": {'name': "Administration", 'icon': '🔐'},
            "-1": {'name': "Hidden", 'icon': '🕶'},
            "0": {'name': "Private"},
            "10": {'name': "Public", 'icon': '💬'}
            }

    def __init__(self, updater, settings, settings_file):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        # Initialize channels if empty
        if 'channels' not in self.settings:
            self.settings['channels'] = {}
        # Extract list of admins
        telegram = self.settings['telegram']
        self.LIST_OF_ADMINS = telegram['admins']
        # Allow chats
        self.groups = []
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        #Setup handlers
        dp.add_handler(CommandHandler("channels", self.cmd_channels))
        dp.add_handler(CommandHandler("settings", self.ch_list))
        dp.add_handler(CallbackQueryHandler(self.ch_edit, pattern='CH_EDIT'))
        dp.add_handler(CallbackQueryHandler(self.ch_type, pattern='CH_TYPE'))
        dp.add_handler(CallbackQueryHandler(self.ch_admin, pattern='CH_ADMIN'))
        dp.add_handler(CallbackQueryHandler(self.ch_save, pattern='CH_SAVE'))
        dp.add_handler(CallbackQueryHandler(self.ch_remove, pattern='CH_REMOVE'))
        dp.add_handler(CallbackQueryHandler(self.ch_notify, pattern='CH_NOTIFY'))
        dp.add_handler(CallbackQueryHandler(self.ch_link, pattern='CH_LINK'))
        dp.add_handler(CallbackQueryHandler(self.ch_beta, pattern='CH_BETA'))
        dp.add_handler(CallbackQueryHandler(self.ch_cancel, pattern='CH_CANCEL'))
        # on noncommand i.e message - echo the message on Telegram
        dp.add_handler(InlineQueryHandler(self.inlinequery))

    def register_chat(self, update, context):
        type_chat = update.effective_chat.type
        chat_id = update.effective_chat.id
        if type_chat in ['group', 'supergroup', 'channel']:
            if chat_id not in self.groups and str(chat_id) not in self.settings['channels']:
                self.groups += [chat_id]

    def isRestricted(self, update, context):
        if update.effective_user.id in self.LIST_OF_ADMINS:
            return False
        for chat_id in self.settings['channels']:
            username = update.message.from_user.username
            if self.settings['channels'][chat_id].get('admin', False):
                if isAdmin(update, context, username, chat_id=int(chat_id)):
                    return False
        return True

    def isAdmin(self, update, context):
        if update.effective_user.id in self.LIST_OF_ADMINS:
            return True
        for chat_id in self.settings['channels']:
            username = update.message.from_user.username
            if isAdmin(update, context, username, chat_id=int(chat_id)):
                return True
        return False

    def isAllowed(self, update, context):
        type_chat = []
        chat = context.bot.getChat(update.effective_chat.id)
        if chat.type == 'private':
            type_chat += [chat.type]
        if str(update.effective_chat.id) in self.settings['channels']:
            type_chat += ['channel']
            if self.settings['channels'][str(update.effective_chat.id)].get('admin', False):
                type_chat += ['ch_admin']
        if len(self.isMember(context, update.effective_user.id)) > 0:
            type_chat += ['member']
        return type_chat

    def isMember(self, context, user_id):
        chat_member = []
        for chat_id in self.settings['channels']:
            try:
                chat = context.bot.get_chat_member(chat_id, user_id)
                if chat.status not in ['left', 'kicked']:
                    chat_member +=[int(chat_id)]
            except TelegramError:
                pass
        return chat_member

    def getLevel(self, context, user_id):
        level = 0
        for chat_id in self.settings['channels']:
            try:
                _ = context.bot.get_chat_member(chat_id, int(user_id))
                level_ch = int(self.settings['channels'][chat_id].get('type', "0"))
                level = level_ch if level_ch <= level else level
            except TelegramError:
                pass
        return level

    def inlinequery(self, update, context):
        """Handle the inline query."""
        query = update.inline_query.query
        # extract level user
        local_chat_id = str(update.effective_user.id)
        local_level = self.getLevel(context, local_chat_id)
        # Sort channels
        channels = sorted(self.settings['channels'].items(), key=lambda kv:(context.bot.getChat(kv[0]).title, kv[1]))
        # If there is a query filter the channels
        if query:
            filtered_dict = {k:v for (k,v) in channels if query.lower() in context.bot.getChat(k).title.lower()}
        else:
            filtered_dict = channels
        # Minimum configuration level
        min_level = int(self.settings['config'].get('inline', '-10'))
        # Make articles list
        articles = []
        for chat_id, data in filtered_dict:
            chat = context.bot.getChat(chat_id)
            link = chat.invite_link
            level = int(data.get('type', "0"))
            # Update link
            if isAdmin(update, context, context.bot.username, chat_id=chat_id):
                # If None generate a link
                if link is None:
                    link = context.bot.exportChatInviteLink(chat_id)
            # Show only enable channels
            if local_level <= level and level >= min_level and link is not None:
                # Load icon type channel
                icon_string = self.getIcons(context, chat_id)
                # Check if this group can see other group with same level
                button = [InlineKeyboardButton(icon_string + chat.title, url=link)]
                # Does not work !!!
                #if chat.photo:
                #    file_id = chat.photo.small_file_id
                #    newFile = context.bot.getFile(file_id)
                #    thumb_url = newFile.file_path
                #    articles += [InlineQueryResultCachedPhoto(id=uuid4(), title=chat.title, photo_file_id=file_id)
                thumb_url = None
                text = f"*{chat.title}*"
                if chat.description:
                    text += f"\n{chat.description}"
                # https://github.com/python-telegram-bot/python-telegram-bot/blob/master/telegram/inline/inlinequeryresultarticle.py
                articles += [InlineQueryResultArticle(id=uuid4(), title=icon_string + chat.title,
                                                      input_message_content=InputTextMessageContent(text, parse_mode='Markdown'),
                                                      url=link,
                                                      thumb_url=thumb_url,
                                                      description=chat.description,
                                                      reply_markup=InlineKeyboardMarkup(build_menu(button, 1)))]
        # Update inline query
        update.inline_query.answer(articles, cache_time=10)

    def getChannels(self, update, context):
        buttons = []
        local_chat_id = str(update.effective_chat.id)
        if local_chat_id in self.settings['channels']:
            local_chat = context.bot.getChat(local_chat_id)
            local_level = int(self.settings['channels'][local_chat_id].get('type', "0"))
            logger.debug(f"{local_chat.title} = {local_level}")
        else:
            local_level = self.getLevel(context, local_chat_id)
        # Sort channels
        channels = sorted(self.settings['channels'].items(), key=lambda kv:(context.bot.getChat(kv[0]).title, kv[1]))
        for chat_id, data in channels:
            chat = context.bot.getChat(chat_id)
            name = chat.title
            link = chat.invite_link
            level = int(data.get('type', "0"))
            if isAdmin(update, context, context.bot.username, chat_id=chat_id):
                # If None generate a link
                if link is None:
                    link = context.bot.exportChatInviteLink(chat_id)
            # Make flag lang
            # slang = flag(channel.get('lang', 'ita'))
            is_admin = ' (Bot not Admin)' if not isAdmin(update, context, context.bot.username, chat_id=chat_id) else ''
            # Load icon type channel
            icon_string = self.getIcons(context, chat_id)
            # Check if this group can see other group with same level
            if local_level <= level and link is not None:
                buttons += [InlineKeyboardButton(icon_string + name + is_admin, url=link)]
        return InlineKeyboardMarkup(build_menu(buttons, 1))

    @register
    @filter_channel
    @rtype(['channel', 'member'])
    def cmd_channels(self, update, context):
        """ List all channels availables """
        reply_markup = self.getChannels(update, context)
        message = "All channels available are:" if self.settings['channels'] else 'No channels available'
        # Send message without reply in group
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML', reply_markup=reply_markup)

    def getIcons(self, context, chat_id):
        chat = context.bot.getChat(chat_id)
        level = self.settings['channels'][chat_id].get('type', "0")
        admin = self.settings['channels'][chat_id].get('admin', False)
        beta = self.settings['channels'][chat_id].get('beta', False)
        icons = []
        icons = icons + ['📢'] if chat.type == 'channel' else icons
        icon_type = Channels.TYPE[level].get('icon', '')
        if chat.type != 'channel':
            icons = icons + [icon_type] if icon_type else icons
        icons = icons + ['👑'] if admin else icons
        icons = icons + ['🅱️'] if beta else icons
        if icons:
            return f"[" + ",".join(icons) + "] "
        return ""

    @filter_channel
    @restricted
    def ch_list(self, update, context):
        """ Bot manager """
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Extract chat id
        buttons = []
        # Sort channels
        channels = sorted(self.settings['channels'].items(), key=lambda kv:(context.bot.getChat(kv[0]).title, kv[1]))
        for chat_id, _ in channels:
            chat = context.bot.getChat(chat_id)
            title = chat.title
            # Load icon type channel
            icon_string = self.getIcons(context, chat_id)
            buttons += [InlineKeyboardButton(icon_string + title, callback_data=f"CH_EDIT {keyID} id={chat_id}")]
        for chat_id in self.groups:
            chat = context.bot.getChat(chat_id)
            title = chat.title
            isChannel = '📢' if chat.type == 'channel' else ''
            buttons += [InlineKeyboardButton(f"[{isChannel}NEW!] " + title, callback_data=f"CH_EDIT {keyID} id={chat_id}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"CH_CANCEL {keyID}")))
        message = 'List of channels:' if buttons else 'No channels'
        context.bot.send_message(chat_id=update.effective_user.id, text=message, parse_mode='HTML', reply_markup=reply_markup)
        # Store value
        context.user_data[keyID] = {}

    @check_key_id('Error message')
    def ch_edit(self, update, context):
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
            context.user_data[keyID][name] = value
        # Read chat_id
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        # Populate configuration
        if chat_id in self.settings['channels']:
            for k, v in self.settings['channels'][chat_id].items():
                if k not in context.user_data[keyID]:
                    context.user_data[keyID][k] = v
        # If this chat is a channel force to be high level
        if chat.type == 'channel':
            context.user_data[keyID]['type'] = "10"
        # Make buttons
        type_chat = Channels.TYPE[context.user_data[keyID].get('type', "0")]
        buttons = []
        if chat.type != 'channel':
            buttons += [InlineKeyboardButton(type_chat.get('icon', '👥') + " Type",
                                             callback_data=f"CH_TYPE {keyID}"),
                        InlineKeyboardButton(("✅" if context.user_data[keyID].get('admin', False) else "❌") + " Admin",
                                             callback_data=f"CH_ADMIN {keyID}")]
        buttons += [InlineKeyboardButton("🔈 Notify",
                                        callback_data=f"CH_NOTIFY {keyID}"),
                   InlineKeyboardButton("🔗 Gen new link",
                                        callback_data=f"CH_LINK {keyID}"),
                   InlineKeyboardButton("🗂 Store",
                                        callback_data=f"CH_SAVE {keyID}"),
                   InlineKeyboardButton("🧹 Remove",
                                        callback_data=f"CH_REMOVE {keyID}")]
        if chat.type != 'channel':
            buttons += [InlineKeyboardButton(("✅" if context.user_data[keyID].get('beta', False) else "❌") + " 🅱️eta",
                                             callback_data=f"CH_BETA {keyID}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"CH_CANCEL {keyID}")))
        # Make message
        message = f"{chat.title}\n"
        message += f"{chat.invite_link}\n" if chat.invite_link is not None else "Link not available!\n"
        for k, v in context.user_data[keyID].items():
            if k == 'type':
                v = Channels.TYPE[v]['name']
            message += f" - {k}={v}\n"
        query.edit_message_text(text=message, reply_markup=reply_markup)

    @check_key_id('Error message')
    def ch_link(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        # remove key from user_data list
        del context.user_data[keyID]
        # generate chat link
        if isAdmin(update, context, context.bot.username, chat_id=chat_id):
            link = context.bot.exportChatInviteLink(chat_id)
            # edit message
            query.edit_message_text(text=f"{chat.title} Link generated:\n{link}")
        else:
            # edit message
            query.edit_message_text(text=f"{chat.title} Require bot Admin!")

    @check_key_id('Error message')
    def ch_type(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        title = context.bot.getChat(chat_id).title
        # Make buttons
        buttons = []
        if 'type' in context.user_data[keyID]:
            level = int(context.user_data[keyID]['type'])
        elif chat_id in self.settings['channels']:
            level = int(self.settings['channels'][chat_id].get('type', "0"))
        else:
            level = 0
        for typech in Channels.TYPE:
            icon = Channels.TYPE[typech].get('icon', '')
            if icon:
                icon = f"[{icon}] - "
            check = " [X]" if level == int(typech) else ""
            buttons += [InlineKeyboardButton(icon + Channels.TYPE[typech]['name'] + check, callback_data=f"CH_EDIT {keyID} type={typech}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1))
        query.edit_message_text(text=f"{title}", reply_markup=reply_markup)

    def notifyNewChat(self, update, context, chat_id):
        chat = context.bot.getChat(chat_id)
        name = chat.title
        link = chat.invite_link
        level = int(self.settings['channels'][chat_id].get('type', "0")) if chat_id in self.settings['channels'] else 0

        for l_chat_id in self.settings['channels']:
            l_level = int(self.settings['channels'][l_chat_id].get('type', "0"))
            l_chat = context.bot.getChat(l_chat_id)
            # Check if this group can see other group with same level
            logger.info(f"level {chat.title}={level}, {l_chat_id}={l_level}")
            if l_chat_id == str(chat_id):
                # Send local message only if not a channel
                if l_chat.type != 'channel':
                    context.bot.send_message(chat_id=l_chat_id, text=f"Hi! I'm activate")
            else:
                if l_level <= level and link is not None:
                    reply_markup = InlineKeyboardMarkup(build_menu([InlineKeyboardButton(name, url=link)], 1))
                    context.bot.send_message(chat_id=l_chat_id, text=f"New channel:", reply_markup=reply_markup)

    @check_key_id('Error message')
    def ch_notify(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        if len(data) > 2:
            if data[2] == 'True':
                # Notify new chat in all chats
                self.notifyNewChat(update, context, chat_id)
                # edit message
                query.edit_message_text(text=f"{chat.title} Notification sent!")
            # remove key from user_data list
            del context.user_data[keyID]
        else:
            buttons = [InlineKeyboardButton("📩 SEND!", callback_data=f"CH_NOTIFY {keyID} True"),
                       InlineKeyboardButton("🚫 Abort", callback_data=f"CH_EDIT {keyID}")]
            reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
            query.edit_message_text(text=f"Send notifications of {chat.title} in all channels?", reply_markup=reply_markup)

    @check_key_id('Error message')
    def ch_admin(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        admin = context.user_data[keyID].get('admin', False)
        buttons = [InlineKeyboardButton("✅ Yes " + ("[X]" if admin else ""),
                                        callback_data=f"CH_EDIT {keyID} admin=True"),
                    InlineKeyboardButton("❌ No " + ("" if admin else "[X]"),
                                        callback_data=f"CH_EDIT {keyID} admin=False")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
        query.edit_message_text(text=f"Set {chat.title} administrator?", reply_markup=reply_markup)

    @check_key_id('Error message')
    def ch_beta(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        beta = context.user_data[keyID].get('beta', False)
        buttons = [InlineKeyboardButton("✅ Yes " + ("[X]" if beta else ""),
                                        callback_data=f"CH_EDIT {keyID} beta=True"),
                    InlineKeyboardButton("❌ No " + ("" if beta else "[X]"),
                                        callback_data=f"CH_EDIT {keyID} beta=False")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
        query.edit_message_text(text=f"Set {chat.title} beta?", reply_markup=reply_markup)

    @check_key_id('Error message')
    def ch_save(self, update, context):
        query = update.callback_query
        data = query.data.split()
        new_channel = False
        # Extract keyID, chat_id
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        # generate chat link
        if isAdmin(update, context, context.bot.username, chat_id=chat_id):
            # If None generate a link
            if chat.invite_link is None:
                context.bot.exportChatInviteLink(chat_id)
        # Add channel in list
        if str(chat_id) not in self.settings['channels']:
            self.settings['channels'][str(chat_id)] = {}
            new_channel = True
        # Notify if beta channel
        if 'beta' in context.user_data[keyID]:
            beta = context.user_data[keyID]['beta']
            old_beta = self.settings['channels'][str(chat_id)].get('beta', False)
            if beta and old_beta != beta:
                context.bot.send_message(chat_id=chat_id, text="[🅱️] This channel now is beta enabled!")
        # Update all variables
        for k, v in context.user_data[keyID].items():
            if k != 'id':
                self.settings['channels'][str(chat_id)][k] = v
        # Update channel setting
        if new_channel and self.settings['config'].get('notify', True):
            # Notify new chat in all chats
            self.notifyNewChat(update, context, chat_id)
        # Remove chat_id if in groups list
        if int(chat_id) in self.groups:
            # Remove from groups list
            self.groups.remove(int(chat_id))
        # Save to CSV file
        save_config(self.settings_file, self.settings)
        # Make message
        message = f"{chat.title} STORED!\n"
        for k, v in context.user_data[keyID].items():
            if k == 'type':
                v = Channels.TYPE[v]['name']
            message += f" - {k}={v}\n"
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=message)

    @check_key_id('Error message')
    def ch_remove(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        chat = context.bot.getChat(chat_id)
        # Update channel setting
        if str(chat_id) in self.settings['channels']:
            del self.settings['channels'][str(chat_id)]
        # Remove chat_id if in groups list
        if chat_id in self.groups:
            # Remove from groups list
            self.groups.remove(chat_id)
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"{chat.title} Removed")

    @check_key_id('Error message')
    def ch_cancel(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id
        keyID = data[1]
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"Abort")
# EOF

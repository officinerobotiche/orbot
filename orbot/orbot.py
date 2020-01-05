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
        if 'group' in type_chat:
            if chat_id not in self.groups and str(chat_id) not in self.settings['channels']:
                self.groups += [chat_id]
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
            if update.effective_chat.id in self.settings['channels'] or self.isMember(context, update.effective_user.id):
                return func(self, update, context, *args, **kwargs)
            else:
                logger.info(f"Unauthorized access denied for {type_chat}.")
                context.bot.send_message(chat_id=update.effective_chat.id, text="Unauthorized access denied.")
                return
        return wrapped
    return group


def check_key_id(message):
    def checkKeyID(func):
        @wraps(func)
        def wrapped(self, update, context):
            query = update.callback_query
            data = query.data.split()
            # Extract keyID and check
            keyID = data[1]
            if keyID not in context.user_data:
                query.edit_message_text(text=message, parse_mode='HTML')
                return ConversationHandler.END
            else:
                return func(self, update, context)
        return wrapped
    return checkKeyID


class ORbot:

    class BotException(Exception):
        pass

    TYPE = {"-10": "Administration",
            "-1": "Hidden",
            "0": "Private",
            "10": "Public"
            }

    def __init__(self, settings_file):
        # Load settings
        self.settings_file = settings_file
        try:
            with open(settings_file) as stream:
                self.settings = json.load(stream)
        except FileNotFoundError:
            raise ORbot.BotException(f"Setting file in {self.settings_file} not found")
        # Initialize channels if empty
        if 'channels' not in self.settings:
            self.settings['channels'] = {}
        # Initialize config if empty
        if 'config' not in self.settings:
            self.settings['config'] = {}
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
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Add commands
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("help", self.help))
        dp.add_handler(CommandHandler('restart', self.restart))
        dp.add_handler(CommandHandler("channels", self.cmd_channels))
        # Settings manager
        dp.add_handler(CommandHandler("settings", self.ch_list))
        dp.add_handler(CallbackQueryHandler(self.ch_edit, pattern='CH_EDIT'))
        dp.add_handler(CallbackQueryHandler(self.ch_type, pattern='CH_TYPE'))
        dp.add_handler(CallbackQueryHandler(self.ch_save, pattern='CH_SAVE'))
        dp.add_handler(CallbackQueryHandler(self.ch_remove, pattern='CH_REMOVE'))
        dp.add_handler(CallbackQueryHandler(self.ch_notify, pattern='CH_NOTIFY'))
        dp.add_handler(CallbackQueryHandler(self.ch_cancel, pattern='CH_CANCEL'))
        # Configuration
        dp.add_handler(CommandHandler("config", self.config))
        dp.add_handler(CallbackQueryHandler(self.config_save, pattern='CONF_SAVE'))
        dp.add_handler(CallbackQueryHandler(self.config_cancel, pattern='CONF_CANCEL'))
        dp.add_handler(CallbackQueryHandler(self.config_notify, pattern='CONF_NOTIFY'))
        # Unknown handler
        unknown_handler = MessageHandler(Filters.command, self.unknown)
        dp.add_handler(unknown_handler)
        # Add group handle
        add_group_handle = MessageHandler(Filters.status_update.new_chat_members, self.add_group)
        dp.add_handler(add_group_handle)
        # log all errors
        dp.add_error_handler(self.error)
        # Allow chats
        self.groups = []
        # Send a message to all admins when the system is started
        version = get_version()
        bot = Bot(token=telegram['token'])
        infobot = bot.get_me()
        logger.info(f"Bot: {infobot}")
        for user_chat_id in self.LIST_OF_ADMINS:
            bot.send_message(chat_id=user_chat_id, text=f"🤖 Bot started! v{version}")

    def isMember(self, context, user_id):
        for chat_id in self.settings['channels']:
            try:
                _ = context.bot.get_chat_member(chat_id, user_id)
                return True
            except TelegramError:
                pass
        return False

    def getLevel(self, context, user_id):
        level = 0
        for chat_id in self.settings['channels']:
            try:
                _ = context.bot.get_chat_member(chat_id, int(user_id))
                level_ch = int(self.settings['channels'][chat_id].get('type', 0))
                level = level_ch if level_ch <= level else level
            except TelegramError:
                pass
        return level

    def runner(self):
        # Start the Bot
        self.updater.start_polling()
        # Run the bot until you press Ctrl-C or the process receives SIGINT,
        # SIGTERM or SIGABRT. This should be used most of the time, since
        # start_polling() is non-blocking and will stop the bot gracefully.
        self.updater.idle()

    def stop_and_restart(self):
        """Gracefully stop the Updater and replace the current process with a new one"""
        self.updater.stop()
        os.execl(sys.executable, sys.executable, *sys.argv)

    @restricted
    def restart(self, update, context):
        update.message.reply_text('Bot is restarting...')
        Thread(target=self.stop_and_restart).start()
    
    @restricted
    def config(self, update, context):
        """ Configuration bot """
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Make buttons
        buttons = [InlineKeyboardButton("Notifications", callback_data=f"CONF_NOTIFY {keyID}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"CONF_CANCEL {keyID}")))
        message = f"Configuration\n"
        for k, v in self.settings['config'].items():
            message += f" - {k}={v}\n"
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML', reply_markup=reply_markup)
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
        buttons = [InlineKeyboardButton("Enable" + (" [X]" if self.settings['config'].get('notify', True) else ""),
                                        callback_data=f"CONF_SAVE {keyID} notify=True"),
                   InlineKeyboardButton("Disable" + ("" if self.settings['config'].get('notify', True) else " [X]"),
                                        callback_data=f"CONF_SAVE {keyID} notify=False")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2))
        message = f"Notifications"
        # edit message
        query.edit_message_text(text=message, parse_mode='HTML', reply_markup=reply_markup)

    @restricted
    def ch_list(self, update, context):
        """ Bot manager """
        # Generate ID and seperate value from command
        keyID = str(uuid4())
        # Extract chat id
        buttons = []
        for chat_id in self.settings['channels']:
            title = context.bot.getChat(chat_id).title
            buttons += [InlineKeyboardButton(title, callback_data=f"CH_EDIT {keyID} id={chat_id}")]
        for chat_id in self.groups:
            title = context.bot.getChat(chat_id).title
            buttons += [InlineKeyboardButton(title + " [NEW!]", callback_data=f"CH_EDIT {keyID} id={chat_id}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"CH_CANCEL {keyID}")))
        message = 'List of new groups:' if buttons else 'No new groups'
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML', reply_markup=reply_markup)
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
            context.user_data[keyID][name] = value
        # Read chat_id
        chat_id = context.user_data[keyID]['id']
        # Populate configuration
        if chat_id in self.settings['channels']:
            for k, v in self.settings['channels'][chat_id].items():
                if k not in context.user_data[keyID]:
                    context.user_data[keyID][k] = v
        # Read title
        title = context.bot.getChat(chat_id).title
        # Make buttons
        buttons = [InlineKeyboardButton("Type", callback_data=f"CH_TYPE {keyID}"),
                   InlineKeyboardButton("Notify", callback_data=f"CH_NOTIFY {keyID}"),
                   InlineKeyboardButton("Store", callback_data=f"CH_SAVE {keyID}"),
                   InlineKeyboardButton("Remove", callback_data=f"CH_REMOVE {keyID}")]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 2, footer_buttons=InlineKeyboardButton("Cancel", callback_data=f"CH_CANCEL {keyID}")))
        # Make message
        message = f"{title}\n"
        for k, v in context.user_data[keyID].items():
            if k == 'type':
                v = ORbot.TYPE[v]
            message += f" - {k}={v}\n"
        query.edit_message_text(text=message, reply_markup=reply_markup)

    @check_key_id('Error message')
    def ch_type(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID, chat_id and title
        keyID = data[1]
        chat_id = context.user_data[keyID]['id']
        title = context.bot.getChat(chat_id).title
        # Make buttons
        buttons = [InlineKeyboardButton(ORbot.TYPE[typech], callback_data=f"CH_EDIT {keyID} type={typech}") for typech in ORbot.TYPE]
        reply_markup = InlineKeyboardMarkup(build_menu(buttons, 1))
        query.edit_message_text(text=f"{title}", reply_markup=reply_markup)

    def notifyNewChat(self, update, context, chat_id):
        chat = context.bot.getChat(chat_id)
        name = chat.title
        link = chat.invite_link
        level = int(self.settings['channels'][chat_id].get('type', 0)) if chat_id in self.settings['channels'] else 0

        for l_chat_id in self.settings['channels']:
            l_level = int(self.settings['channels'][chat_id].get('type', 0))
            # Check if this group can see other group with same level
            if l_chat_id == str(chat_id):
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
        # Notify new chat in all chats
        self.notifyNewChat(update, context, chat_id)
        # remove key from user_data list
        del context.user_data[keyID]
        # edit message
        query.edit_message_text(text=f"{chat.title} Notification sent!")

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
        if isAdmin(context, chat_id):
            # If None generate a link
            if chat.invite_link is None:
                context.bot.exportChatInviteLink(chat_id)
        # Add channel in list
        if str(chat_id) not in self.settings['channels']:
            self.settings['channels'][str(chat_id)] = {}
            new_channel = True
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
        with open(self.settings_file, 'w') as fp:
            json.dump(self.settings, fp)
        # Make message
        message = f"{chat.title} STORED!\n"
        for k, v in context.user_data[keyID].items():
            if k == 'type':
                v = ORbot.TYPE[v]
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

    def getChannels(self, update, context):
        buttons = []
        local_chat_id = str(update.effective_chat.id)
        if local_chat_id in self.settings['channels']:
            local_chat = context.bot.getChat(local_chat_id)
            local_level = int(self.settings['channels'][local_chat_id].get('type', 0))
            logger.debug(f"{local_chat.title} = {local_level}")
        else:
            local_level = self.getLevel(context, local_chat_id)
        for chat_id in self.settings['channels']:
            chat = context.bot.getChat(chat_id)
            name = chat.title
            link = chat.invite_link
            level = int(self.settings['channels'][chat_id].get('type', 0))
            if isAdmin(context, chat_id):
                # If None generate a link
                if link is None:
                    link = context.bot.exportChatInviteLink(chat_id)
            # Make flag lang
            # slang = flag(channel.get('lang', 'ita'))
            is_admin = ' (Bot not Admin)' if not isAdmin(context, chat_id) else ''
            # Check if this group can see other group with same level
            if local_level <= level and link is not None:
                buttons += [InlineKeyboardButton(name + is_admin, url=link)]
        return InlineKeyboardMarkup(build_menu(buttons, 1))

    def unknown(self, update, context):
        context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")

    @register
    def add_group(self, update, context):
        for member in update.message.new_chat_members:
            print(member)
            if not member.is_bot:
                if member.user.username != context.bot.username:
                    # Build list channels buttons
                    reply_markup = self.getChannels(update, context)
                    context.bot.send_message(chat_id=update.effective_chat.id,
                                             text=f"{member.username} Welcome! All channels avalable are:",
                                             reply_markup=reply_markup)

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
        reply_markup = self.getChannels(update, context)
        message = "All channels available are:" if reply_markup else 'No channels available'
        # Send message without reply in group
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML', reply_markup=reply_markup)

    def help(self, update, context):
        """ Help list of all commands """
        chat_id = update.effective_chat.id
        message = ""
        if chat_id in self.LIST_OF_ADMINS:
            message += "<b>Admin commands:</b>\n"
            message += " - /start your bot \n"
            message += " - /settings channels \n"
            message += " - /restart this bot \n"
            message += "\n"
        message += "All commands available in this bot are show below \n"
        # Print all commands availables
        message += " - All /channels available \n"
        message += " - This /help \n"
        # update.message.reply_text(message, parse_mode='HTML')
        context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='HTML')

    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)

# EOF

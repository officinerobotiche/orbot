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


import re
from uuid import uuid4
from telegram.ext import (Updater,
                          CommandHandler,
                          CallbackQueryHandler,
                          MessageHandler,
                          Filters,
                          CallbackContext,
                          ConversationHandler)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot, TelegramError
import logging
# Menu 
from .utils import build_menu, check_key_id, isAdmin, filter_channel, restricted, rtype

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BETA = True
START = 'start'
STOP = 'stop'

class Autoreply:

    def __init__(self, updater, context, chat_id, type, text, text_timeout, time=60, interval=10, keyID=None):
        # Usually th e keyID is automatically generated.
        # Do not use a keyID in a job timer message
        if keyID is None:
            # Generate ID and seperate value from command
            keyID = str(uuid4())
            # Set the user data
            context.user_data[keyID] = {'chat_id': chat_id}
        # set total time
        self.time = time
        # Interval update message
        self.interval = interval
        # Make control buttons
        msg = self.ctrl_buttons(context, chat_id, keyID, type, text)
        # Initialize the context to share
        data_timer = {'timer': self.time,
                      'message': msg.message_id,
                      'chat_id': chat_id,
                      'keyID': keyID,
                      'text': text,
                      'text_timeout': text_timeout,
                      'type_cb': type}
        # add job in recording dictionary
        self.job = updater.job_queue.run_repeating(self.timer_autoreply, context=data_timer, interval=self.interval, first=self.interval)

    def stop(self):
        # Stop the autoreply timer
        self.job.enabled = False  # Temporarily disable this job
        self.job.schedule_removal()  # Remove this job completely

    def timer_autoreply(self, context: CallbackContext):
        # Get job data
        job = context.job
        data_timer = context.job.context
        # Extract all context parameter
        timer = data_timer['timer']
        message = data_timer['message']
        chat_id = data_timer['chat_id']
        keyID = data_timer['keyID']
        text = data_timer['text']
        type_cb = data_timer['type_cb']
        # Update control buttons and text
        self.ctrl_buttons(context, chat_id, keyID, type_cb, f"{text} _({timer}s left)_", message)
        # Decrease timer
        context.job.context['timer'] -= self.interval
        # If timer left remove timer and send a message
        if timer <= 0:
            job.schedule_removal()
            # Send the message
            text = data_timer['text_timeout']
            context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message, parse_mode='Markdown')

    def ctrl_buttons(self, context, chat_id, keyID, type_cb, message, edit_msg=None):
        yes = InlineKeyboardButton("✅", callback_data=f"{type_cb} {keyID} true")
        no = InlineKeyboardButton("❌", callback_data=f"{type_cb} {keyID} false")
        reply_markup = InlineKeyboardMarkup(build_menu([yes, no], 2))
        if edit_msg is not None:
            context.bot.edit_message_text(chat_id=chat_id,
                                          message_id=edit_msg,
                                          text=message,
                                          parse_mode='Markdown',
                                          reply_markup=reply_markup)
            return None
        else:
            return context.bot.send_message(chat_id=chat_id,
                                           text=message,
                                           parse_mode='Markdown',
                                           reply_markup=reply_markup)

class Record:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Recording status
        self.recording = {}
        # Job queue
        self.job = self.updater.job_queue
        # Get the dispatcher to register handlers
        dp = self.updater.dispatcher
        # Text recorder
        summarize_handler = MessageHandler(Filters.text, self.record)
        dp.add_handler(summarize_handler)
        # Query messages
        dp.add_handler(CallbackQueryHandler(self.start, pattern='REC_START'))
        dp.add_handler(CallbackQueryHandler(self.stop, pattern='REC_STOP'))
        dp.add_handler(CallbackQueryHandler(self.timer_stop_cb, pattern='REC_TIMER_STOP'))

    def job_timer_reset(self, chat_id):
        # Stop the timer
        self.job_timer_stop(chat_id)
        # Start timer
        self.job_timer_start(chat_id)

    def job_timer_start(self, chat_id):
        # add job in recording dictionary
        self.recording[chat_id]['job'] = self.job.run_once(self.timer_stop, 5, context=chat_id)

    def job_timer_stop(self, chat_id):
        if 'job' in self.recording[chat_id]:
            job = self.recording[chat_id]['job']
            # Stop the timer
            job.enabled = False  # Temporarily disable this job
            job.schedule_removal()  # Remove this job completely

    def job_timer_delete(self, chat_id):
        if 'job' in self.recording[chat_id]:
            # Remove timer
            del self.recording[chat_id]['job']

    def record(self, update, context):
        #if update.edit_message is not None:
        #    print(update.edit_message.text)
        # Check is the message is not empty
        if update.message is None:
            logger.info("Empty message or edited")
            return
        # Check if not a private chat
        if update.message.chat.type == 'private':
            logger.info("Private chat")
            return
        chat_id = update.effective_chat.id
        if str(chat_id) not in self.settings['channels']:
            logger.info("Chat not authorized")
            return
        # Enable only beta channels
        if BETA:
            if not self.settings['channels'][str(chat_id)].get('beta', False):
                return
        # initialization recording chat
        if chat_id not in self.recording:
            self.recording[chat_id] = {'status': 'idle'}
        # print(update.message)
        # Message ID
        msg_id = update.message.message_id
        # Text message
        text = update.message.text
        # date message
        date = update.message.date
        # User ID
        user_id = update.message.from_user.id
        # Username
        username = update.message.from_user.username
        # Name
        firstname = update.message.from_user.first_name
        # Make message
        msg = {'msg_id': msg_id, 'date': date, 'user_id': user_id}
        # Add message in queue text
        self.recording[chat_id]['msg'] = msg
        # restart timer only if is active
        if 'job' in self.recording[chat_id]:
            # restart timer
            self.job_timer_reset(chat_id)
        # https://python-telegram-bot.readthedocs.io/en/latest/telegram.messageentity.html
        # entities = update.message.parse_entities()
        # Extract all hashtags
        hashtags = re.findall(r"#(\w+)", text)
        # check if there is the start hashtag
        start = True if START in hashtags else False
        stop = True if STOP in hashtags else False
        # Skip start and stop togheter
        if start and stop:
            logger.info("Start and stop togheter, skip control record")
            return
        # Message to store (sample)
        print(f"{date} - {username} - {firstname} - {text}")
        # Initialize recording
        chat_id = update.effective_chat.id
        text_timeout = f"Ok next time!"
        # If start is only in this text start to record
        if start:
            # Make buttons
            text = "📼 Do you want *record* this chat? 📼"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_START', text, text_timeout)
        if stop:
            # Make buttons
            text = "🚫 Do you want *stop* now? 🚫"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_STOP', text, text_timeout)

    def timer_stop(self, context: CallbackContext):
        # Extract chat ids
        chat_id = context.job.context
        text = "🚫 Do you want *stop* now? 🚫"
        text_timeout = f"Ok next time!"
        self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_STOP', text, text_timeout, keyID=chat_id)

    @check_key_id('Error message')
    def start(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID
        keyID = data[1]
        chat_id = context.user_data[keyID]['chat_id']
        # Stop the autoreply timer
        self.recording[chat_id]['job_autoreply'].stop()
        # Extract status record
        status = True if data[2] == 'true' else False
        if status:
            # Start timer
            self.job_timer_start(chat_id)
            # Message to send
            message = f"📼 *Recording*..."
            query.edit_message_text(text=message, parse_mode='Markdown')
        else:
            # Send the message
            message = f"Ok next time!"
            query.edit_message_text(text=message, parse_mode='Markdown')
        # remove key from user_data list
        del context.user_data[keyID]

    @check_key_id('Error message')
    def stop(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID
        keyID = data[1]
        chat_id = context.user_data[keyID]['chat_id']
        # Run callback stop
        self.cb_stop(update, context, chat_id)
        # remove key from user_data list
        del context.user_data[keyID]

    def timer_stop_cb(self, update, context):
        query = update.callback_query
        data = query.data.split()
        chat_id = int(data[1])
        # Run callback stop
        self.cb_stop(update, context, chat_id)

    def cb_stop(self, update, context, chat_id):
        query = update.callback_query
        data = query.data.split()
        # Stop the autoreply timer
        self.recording[chat_id]['job_autoreply'].stop()
        # Extract status record
        status = True if data[2] == 'true' else False
        if status:
            # Remove and stop the timer
            self.job_timer_stop(chat_id)
            self.job_timer_delete(chat_id)
            # Send message
            message = f"🛑 Recording *stop*!"
            query.edit_message_text(text=message, parse_mode='Markdown')
        else:
            # Start timer
            self.job_timer_reset(chat_id)
            # Send the message
            message = f"📼 *Recording*..."
            query.edit_message_text(text=message, parse_mode='Markdown')
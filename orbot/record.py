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
from collections import deque
import os
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

    def __init__(self, updater, context, chat_id, type, text, func_timeout, data, time=10, interval=5, keyID=None):
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
                      'func_timeout': func_timeout,
                      'data': data,
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
        message_id = data_timer['message']
        chat_id = data_timer['chat_id']
        keyID = data_timer['keyID']
        text = data_timer['text']
        type_cb = data_timer['type_cb']
        # Update control buttons and text
        self.ctrl_buttons(context, chat_id, keyID, type_cb, f"{text} _({timer}s left)_", message_id)
        # Decrease timer
        context.job.context['timer'] -= self.interval
        # If timer left remove timer and send a message
        if timer <= 0:
            job.schedule_removal()
            # Send the message
            func_timeout = data_timer['func_timeout']
            data = [type_cb, keyID, data_timer['data']]
            func_timeout(context, message_id, chat_id, data)

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

IDLE, WAIT_START, WAIT_STOP, WRITING = range(4)

class Record:

    def __init__(self, updater, settings, settings_file, channels):
        self.updater = updater
        self.settings_file = settings_file
        self.settings = settings
        self.channels = channels
        # Timeout autostop
        self.timeout = 5
        # Recording status
        self.recording = {}
        # Initialize folder records
        self.records_folder = self.settings['config'].get('records', 'records')
        if not os.path.isdir(self.records_folder):
            os.mkdir(self.records_folder)
            logger.info(f"Directory {self.records_folder} created")
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
        self.recording[chat_id]['job'] = self.job.run_once(self.timer_stop, self.timeout, context=chat_id)

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
            self.recording[chat_id] = {'status': IDLE, 'msgs': deque(maxlen=5)}
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
        msg = {'msg_id': msg_id, 'date': date, 'user_id': user_id, 'firstname': firstname, 'username': username, 'text': text}
        # Recording funcions
        if self.recording[chat_id]['status'] in [WRITING]:
            # Add message in queue text
            self.recording[chat_id]['msgs'].append(msg)
            self.writing(context, chat_id, msg)
        else:
            # Add message in queue text
            self.recording[chat_id]['msgs'].append(msg)            
        # restart timer only if is active
        if 'job' in self.recording[chat_id] and self.recording[chat_id]['status'] in [WRITING]:
            # restart timer
            self.job_timer_reset(chat_id)
        # https://python-telegram-bot.readthedocs.io/en/latest/telegram.messageentity.html
        # entities = update.message.parse_entities()
        # Extract all hashtags
        hashtags = re.findall(r"#(\w+)", text)
        # check if there is the start hashtag
        start = True if START in hashtags else False
        stop = True if STOP in hashtags else False
        # Initialize recording
        chat_id = update.effective_chat.id
        # If start is only in this text start to record
        if start and self.recording[chat_id]['status'] == IDLE:
            # Wait reply
            self.recording[chat_id]['status'] = WAIT_START
            # Send message
            text = "📼 Do you want *record* this chat? 📼"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_START', text, self.cb_start, 'false')
        elif stop and self.recording[chat_id]['status'] not in [IDLE, WAIT_START, WAIT_STOP]:
            # Remove and stop the timer
            self.job_timer_stop(chat_id)
            self.job_timer_delete(chat_id)
            # Send message
            text = "🚫 Do you want *stop* now? 🚫"
            self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_STOP', text, self.cb_stop, 'true')

    def writing(self, context, chat_id, msg):
        folder_name = str(chat_id)
        file_name = self.recording[chat_id]['file_name']
        # Append new line on file
        with open(f"{self.records_folder}/{folder_name}/{file_name}", "a") as f:
                f.write(msg['text'] + "\n")
        # log status
        logger.info(f"Chat {chat_id} in WRITING {msg['text']}")

    def init_record(self, context, chat_id):
        folder_name = str(chat_id)
        first_record = self.recording[chat_id]['msgs'][0]
        file_name = str(first_record['date']) + ".txt"
        self.recording[chat_id]['file_name'] = file_name
        # Make chat folder if not exist
        if not os.path.isdir(f"{self.records_folder}/{folder_name}"):
            os.mkdir(f"{self.records_folder}/{folder_name}")
            logger.info(f"Directory {folder_name} created")
        # Init file and write a file
        # "x" - Create - will create a file, returns an error if the file exist
        # "a" - Append - will create a file if the specified file does not exist
        # "w" - Write - will create a file if the specified file does not exist
        with open(f"{self.records_folder}/{folder_name}/{file_name}", "x") as f:
            for msg in self.recording[chat_id]['msgs']:
                f.write(msg['text'] + "\n")
        # log status
        logger.info(f"Chat {chat_id} in WRITING")

    def idle(self, context, chat_id):
        # Clear message list
        self.recording[chat_id]['msgs'].clear()
        # log status
        logger.info(f"Chat {chat_id} in IDLE")
        # Extract msgs
        text = ""
        folder_name = str(chat_id)
        file_name = self.recording[chat_id]['file_name']
        with open(f"{self.records_folder}/{folder_name}/{file_name}", "r") as f:
            for line in f:
                text += line
        if text:
            context.bot.send_message(chat_id=chat_id, text=text)

    def timer_stop(self, context: CallbackContext):
        # Extract chat ids
        chat_id = context.job.context
        # Wait reply
        self.recording[chat_id]['status'] = WAIT_STOP
        # Send message
        text = "*TOK TOK* There is anyone here?\n🚫 Do you want *stop* now? 🚫"
        self.recording[chat_id]['job_autoreply'] = Autoreply(self.updater, context, chat_id, 'REC_TIMER_STOP', text, self.cb_stop, 'true', keyID=chat_id)

    @check_key_id('Error message')
    def start(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID
        keyID = data[1]
        chat_id = context.user_data[keyID]['chat_id']
        # Start controller callback
        self.cb_start(context, query.message.message_id, chat_id, data)
        # remove key from user_data list
        del context.user_data[keyID]

    def cb_start(self, context, message_id, chat_id, data):
        # Stop the autoreply timer
        if chat_id in self.recording:
            if 'job_autoreply' in self.recording[chat_id]:
                self.recording[chat_id]['job_autoreply'].stop()
            # Extract status record
            status = True if data[2] == 'true' else False
            if status:
                # Start write mode
                self.init_record(context, chat_id)
                # Start timer
                self.job_timer_start(chat_id)
                # Initialize writing mode
                self.recording[chat_id]['status'] = WRITING
                # Message to send
                text = f"📼 *Recording*..."
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
            else:
                self.recording[chat_id]['status'] = IDLE
                # Send the message
                text = f"Ok next time!"
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
        else:
            text = "Error message"
            context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')


    @check_key_id('Error message')
    def stop(self, update, context):
        query = update.callback_query
        data = query.data.split()
        # Extract keyID
        keyID = data[1]
        chat_id = context.user_data[keyID]['chat_id']
        # Run callback stop
        self.cb_stop(context, query.message.message_id, chat_id, data)
        # remove key from user_data list
        del context.user_data[keyID]

    def timer_stop_cb(self, update, context):
        query = update.callback_query
        data = query.data.split()
        chat_id = int(data[1])
        # Run callback stop
        self.cb_stop(context, query.message.message_id, chat_id, data)

    def cb_stop(self, context, message_id, chat_id, data):
        # Stop the autoreply timer
        if chat_id in self.recording:
            if 'job_autoreply' in self.recording[chat_id]:
                self.recording[chat_id]['job_autoreply'].stop()
            # Extract status record
            status = True if data[2] == 'true' else False
            if status:
                # Remove and stop the timer
                self.job_timer_stop(chat_id)
                self.job_timer_delete(chat_id)
                # Set in idle mode and wait a new record
                self.idle(context, chat_id)
                # Set in idle mode
                self.recording[chat_id]['status'] = IDLE
                # Send message
                text = f"🛑 Recording *stop*!"
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
            else:
                # Start timer
                self.job_timer_reset(chat_id)
                # Send the message
                text = f"📼 *Recording*..."
                context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')
        else:
            text = "Error message"
            context.bot.edit_message_text(chat_id=chat_id, text=text, message_id=message_id, parse_mode='Markdown')